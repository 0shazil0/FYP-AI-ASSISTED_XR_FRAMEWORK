"""
backend/services/guidance_composer.py
=======================================
Generates spoken coaching sentences (tts_text) for each lesson step at
DEMO INGEST TIME -- never called at learner runtime.

ROLE IN ARCHITECTURE:
  Training path only:
    DemoIngestor._generate_tts()
          |
          v
    GuidanceComposer.compose()
          |
          v
    Ollama /api/chat  ->  "Step 2. Click the Shapes button in the Insert ribbon."
          |
          v
    Stored in lesson_steps.tts_text

DESIGN:
  - Falls back to a deterministic template string when Ollama is unavailable,
    so ingestion never hard-fails just because the LLM is down.
  - Temperature=0 for deterministic output.
  - max_tokens=60 -- tts_text must be short (<= 15 words).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Optional

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False


_SYSTEM_PROMPT = (
    "You are a friendly software training voice coach. "
    "Given a UI action, produce a single spoken coaching sentence (<=15 words) "
    "that a tutor would say to a learner. "
    "Format: 'Step N. <action verb> <target name>. <optional brief hint>.'\n"
    "Examples:\n"
    "  Step 1. Click the Insert tab at the top of the ribbon.\n"
    "  Step 2. Click the Shapes button to open the gallery.\n"
    "  Step 3. Choose the Rectangle shape from the list.\n"
    "Return ONLY the coaching sentence -- no JSON, no markdown, no quotes."
)


class GuidanceComposer:
    """
    Wraps the Ollama /api/chat endpoint to produce natural-language step narrations.

    Args:
        ollama_base_url: Root URL of the Ollama server, e.g. ``http://127.0.0.1:11434``.
        model:           Ollama model name, e.g. ``llama3.2`` or ``qwen3:4b``.
        api_key:         Optional Bearer token (for Ollama Cloud).
    """

    def __init__(
        self,
        ollama_base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        raw_url = (
            ollama_base_url
            or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        ).strip()

        # Normalise to root (strip /v1 suffix from OpenAI-compat URLs)
        parsed = urlparse(raw_url)
        if parsed.scheme and parsed.netloc:
            self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        else:
            self._base_url = "http://127.0.0.1:11434"

        # Detect whether this is a non-local (cloud/remote) Ollama instance.
        # Remote instances expose OpenAI-compat /v1/chat/completions, not /api/chat.
        _local_hosts = {"127.0.0.1", "localhost", "::1"}
        self._is_remote = parsed.hostname not in _local_hosts if parsed.hostname else False

        self._model   = (model or os.getenv("COPILOT_OLLAMA_MODEL", "llama3.2")).strip()
        self._api_key = api_key or os.getenv("OLLAMA_API_KEY", "")

        mode = "remote/OpenAI-compat" if self._is_remote else "local/native"
        print(
            f"[GuidanceComposer] Ollama url={self._base_url}  "
            f"model={self._model}  mode={mode}  key={'set' if self._api_key else 'none'}"
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def compose(
        self,
        action: str,
        label: str,
        step_num: int,
        context: str = "",
    ) -> str:
        """
        Generate a spoken coaching sentence for one lesson step.

        Args:
            action:    Action type -- "click", "type", "scroll", etc.
            label:     UI element label -- "Shapes", "Insert tab", "Bold button", etc.
            step_num:  1-based step number (used in the "Step N." prefix).
            context:   Optional extra context, e.g. the app name.

        Returns:
            A short coaching sentence, e.g.
            ``"Step 2. Click the Shapes button in the ribbon."``
            Falls back to a template string if Ollama is unavailable.
        """
        if not _REQUESTS_OK:
            return self._fallback(action, label, step_num)

        user_msg = (
            f"Step number: {step_num}\n"
            f"Action: {action}\n"
            f"UI element: {label}\n"
        )
        if context:
            user_msg += f"Application: {context}\n"
        user_msg += "Write the coaching sentence now."

        try:
            content = self._call_ollama(user_msg)
            if content:
                # Strip surrounding quotes if model added them
                content = content.strip().strip('"').strip("'")
                return content
        except Exception as exc:
            print(f"[GuidanceComposer] Ollama call failed: {exc}")

        return self._fallback(action, label, step_num)

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _call_ollama(self, user_message: str) -> str:
        headers: dict = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        if self._is_remote:
            # OpenAI-compat path (/v1/chat/completions)
            endpoint = f"{self._base_url}/v1/chat/completions"
            payload = {
                "model":       self._model,
                "stream":      False,
                "max_tokens":  60,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
            }
            resp = _requests.post(endpoint, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            obj = resp.json()
            choices = obj.get("choices", [])
            if choices:
                return str(choices[0].get("message", {}).get("content", "")).strip()
            return ""
        else:
            # Native Ollama path (/api/chat)
            endpoint = f"{self._base_url}/api/chat"
            payload = {
                "model":  self._model,
                "stream": False,
                "think":  False,
                "options": {"temperature": 0, "num_predict": 60},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
            }
            resp = _requests.post(endpoint, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            obj  = resp.json()
            msg  = obj.get("message", {}) if isinstance(obj, dict) else {}
            return str(msg.get("content", "") if isinstance(msg, dict) else "").strip()

    @staticmethod
    def _fallback(action: str, label: str, step_num: int) -> str:
        """Deterministic fallback when Ollama is unavailable."""
        verb_map = {
            "click":        "Click",
            "double_click": "Double-click",
            "right_click":  "Right-click",
            "type":         "Type in",
            "scroll":       "Scroll to",
            "select":       "Select",
            "key":          "Press",
        }
        verb = verb_map.get(action.lower(), "Interact with")
        return f"Step {step_num}. {verb} {label}."
