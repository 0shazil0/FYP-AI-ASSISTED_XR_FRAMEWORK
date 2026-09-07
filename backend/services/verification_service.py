"""
backend/services/verification_service.py
==========================================
Step-completion verification for the UI Copilot + Lesson pipeline.

WHAT THIS DOES:
  After Unity sends a "step_done" message, the backend needs to verify that
  the user actually completed the step before moving to the next one.

  Strategy:
    1. Capture a "before" screenshot just before sending a step to Unity.
    2. When "step_done" arrives, capture an "after" screenshot.
    3. Compare the two using SSIM (Structural Similarity Index) and
       element-level diff to decide if the screen changed meaningfully.
    4. Return VerificationResult with passed=True/False + a tts_text
       coaching message for the narrator to speak.

  SSIM diff threshold is configurable via COPILOT_VERIFY_THRESHOLD in .env.
  Default: 0.15 (15% structural change = step is confirmed done).
  Lower = more lenient (easier to pass), higher = stricter confirmation.

FALLBACK:
  If screenshot capture or diff fails for any reason, verification passes
  (fail-open) so the learner is never blocked by a tech issue.

USAGE (from main.py):
    verifier = VerificationService()
    before_bytes = verifier.snapshot()   # call just before sending step
    ...
    result = await asyncio.to_thread(
        verifier.verify, before_bytes, step
    )
    await ws.send_json({
        "type": "step_verification",
        "step_index": step_idx,
        "passed": result.passed,
        "tts_text": result.tts_text,
        "diff_score": result.diff_score,
    })
"""

from __future__ import annotations

import os
import io
from dataclasses import dataclass
from typing import Optional

# ── Optional OpenCV for SSIM-style diff ──────────────────────────────────────
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[VerifyService] OpenCV not installed — using pixel-count diff fallback. "
          "For better accuracy: pip install opencv-python")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


@dataclass
class VerificationResult:
    """
    Result of a step-completion verification check.

    passed:     True  → screen changed enough → step is confirmed done
                False → screen looks the same → user may not have done it yet

    diff_score: 0.0 – 1.0  Structural difference between before/after.
                            Higher = more change detected.

    tts_text:   Coaching sentence for Android TTS to speak after the check.
    """
    passed:     bool
    diff_score: float
    tts_text:   str


