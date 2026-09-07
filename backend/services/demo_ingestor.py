"""
backend/services/demo_ingestor.py
===================================
Converts an OpenAdapt JSON export into structured lesson steps
and auto-extracts 96x96 px visual templates for each click action.

ROLE IN ARCHITECTURE  (TRAINING PATH ONLY -- never called at runtime):

  Expert records workflow with OpenAdapt
         |
  openadapt export --output recordings/word_bold.json
         |
  DemoIngestor.ingest_json("recordings/word_bold.json")
         |
    For every click event:
      1. _ground_label()     -> semantic label via OmniParser proximity
      2. _extract_template() -> crop 96x96 px patch, save PNG
      3. _generate_tts()     -> GuidanceComposer -> "Step N. Click X."
         |
  Returns list[dict] ready for lesson_repository.upsert_steps()

TEMPLATE EXTRACTION DETAIL:
  - A 96x96 px patch is cropped around the click coordinates.
  - Saved to: templates/<app_name_lower>/<safe_label>.png
  - Path stored in lesson_steps.template_path AND templates table.
  - UNIQUE(app_name, label) in DB deduplicates across recordings.
  - At runtime: pywinauto (5ms) -> template match (15ms) -> OmniParser (350ms)

SUPPORTED FORMATS:
  ingest_json()          - Raw OpenAdapt export JSON (click/type/scroll events)
  ingest_steps_list()    - Pre-built list[dict] (manual or scripted lessons)
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

try:
    import numpy as np
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False
    print("[DemoIngestor] WARNING: opencv-python not installed. Template extraction disabled.")

from services.guidance_composer import GuidanceComposer

# Where auto-extracted template PNGs are stored (relative to backend/)
TEMPLATE_ROOT = Path(__file__).parent.parent / "templates"

# Patch size (pixels) cropped around each click
TEMPLATE_PATCH_SIZE = 96


class DemoIngestor:
    """
    Reads an OpenAdapt JSON export, grounds each action to a semantic label,
    extracts visual templates, and generates coaching narrations.

    Args:
        screen_parser:       Optional ScreenParser instance for OmniParser grounding.
                             If None, labels default to pywinauto-style names.
        guidance_composer:   Optional GuidanceComposer instance.
                             If None, a default instance is constructed.
        screen_w:            Source screen width (pixels). Default 1920.
        screen_h:            Source screen height (pixels). Default 1080.
    """

    def __init__(
        self,
        screen_parser=None,
        guidance_composer: Optional[GuidanceComposer] = None,
        screen_w: int = 1920,
        screen_h: int = 1080,
    ) -> None:
        self._parser  = screen_parser
        self._composer = guidance_composer or GuidanceComposer()
        self._sw      = screen_w
        self._sh      = screen_h

    # =========================================================================
    # Public ingestors
    # =========================================================================

    def ingest_json(
        self,
        json_path: str,
        app_name_override: Optional[str] = None,
    ) -> list[dict]:
        """
        Load a raw OpenAdapt export JSON file and convert to lesson steps.

        Args:
            json_path:          Path to the OpenAdapt .json export.
            app_name_override:  Force a specific app name (overrides window_app field).

        Returns:
            list of step dicts suitable for ``lesson_repository.upsert_steps()``.
        """
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # OpenAdapt can export as a list of events OR a dict with an "events" key
        events = data if isinstance(data, list) else data.get("events", [])

        # Filter to action events only (skip metadata / window-change events)
        action_types = {"click", "double_click", "right_click", "type", "scroll", "key"}
        action_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type", "").lower() in action_types
        ]

        print(f"[DemoIngestor] Loaded {len(action_events)} action events from {json_path}")
        return self._build_steps(action_events, app_name_override)

    def ingest_steps_list(
        self,
        steps: list[dict],
        app_name: str = "Unknown",
    ) -> list[dict]:
        """
        Accept a pre-built list of step dicts (manual or scripted lessons).
        Fills in missing tts_text via GuidanceComposer.

        Each dict must have at least: action, target
        Optional: target_type, tts_text, template_path, bbox_x1/y1/x2/y2
        """
        result: list[dict] = []
        for i, s in enumerate(steps):
            action = s.get("action", "click")
            label  = s.get("target", "")
            tts    = s.get("tts_text", "").strip()
            if not tts:
                tts = self._composer.compose(action, label, i + 1, app_name)
            result.append({
                "step_index":    i,
                "action":        action,
                "target":        label,
                "target_type":   s.get("target_type", "Button"),
                "value":         s.get("value", ""),
                "tts_text":      tts,
                "template_path": s.get("template_path"),
                "bbox_x1":       s.get("bbox_x1"),
                "bbox_y1":       s.get("bbox_y1"),
                "bbox_x2":       s.get("bbox_x2"),
                "bbox_y2":       s.get("bbox_y2"),
            })
        return result

    # =========================================================================
    # Internals
    # =========================================================================

    def _build_steps(
        self, events: list[dict], app_name_override: Optional[str]
    ) -> list[dict]:
        steps: list[dict] = []
        step_num = 0

        for event in events:
            evt_type   = event.get("type", "click").lower()
            px         = int(event.get("x", 0))
            py         = int(event.get("y", 0))
            text_val   = event.get("text") or ""
            window_app = app_name_override or event.get("window_app", "Unknown")
            screenshot_b64 = event.get("screenshot_b64", "")

            # Ground to semantic label
            label = self._ground_label(screenshot_b64, px, py)
            if not label:
                # Fall back to coordinate-based label
                label = f"element_at_{px}_{py}"

            # Extract visual template patch
            template_path = None
            if screenshot_b64 and evt_type in {"click", "double_click", "right_click"}:
                template_path = self._extract_template(
                    screenshot_b64, px, py, window_app, label
                )

            # Generate coaching narration
            tts = self._composer.compose(evt_type, label, step_num + 1, window_app)

            steps.append({
                "step_index":    step_num,
                "action":        evt_type,
                "target":        label,
                "target_type":   "Button",
                "value":         text_val,
                "tts_text":      tts,
                "template_path": template_path,
                # Store original recording coordinates as normalised bbox fallback.
                # bbox_x1/y1 = click centre (normalised 0-1 relative to source screen).
                # Used at runtime when template matching fails: overlay is placed here.
                "bbox_x1":  px / self._sw if px else None,
                "bbox_y1":  py / self._sh if py else None,
                "bbox_x2":  (px + 48) / self._sw if px else None,
                "bbox_y2":  (py + 48) / self._sh if py else None,
            })
            step_num += 1


        print(f"[DemoIngestor] Built {len(steps)} steps.")
        return steps

    def _ground_label(
        self, screenshot_b64: str, px: int, py: int
    ) -> str:
        """
        Find the UI element label closest to the click point.

        Priority:
          1. OmniParser proximity match (if screen_parser available)
          2. Empty string (caller uses coordinate-based fallback)
        """
        if not self._parser or not screenshot_b64:
            return ""

        try:
            sc_bytes = base64.b64decode(screenshot_b64)
            elements = self._parser.parse(sc_bytes, self._sw, self._sh)
            if not elements:
                return ""

            # Find element whose bounding box centre is closest to (px, py)
            best_label = ""
            best_dist  = float("inf")
            for el in elements:
                if not el.label:
                    continue
                cx = (el.bbox_norm[0] + el.bbox_norm[2]) * 0.5 * self._sw
                cy = (el.bbox_norm[1] + el.bbox_norm[3]) * 0.5 * self._sh
                dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist  = dist
                    best_label = el.label

            return best_label
        except Exception as exc:
            print(f"[DemoIngestor] _ground_label failed: {exc}")
            return ""

    def _extract_template(
        self,
        screenshot_b64: str,
        px: int,
        py: int,
        app_name: str,
        label: str,
        patch_size: int = TEMPLATE_PATCH_SIZE,
    ) -> Optional[str]:
        """
        Crop a patch_size x patch_size region around (px, py) from the screenshot.
        Save as: templates/<app_slug>/<label_slug>.png
        Return the relative file path, or None on failure.

        The UNIQUE(app_name, label) constraint in the templates table means
        recording the same workflow twice simply overwrites the template.
        """
        if not _CV2_OK:
            return None

        try:
            img_bytes = base64.b64decode(screenshot_b64)
            img_arr   = np.frombuffer(img_bytes, dtype=np.uint8)
            img       = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            if img is None:
                return None

            h, w     = img.shape[:2]
            half     = patch_size // 2
            x1, y1   = max(0, px - half), max(0, py - half)
            x2, y2   = min(w, px + half), min(h, py + half)
            patch    = img[y1:y2, x1:x2]

            # Build directory: templates/winword/ or templates/excel/ etc.
            app_slug   = (
                app_name.upper()
                .replace(".EXE", "")
                .replace(" ", "_")
                .lower()
            )
            label_slug = (
                label.lower()
                .replace(" ", "_")
                .replace("/", "_")
                .replace("\\", "_")
            )[:48]

            app_dir = TEMPLATE_ROOT / app_slug
            app_dir.mkdir(parents=True, exist_ok=True)

            out_path    = app_dir / f"{label_slug}.png"
            cv2.imwrite(str(out_path), patch)

            # Return relative path from backend/ for portability
            rel_path = str(out_path.relative_to(Path(__file__).parent.parent))
            print(f"[DemoIngestor] Template saved: {rel_path}")
            return rel_path

        except Exception as exc:
            print(f"[DemoIngestor] _extract_template failed: {exc}")
            return None
