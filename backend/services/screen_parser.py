"""
backend/services/screen_parser.py
===================================
Unified UI screen grounding layer for the UI Copilot + Lesson pipeline.

WHAT THIS DOES:
  Parses a screenshot into a structured list of UIElement objects, each
  with a label, bounding box (normalised 0–1), element type, and source.

  This gives us three grounding layers:
    • OmniParser  → detects UI widgets, icons, and buttons even without
                    accessibility APIs (works on any Windows app).
    • PaddleOCR   → reads text labels, menu items, form field values.
    • pywinauto   → remains as a semantic fallback (handled in ui_detector).

SETUP (one-time):
  # OmniParser
  git clone https://github.com/microsoft/OmniParser
  pip install -r OmniParser/requirements.txt
  # Download OmniParser-v2 weights:
  #   https://huggingface.co/microsoft/OmniParser-v2
  # Place weights at:
  #   OmniParser/weights/icon_detect/model.pt
  #   OmniParser/weights/icon_caption_florence/  (directory)

  # PaddleOCR
  pip install paddleocr paddlepaddle

RUNTIME BEHAVIOUR:
  • If OmniParser weights are not downloaded → OmniParser is skipped silently.
  • If PaddleOCR is not installed → PaddleOCR is skipped silently.
  • All errors are caught and logged — no crash on parser failure.
"""

from __future__ import annotations

import base64
import io
import os
import sys