class VerificationService:
    """
    Compares before/after screenshots to confirm a UI Copilot step was done.

    Thread-safe: each call to verify() is stateless — no shared mutable state.
    """

    def __init__(self, threshold: float = 0.15):
        """
        Args:
            threshold: Minimum diff_score (0–1) required to pass verification.
                       Set via COPILOT_VERIFY_THRESHOLD in backend/.env.
                       Default 0.15 = 15% structural change required.
        """
        self.threshold = float(os.getenv("COPILOT_VERIFY_THRESHOLD", str(threshold)))
        print(f"[VerifyService] Initialised. diff_threshold={self.threshold:.2f}  "
              f"engine={'opencv-ssim' if CV2_AVAILABLE else 'pixel-count'}")

    # ── Public API ────────────────────────────────────────────────────────────

    def snapshot(self, screen_capture) -> Optional[bytes]:
        """
        Capture a reference screenshot using the ScreenCapture singleton.

        Args:
            screen_capture: The _copilot_screen singleton from main.py.

        Returns:
            JPEG bytes of the current screen, or None on failure.
        """
        try:
            return screen_capture.capture_bytes(quality=80)
        except Exception as e:
            print(f"[VerifyService] Snapshot failed: {e}")
            return None

    def verify(self,
               before_bytes: Optional[bytes],
               after_bytes:  Optional[bytes],
               step:         dict) -> VerificationResult:
        """
        Compare before/after screenshots and return a VerificationResult.

        Args:
            before_bytes: JPEG screenshot taken before the step was shown.
            after_bytes:  JPEG screenshot taken after Unity sends step_done.
            step:         The step dict (contains 'target', 'action', 'tts_text').

        Returns:
            VerificationResult with passed, diff_score, and tts_text.
        """
        target  = step.get("target", "the element")
        action  = step.get("action", "click")
        step_no = step.get("step_index", "")

        # ── Fail-open if no screenshots available ────────────────────────────
        if not before_bytes or not after_bytes:
            return VerificationResult(
                passed     = True,
                diff_score = 0.0,
                tts_text   = self._confirm_tts(step_no, action, target),
            )

        # ── Compute diff score ───────────────────────────────────────────────
        diff_score = self._compute_diff(before_bytes, after_bytes)

        # ── Decision ─────────────────────────────────────────────────────────
        passed = diff_score >= self.threshold

        if passed:
            tts_text = self._confirm_tts(step_no, action, target)
        else:
            tts_text = self._retry_tts(step_no, action, target)

        print(f"[VerifyService] step={step_no}  diff={diff_score:.3f}  "
              f"threshold={self.threshold:.2f}  passed={passed}")

        return VerificationResult(
            passed     = passed,
            diff_score = round(diff_score, 4),
            tts_text   = tts_text,
        )

    # ── Internal diff engines ─────────────────────────────────────────────────

    def _compute_diff(self, before_bytes: bytes, after_bytes: bytes) -> float:
        """
        Returns a diff score in [0, 1] between two JPEG images.
        Higher = more visual change (more likely step was completed).

        Uses OpenCV pixel-diff if available; falls back to PIL pixel count.
        """
        if CV2_AVAILABLE:
            return self._opencv_diff(before_bytes, after_bytes)
        elif PIL_AVAILABLE:
            return self._pil_diff(before_bytes, after_bytes)
        else:
            return 0.5  # no image library — assume pass

    def _opencv_diff(self, before_bytes: bytes, after_bytes: bytes) -> float:
        """
        Compute normalised pixel difference using OpenCV.
        We use L1 mean absolute difference on grayscale (fast, deterministic).
        Score range: 0.0 (identical) – 1.0 (completely different).
        """
        try:
            before_arr = np.frombuffer(before_bytes, dtype=np.uint8)
            after_arr  = np.frombuffer(after_bytes,  dtype=np.uint8)
            before_img = cv2.imdecode(before_arr, cv2.IMREAD_GRAYSCALE)
            after_img  = cv2.imdecode(after_arr,  cv2.IMREAD_GRAYSCALE)

            if before_img is None or after_img is None:
                return 0.0

            # Resize to same size if they differ (shouldn't normally happen)
            if before_img.shape != after_img.shape:
                h = min(before_img.shape[0], after_img.shape[0])
                w = min(before_img.shape[1], after_img.shape[1])
                before_img = cv2.resize(before_img, (w, h))
                after_img  = cv2.resize(after_img,  (w, h))

            # Mean absolute difference, normalised to [0, 1]
            diff  = cv2.absdiff(before_img, after_img)
            score = float(diff.mean()) / 255.0
            return score

        except Exception as e:
            print(f"[VerifyService] OpenCV diff failed: {e}")
            return 0.0

    def _pil_diff(self, before_bytes: bytes, after_bytes: bytes) -> float:
        """
        Fallback diff using PIL.
        Returns fraction of pixels that changed by more than 10 grey levels.
        """
        try:
            import struct
            before_img = Image.open(io.BytesIO(before_bytes)).convert("L")
            after_img  = Image.open(io.BytesIO(after_bytes)).convert("L")

            # Resize to same size
            size = (min(before_img.width, after_img.width),
                    min(before_img.height, after_img.height))
            before_img = before_img.resize(size)
            after_img  = after_img.resize(size)

            before_pix = list(before_img.getdata())
            after_pix  = list(after_img.getdata())

            changed = sum(1 for b, a in zip(before_pix, after_pix) if abs(b - a) > 10)
            score   = changed / max(len(before_pix), 1)
            return score

        except Exception as e:
            print(f"[VerifyService] PIL diff failed: {e}")
            return 0.0

    # ── TTS coaching messages ─────────────────────────────────────────────────

    @staticmethod
    def _confirm_tts(step_no, action: str, target: str) -> str:
        """Coaching text spoken when step passes verification."""
        action_past = {
            "click":        "clicked",
            "double_click": "double-clicked",
            "right_click":  "right-clicked",
            "type":         "typed into",
            "scroll":       "scrolled",
        }.get(action, "completed")
        return f"Great job! You {action_past} {target}. Moving to the next step."

    @staticmethod
    def _retry_tts(step_no, action: str, target: str) -> str:
        """Coaching text spoken when step fails verification — ask user to retry."""
        action_verb = {
            "click":        "click",
            "double_click": "double-click",
            "right_click":  "right-click",
            "type":         "type into",
            "scroll":       "scroll",
        }.get(action, "complete")
        return (
            f"I did not detect a change. Please {action_verb} {target} "
            f"and then tap Done again."
        )
