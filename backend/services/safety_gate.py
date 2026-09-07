"""
backend/services/safety_gate.py
=================================
Content safety gate for the UI Copilot narrator layer.

WHAT THIS DOES:
  Filters narrator text (the tts_text spoken aloud to the learner) through
  NVIDIA's nemotron-3.5-content-safety model before sending to Android TTS.

  This prevents inappropriate, offensive, or sensitive content from being
  spoken out loud in a corporate training environment.

HOW IT WORKS:
  FYP mode  (USE_NIM=false):  pass-through — all text is returned unchanged.
  Production (USE_NIM=true):  calls nemotron-3.5-content-safety via NIM API.
                              If flagged → "[Content filtered]" is returned instead.

USAGE:
    from services.safety_gate import SafetyGate
    gate = SafetyGate()
    safe_text = gate.filter("Click the File menu to open the document.")
"""

from __future__ import annotations

import os
from typing import Optional


class SafetyGate:
    """
    Content safety filter for narrator (tts_text) output.
    Thread-safe — uses a stateless HTTP call per check (no shared state).
    """

    def __init__(self):
        # Read NIM settings from environment (already validated in config.py)
        self._use_nim   = os.getenv("USE_NIM", "false").strip().lower() in {"1","true","yes","on"}
        self._api_key   = os.getenv("NIM_API_KEY",  "").strip()
        self._base_url  = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        self._model     = os.getenv("NIM_SAFETY_MODEL", "nvidia/nemotron-3.5-content-safety")
        self._enabled   = self._use_nim and bool(self._api_key)

        if self._enabled:
            print(f"[SafetyGate] Enabled — model={self._model!r}")
        else:
            print("[SafetyGate] Pass-through mode (USE_NIM=false or NIM_API_KEY not set).")

        # Lazy import openai to avoid hard dependency when USE_NIM=false
        self._client: Optional[object] = None
        if self._enabled:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url,
                )
                print("[SafetyGate] OpenAI NIM client initialised.")
            except ImportError:
                print("[SafetyGate] WARNING: openai package not installed. "
                      "Run: pip install openai  — falling back to pass-through.")
                self._enabled = False
            except Exception as e:
                print(f"[SafetyGate] Client init failed: {e} — falling back to pass-through.")
                self._enabled = False

    # ── Public API ───────────────────────────────────────────────────────────

    def is_safe(self, text: str) -> bool:
        """
        Check whether text is safe to send to the learner.

        Returns:
            True  → text is safe (or safety gate is disabled / pass-through).
            False → text was flagged as unsafe by the safety model.
        """
        if not self._enabled or not text.strip():
            return True

        try:
            response = self._client.chat.completions.create(  # type: ignore
                model=self._model,
                messages=[{"role": "user", "content": text}],
                max_tokens=5,
                temperature=0.0,
            )
            # nemotron-3.5-content-safety returns "safe" or "unsafe" in the content
            result = response.choices[0].message.content.strip().lower()
            return "safe" in result and "unsafe" not in result
        except Exception as e:
            # On any error → fail open (allow the text through rather than breaking UX)
            print(f"[SafetyGate] Check failed: {e} — allowing text through.")
            return True

    def filter(self, text: str, replacement: str = "[Content filtered]") -> str:
        """
        Filter narrator text before it is sent to Android TTS.

        Args:
            text:        The narrator text to check.
            replacement: What to send instead if flagged. Defaults to a
                         neutral message that TTS can speak without error.

        Returns:
            The original text if safe, or replacement if flagged.
        """
        if not text:
            return text
        if self.is_safe(text):
            return text
        print(f"[SafetyGate] Text flagged — replaced: {text[:60]!r}…")
        return replacement