# Disable buggy PaddleOneDNN CPU executor flags
os.environ["FLAGS_use_onednn"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"

from dataclasses import dataclass, field
from typing import Optional
import threading

# ── PIL ───────────────────────────────────────────────────────────────────────
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[ScreenParser] WARNING: Pillow not installed. Run: pip install pillow")

# ── NumPy ─────────────────────────────────────────────────────────────────────
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("[ScreenParser] WARNING: numpy not installed. OCR grounding disabled.")

# ── OmniParser ────────────────────────────────────────────────────────────────
# OmniParser is a cloned repo (not a pip package).
# Repo:     git clone https://github.com/microsoft/OmniParser
# Weights:  https://huggingface.co/microsoft/OmniParser-v2  →  OmniParser/weights/
#
# Real API (from util/omniparser.py):
#   Omniparser(config)  where config = {'som_model_path', 'caption_model_name',
#                                        'caption_model_path', 'BOX_TRESHOLD'}
#   .parse(image_base64: str) -> (labeled_img, parsed_content_list)
#
# parsed_content_list items are dicts:
#   {'type': 'icon'|'text', 'bbox': [x1,y1,x2,y2] (absolute px),
#    'interactivity': bool, 'content': 'label text', 'source': '...'}

_OMNI_REPO      = os.getenv("OMNIPARSER_REPO_PATH",    "OmniParser")
_OMNI_WEIGHTS   = os.getenv("OMNIPARSER_WEIGHTS_PATH", "OmniParser/weights")
OMNI_AVAILABLE  = False
_Omniparser_cls = None

if os.path.isdir(_OMNI_REPO):
    _util_path = os.path.abspath(_OMNI_REPO)
    if _util_path not in sys.path:
        sys.path.insert(0, _util_path)
    try:
        # Patch transformers PreTrainedModel._supports_sdpa for compatibility with older cached Florence-2 files
        try:
            import transformers
            if hasattr(transformers, "PreTrainedModel") and not hasattr(transformers.PreTrainedModel, "_supports_sdpa"):
                transformers.PreTrainedModel._supports_sdpa = True
        except ImportError:
            pass

        from util.omniparser import Omniparser as _Omniparser_cls   # type: ignore
        OMNI_AVAILABLE = True
        print(f"[ScreenParser] OmniParser (Omniparser class) found at {_OMNI_REPO!r}.")
    except ImportError as e:
        print(f"[ScreenParser] OmniParser import failed: {e}. "
              "Check: pip install -r OmniParser/requirements.txt")
else:
    print(f"[ScreenParser] OmniParser repo not found at {_OMNI_REPO!r}. "
          "Clone it: git clone https://github.com/microsoft/OmniParser")

# ── PaddleOCR ─────────────────────────────────────────────────────────────────
PADDLE_AVAILABLE = False
_PaddleOCR_cls   = None

try:
    # Resolve Windows Python 3.8+ DLL loading issue for nvidia cuDNN/cuBLAS packages
    import sys
    if sys.platform.startswith("win"):
        import os
        for p in sys.path:
            nvidia_dir = os.path.join(p, "nvidia")
            if os.path.isdir(nvidia_dir):
                for sub in os.listdir(nvidia_dir):
                    bin_path = os.path.join(nvidia_dir, sub, "bin")
                    if os.path.isdir(bin_path):
                        try:
                            os.add_dll_directory(bin_path)
                        except Exception:
                            pass

    from paddleocr import PaddleOCR as _PaddleOCR_cls   # type: ignore
    PADDLE_AVAILABLE = True
    print("[ScreenParser] PaddleOCR package found.")
except ImportError:
    print("[ScreenParser] PaddleOCR not installed. "
          "Run: pip install paddleocr paddlepaddle")


# ─────────────────────────────────────────────────────────────────────────────
# DATA MODEL
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UIElement:
    """
    A single UI element detected on the screen.

    bbox_norm: [x1, y1, x2, y2] in normalised coordinates (0.0 – 1.0).
               x1/y1 = top-left corner, x2/y2 = bottom-right corner.
    source:    which parser detected this element.
    """
    label:      str                      # Human-readable label (e.g. "Insert", "PivotTable")
    bbox_norm:  list                     # [x1, y1, x2, y2] normalised 0–1
    type:       str   = "Button"         # Button | MenuItem | Edit | Icon | Text | TabItem
    text:       str   = ""              # Raw OCR text (may differ from label after cleanup)
    confidence: float = 1.0            # Detector confidence (0–1)
    source:     str   = "omniparser"   # omniparser | ocr | pywinauto


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN PARSER
# ─────────────────────────────────────────────────────────────────────────────

class ScreenParser:
    """
    Unified screen grounding service.

    Usage:
        parser = ScreenParser()   # create once (module-level singleton)
        elements = parser.parse(screenshot_bytes, screen_w=1920, screen_h=1080)
        el = parser.find_element(elements, "Insert tab")
        cx, cy = parser.center_px(el, 1920, 1080)

    Thread safety:
        parse() is thread-safe — each call is independent.
    """

    def __init__(self,
                 omni_enabled:   bool = True,
                 paddle_enabled: bool = True,
                 paddle_lang:    str  = "en"):
        self._omni        = None   # Omniparser instance (lazy-loaded)
        self._ocr         = None   # PaddleOCR instance (lazy-loaded)
        self._omni_lock   = threading.Lock()
        self._ocr_lock    = threading.Lock()
        self._omni_enabled   = omni_enabled   and OMNI_AVAILABLE
        self._paddle_enabled = paddle_enabled and PADDLE_AVAILABLE
        self._paddle_lang    = paddle_lang

        available = []
        if self._omni_enabled:   available.append("OmniParser")
        if self._paddle_enabled: available.append(f"PaddleOCR({paddle_lang})")
        if available:
            print(f"[ScreenParser] Active parsers: {', '.join(available)}")
        else:
            print("[ScreenParser] No vision parsers active — "
                  "pywinauto-only fallback will be used for element resolution.")

    # ── Public API ───────────────────────────────────────────────────────────

    def parse(self,
              screenshot_bytes: bytes,
              screen_w: int,
              screen_h: int) -> list:
        """
        Parse a JPEG/PNG screenshot into a list of UIElements.

        Args:
            screenshot_bytes: Raw image bytes (JPEG or PNG).
            screen_w:         Width of the source screen in pixels.
            screen_h:         Height of the source screen in pixels.

        Returns:
            List of UIElement (may be empty if no parsers available).
        """
        if not PIL_AVAILABLE or not screenshot_bytes:
            return []

        try:
            img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        except Exception as e:
            print(f"[ScreenParser] Image decode failed: {e}")
            return []

        elements = []

        # 1. OmniParser — detect UI widgets and icons
        if self._omni_enabled:
            try:
                elements.extend(self._run_omni(img))
            except Exception as e:
                print(f"[ScreenParser] OmniParser error: {e}")

        # 2. PaddleOCR — detect text regions not already covered by OmniParser
        if self._paddle_enabled and NUMPY_AVAILABLE:
            try:
                existing_bboxes = [el.bbox_norm for el in elements]
                elements.extend(self._run_ocr(img, existing_bboxes))
            except Exception as e:
                print(f"[ScreenParser] PaddleOCR error: {e}")

        return elements

    def find_element(self,
                     elements: list,
                     label: str,
                     threshold: float = 0.35) -> Optional[UIElement]:
        """
        Find the UIElement whose label best matches the given label string.

        Matching strategy (in order):
          1. Exact match (case-insensitive)
          2. Substring containment (either direction)
          3. Token overlap (Jaccard of word sets) above threshold

        Returns None if no element passes the threshold.
        """
        if not label or not elements:
            return None

        label_lower = label.strip().lower()
        best, best_score = None, 0.0

        for el in elements:
            el_lower = el.label.strip().lower()

            # Exact match
            if el_lower == label_lower:
                return el

            # Substring containment
            if label_lower in el_lower or el_lower in label_lower:
                a = set(label_lower.split())
                b = set(el_lower.split())
                score = len(a & b) / max(len(a | b), 1)
                if score > best_score:
                    best_score, best = score, el
                continue

            # Token Jaccard
            a_words = set(label_lower.split())
            b_words = set(el_lower.split())
            denom = len(a_words | b_words)
            if denom > 0:
                jaccard = len(a_words & b_words) / denom
                if jaccard > best_score:
                    best_score, best = jaccard, el

        return best if best_score >= threshold else None

    def center_px(self, el: UIElement, screen_w: int, screen_h: int):
        """
        Convert a UIElement's bbox_norm to absolute pixel center coordinates.
        Returns (cx_px, cy_px).
        """
        cx = (el.bbox_norm[0] + el.bbox_norm[2]) * 0.5 * screen_w
        cy = (el.bbox_norm[1] + el.bbox_norm[3]) * 0.5 * screen_h
        return cx, cy

    def size_px(self, el: UIElement, screen_w: int, screen_h: int):
        """Return (width_px, height_px) of the element's bounding box."""
        w = (el.bbox_norm[2] - el.bbox_norm[0]) * screen_w
        h = (el.bbox_norm[3] - el.bbox_norm[1]) * screen_h
        return w, h

    # ── OmniParser ───────────────────────────────────────────────────────────

    def _get_omni(self):
        """
        Lazy-load OmniParser on first call (~2–4 s for weight loading).

        Config paths follow the OmniParser-v2 weight structure:
          OmniParser/weights/icon_detect/model.pt        (YOLOv8 icon detector)
          OmniParser/weights/icon_caption_florence/       (Florence-2 caption model)
        """
        if self._omni is not None:
            return self._omni
        with self._omni_lock:
            if self._omni is not None:
                return self._omni
            if not OMNI_AVAILABLE or _Omniparser_cls is None:
                return None
            weights = os.path.abspath(_OMNI_WEIGHTS)
            config = {
                # YOLOv8 icon detector weights
                "som_model_path":     os.path.join(weights, "icon_detect", "model.pt"),
                # Caption model: OmniParser-v2 uses Florence-2 (folder: icon_caption)
                # The folder name on HuggingFace is 'icon_caption', not 'icon_caption_florence'
                "caption_model_name": "florence2",
                "caption_model_path": os.path.join(weights, "icon_caption"),
                # Detection confidence threshold (0.05 = detect most elements)
                "BOX_TRESHOLD":       0.05,
            }
            # Check that weights exist before trying to load
            if not os.path.exists(config["som_model_path"]):
                print(
                    f"[ScreenParser] OmniParser weights not found at {config['som_model_path']!r}.\n"
                    "  Download from: https://huggingface.co/microsoft/OmniParser-v2\n"
                    "  Place in: OmniParser/weights/icon_detect/model.pt\n"
                    "  Set OMNIPARSER_ENABLED=false in .env to suppress this message."
                )
                return None
            try:
                self._omni = _Omniparser_cls(config)
                print("[ScreenParser] OmniParser loaded successfully.")
            except Exception as e:
                print(f"[ScreenParser] OmniParser load failed: {e}")
        return self._omni

    def _run_omni(self, img) -> list:
        """
        Run OmniParser on a PIL image and return UIElements.

        OmniParser.parse(base64_str) returns (labeled_img, parsed_content_list).
        Each item in parsed_content_list is a dict:
            {'type': 'icon'|'text', 'bbox': [x1,y1,x2,y2] (absolute pixels),
             'interactivity': bool, 'content': 'label', 'source': '...'}
        """
        omni = self._get_omni()
        if omni is None:
            return []

        # OmniParser requires base64-encoded JPEG input
        try:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            print(f"[ScreenParser] Image encoding for OmniParser failed: {e}")
            return []

        try:
            _, content_list = omni.parse(img_b64)
        except Exception as e:
            print(f"[ScreenParser] OmniParser.parse() failed: {e}")
            return []

        elements = []
        W, H = img.width, img.height

        for item in (content_list or []):
            try:
                label = str(item.get("content", "") or "").strip()
                bbox  = item.get("bbox", [])
                etype = str(item.get("type", "icon"))
                if not label or len(bbox) < 4:
                    continue

                bbox_norm = self._normalise_bbox(bbox, W, H)
                if bbox_norm is None:
                    continue

                elements.append(UIElement(
                    label      = label,
                    bbox_norm  = bbox_norm,
                    type       = "Text" if etype == "text" else "Icon",
                    confidence = 1.0,
                    source     = "omniparser",
                ))
            except Exception:
                continue

        return elements

    # ── PaddleOCR ────────────────────────────────────────────────────────────

    def _get_ocr(self):
        """Lazy-load PaddleOCR on first call."""
        if self._ocr is not None:
            return self._ocr
        with self._ocr_lock:
            if self._ocr is not None:
                return self._ocr
            try:
                self._ocr = _PaddleOCR_cls(
                    lang=self._paddle_lang,
                    device="cpu",
                )
                print(f"[ScreenParser] PaddleOCR loaded (lang={self._paddle_lang!r}, device='cpu').")
            except Exception as e:
                print(f"[ScreenParser] PaddleOCR init failed: {e}")
        return self._ocr

    def _run_ocr(self, img, existing_bboxes: list) -> list:
        """
        Run PaddleOCR and return text regions NOT already covered by OmniParser.
        We skip OCR results that overlap significantly with an existing OmniParser bbox.
        """
        ocr = self._get_ocr()
        if ocr is None:
            return []

        img_np = np.array(img)

        try:
            try:
                raw = ocr.ocr(img_np, cls=True)
            except TypeError:
                # If cls is not a valid keyword arg in this version
                raw = ocr.ocr(img_np)
        except Exception as e:
            print(f"[ScreenParser] PaddleOCR.ocr() failed: {e}")
            return []

        elements = []
        W, H = img.width, img.height

        for group in (raw or []):
            for entry in (group or []):
                try:
                    # entry = [[pts...], (text, confidence)]
                    pts, (text, conf) = entry
                    text = str(text).strip()
                    if not text or conf < 0.5:
                        continue

                    # pts = [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    bbox_norm = [
                        min(xs) / W, min(ys) / H,
                        max(xs) / W, max(ys) / H,
                    ]

                    # Skip if already covered by OmniParser detection
                    if self._is_covered(bbox_norm, existing_bboxes, iou_threshold=0.5):
                        continue

                    elements.append(UIElement(
                        label      = text,
                        bbox_norm  = bbox_norm,
                        type       = "Text",
                        text       = text,
                        confidence = float(conf),
                        source     = "ocr",
                    ))
                except Exception:
                    continue

        return elements

    # ── Static Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_bbox(bbox, img_w: int, img_h: int):
        """
        Accept bbox in [x1,y1,x2,y2] form (absolute pixels or normalised 0–1).
        Returns normalised [x1,y1,x2,y2] or None if invalid.
        """
        try:
            if len(bbox) < 4:
                return None
            x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            # If values > 1 they are absolute pixel coords
            if x2 > 1.5 or y2 > 1.5:
                x1, y1, x2, y2 = x1 / img_w, y1 / img_h, x2 / img_w, y2 / img_h
            # Clamp to [0,1]
            x1, y1 = max(0.0, x1), max(0.0, y1)
            x2, y2 = min(1.0, x2), min(1.0, y2)
            if x2 <= x1 or y2 <= y1:
                return None
            return [x1, y1, x2, y2]
        except Exception:
            return None

    @staticmethod
    def _is_covered(bbox: list, existing: list, iou_threshold: float = 0.5) -> bool:
        """Return True if bbox overlaps significantly with any existing bbox (IoU > threshold)."""
        x1, y1, x2, y2 = bbox
        for ex in existing:
            ex1, ey1, ex2, ey2 = ex
            ix1 = max(x1, ex1); iy1 = max(y1, ey1)
            ix2 = min(x2, ex2); iy2 = min(y2, ey2)
            if ix2 <= ix1 or iy2 <= iy1:
                continue
            intersection = (ix2 - ix1) * (iy2 - iy1)
            union = ((x2 - x1) * (y2 - y1)) + ((ex2 - ex1) * (ey2 - ey1)) - intersection
            if union > 0 and intersection / union > iou_threshold:
                return True
        return False
