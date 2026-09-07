"""
backend/services/llm_service.py
LLM-powered natural language → UI action step converter.
Supports Ollama (local), OpenAI, and Hugging Face UI-TARS.
"""

from __future__ import annotations
import base64
import json
import re
import os
from urllib.parse import urlparse
from typing import Optional

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[LLMCopilot] WARNING: openai package not installed. Run: pip install openai")

try:
    from huggingface_hub import InferenceClient
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    print("[LLMCopilot] WARNING: huggingface_hub not installed. Run: pip install huggingface_hub")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[LLMCopilot] WARNING: requests not installed. Run: pip install requests")


COPILOT_SYSTEM_PROMPT = """You are a Windows software automation expert AND a friendly voice tutor.
Given a user task and the target application name, return a JSON object with a 'steps' array.

Each step MUST be a JSON object with ALL of these fields:
- "action":   one of "click", "double_click", "right_click", "type", "scroll"
- "target":   the EXACT visible label of the UI element (button, menu item, etc.)
- "type":     the control type — "Button", "MenuItem", "Edit", "TabItem", "ComboBox" (default: "Button")
- "value":    (only for "type" action) the text to type into the field; omit for other actions
- "tts_text": a SHORT, FRIENDLY spoken coaching sentence (max 15 words) that a tutor would say
              to guide the learner to perform this step.
              Format: "Step N. <action verb> <target name>. <optional brief hint>"
              Example: "Step 1. Click the Insert tab at the top of the ribbon."
              Example: "Step 2. Choose PivotTable from the drop-down menu."
              Example: "Step 3. Type your data range in the field and press OK."

RULES:
- Use only real, visible UI element names from the application.
- Return ONLY a valid JSON object starting with {"steps": [
- No markdown, no extra text, no explanations outside the JSON.
- If the task is unclear or impossible, return: {"steps": []}
- Start from the most logical first step (e.g., open a menu before clicking submenu items).
- tts_text MUST be present in every step — never omit it.

EXAMPLE for "Make text bold and italic in Word":
{
  "steps": [
    {"action": "click",  "target": "Bold",   "type": "Button", "tts_text": "Step 1. Click the Bold button in the Home ribbon."},
    {"action": "click",  "target": "Italic", "type": "Button", "tts_text": "Step 2. Now click Italic to apply italic formatting."}
  ]
}

EXAMPLE for "Insert a table with 3 columns in Word":
{
  "steps": [
    {"action": "click", "target": "Insert",        "type": "MenuItem", "tts_text": "Step 1. Click the Insert tab at the top."},
    {"action": "click", "target": "Table",          "type": "Button",   "tts_text": "Step 2. Click the Table button to open the menu."},
    {"action": "click", "target": "Insert Table...","type": "MenuItem", "tts_text": "Step 3. Choose Insert Table from the drop-down."}
  ]
}
"""

COPILOT_UI_TARS_SYSTEM_PROMPT = """You are UI-TARS, a UI understanding assistant and voice tutor.
Given one screenshot and a user task, produce actionable desktop UI steps.

Return ONLY JSON in this strict schema:
{"steps": [{"action": "click|double_click|right_click|type|scroll", "target": "exact label", "type": "Button|MenuItem|Edit|TabItem|ComboBox", "value": "optional text", "tts_text": "Step N. spoken coaching instruction max 15 words."}]}

Rules:
- Output only JSON, no markdown.
- Prefer exact visible labels found on the interface.
- Keep the list short and practical.
- tts_text MUST be present in every step.
- If uncertain, return {"steps": []}.
"""


class LLMCopilotService:
    """
    Converts natural language queries into ordered lists of UI actions
    that pywinauto can resolve to pixel coordinates.
    """

    def __init__(
        self,
        provider: str | None = None,
        use_ollama: bool = True,
        ollama_model: str = "llama3.2",
        ollama_base_url: str = "http://localhost:11434/v1",
        ollama_api_key: str | None = None,
        openai_model: str = "gpt-4o",
        hf_model_id: str = "ByteDance-Seed/UI-TARS-1.5",
        hf_endpoint_url: str = "",
        hf_api_token: str | None = None,
        hf_temperature: float = 0.1,
        hf_max_new_tokens: int = 1024,
    ):
        self.use_ollama = use_ollama
        self.provider = (provider or ("ollama" if use_ollama else "openai")).strip().lower()
        self.ollama_api_key = ollama_api_key

        self.client = None
        self.model = ""
        self.ollama_native_base_url = ""

        self.hf_client = None
        self.hf_model_id = hf_model_id
        self.hf_endpoint_url = hf_endpoint_url.strip()
        self.hf_temperature = max(0.0, min(float(hf_temperature), 1.0))
        self.hf_max_new_tokens = max(64, int(hf_max_new_tokens))

        if self.provider in {"ollama", "openai"}:
            self._init_openai_like(ollama_base_url, ollama_model, openai_model, ollama_api_key)
        elif self.provider == "ui_tars":
            self._init_ui_tars(hf_api_token)
        else:
            print(f"[LLMCopilot] Unknown provider '{self.provider}' — defaulting to ollama mode.")
            self.provider = "ollama"
            self._init_openai_like(ollama_base_url, ollama_model, openai_model, ollama_api_key)

    def parse_query(
        self,
        user_query: str,
        app_context: str = "Microsoft Word",
        available_controls: str = "",
        max_steps: int = 8,
        screenshot_bytes: Optional[bytes] = None,
    ) -> list[dict]:
        """
        Convert a natural language user query into an ordered list of UI steps.

        Args:
            user_query: e.g. "How do I insert a pie chart?"
            app_context: e.g. "Microsoft Word", "Excel", "Notepad"
            available_controls: Grounding hint — list of real control names from pywinauto.
                                 Injected into prompt to reduce hallucination.
            max_steps: Cap the number of returned steps.

        Returns:
            List of step dicts: [{"action": "click", "target": "Bold", "type": "Button"}, ...]
        """
        if self.provider == "ui_tars":
            return self._parse_query_ui_tars(
                user_query=user_query,
                app_context=app_context,
                available_controls=available_controls,
                max_steps=max_steps,
                screenshot_bytes=screenshot_bytes,
            )

        if self.provider == "ollama":
            return self._parse_query_ollama_native(
                user_query=user_query,
                app_context=app_context,
                available_controls=available_controls,
                max_steps=max_steps,
            )

        return self._parse_query_openai_like(
            user_query=user_query,
            app_context=app_context,
            available_controls=available_controls,
            max_steps=max_steps,
        )

    def _init_openai_like(self, ollama_base_url: str, ollama_model: str, openai_model: str, ollama_api_key: str | None = None) -> None:
        if not OPENAI_AVAILABLE:
            print("[LLMCopilot] openai package missing — defaulting to empty-step mode.")
            self.client = None
            return

        if self.provider == "ollama":
            self.client = OpenAI(
                base_url=ollama_base_url,
                api_key=ollama_api_key or "ollama",
            )
            self.model = ollama_model
            self.ollama_native_base_url = self._to_ollama_native_base_url(ollama_base_url)
            print(f"[LLMCopilot] Provider=ollama model={self.model}")
        else:
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                print("[LLMCopilot] WARNING: OPENAI_API_KEY not set.")
            self.client = OpenAI(api_key=api_key)
            self.model = openai_model
            print(f"[LLMCopilot] Provider=openai model={self.model}")

    def _to_ollama_native_base_url(self, base_url: str) -> str:
        """Convert OpenAI-compatible Ollama URL to native Ollama URL root."""
        url = (base_url or "http://127.0.0.1:11434/v1").strip()
        if not url:
            return "http://127.0.0.1:11434"

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:11434"

        root = f"{parsed.scheme}://{parsed.netloc}"
        return root

    def _parse_query_ollama_native(
        self,
        user_query: str,
        app_context: str,
        available_controls: str,
        max_steps: int,
    ) -> list[dict]:
        """
        Use native Ollama /api/chat JSON mode to avoid empty content issues.
        Works for BOTH local Ollama (http://127.0.0.1:11434) and Ollama Cloud
        (https://ollama.com) — both expose /api/chat with the same request shape.
        Cloud calls include a Bearer token via Authorization header.
        """
        if not REQUESTS_AVAILABLE:
            print("[LLMCopilot] requests missing — falling back to OpenAI-compatible client.")
            return self._parse_query_openai_like(user_query, app_context, available_controls, max_steps)

        prompt_parts = [
            f"Application: {app_context}",
            f"User task: {user_query}",
        ]
        if available_controls:
            prompt_parts.append(
                f"Available UI controls in the app (use ONLY these names): {available_controls}"
            )
        user_prompt = "\n".join(prompt_parts)

        messages = [
            {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            data = self._ollama_chat_json(messages, max_tokens=1800)
            content = str(data.get("content") or "").strip()
            thinking = str(data.get("thinking") or "").strip()
            done_reason = str(data.get("done_reason") or "")

            print(
                "[LLMCopilot] Ollama native response: "
                f"content_len={len(content)} thinking_len={len(thinking)} done_reason={done_reason} "
                f"preview={content[:300] if content else thinking[:300]}"
            )

            steps = self._parse_response(content) if content else []

            if not steps:
                retry_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Return one compact JSON object only. "
                            "Schema: {\"steps\": [{\"action\":\"click|double_click|right_click|type|scroll\","
                            " \"target\":\"exact label\", \"type\":\"Button|MenuItem|Edit|TabItem|ComboBox\","
                            " \"value\":\"optional text\"}]}. "
                            "No explanations. No markdown."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Application: {app_context}\n"
                            f"Task: {user_query}\n"
                            "Output JSON now."
                        ),
                    },
                ]
                retry_data = self._ollama_chat_json(retry_messages, max_tokens=2200)
                retry_content = str(retry_data.get("content") or "").strip()
                retry_thinking = str(retry_data.get("thinking") or "").strip()
                retry_reason = str(retry_data.get("done_reason") or "")
                print(
                    "[LLMCopilot] Ollama native retry: "
                    f"content_len={len(retry_content)} thinking_len={len(retry_thinking)} done_reason={retry_reason} "
                    f"preview={retry_content[:300] if retry_content else retry_thinking[:300]}"
                )
                steps = self._parse_response(retry_content) if retry_content else []

            steps = steps[:max_steps]
            print(f"[LLMCopilot] Parsed {len(steps)} steps for: '{user_query}'")
            return steps
        except Exception as e:
            print(f"[LLMCopilot] Ollama native error: {e}")
            return []

    def _ollama_chat_json(self, messages: list[dict], max_tokens: int) -> dict:
        parsed = urlparse(self.ollama_native_base_url)
        _local_hosts = {"127.0.0.1", "localhost", "::1"}
        is_remote = parsed.hostname not in _local_hosts if parsed.hostname else False

        headers = {}
        if getattr(self, "ollama_api_key", None):
            headers["Authorization"] = f"Bearer {self.ollama_api_key}"

        if is_remote:
            endpoint = f"{self.ollama_native_base_url.rstrip('/')}/v1/chat/completions"
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            response = requests.post(endpoint, json=payload, headers=headers, timeout=200)
            response.raise_for_status()
            obj = response.json()
            choices = obj.get("choices", [])
            content = str(choices[0].get("message", {}).get("content", "")) if choices else ""
            return {
                "content": content,
                "thinking": "",
                "done_reason": "stop",
            }
        else:
            endpoint = f"{self.ollama_native_base_url.rstrip('/')}/api/chat"
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "think": False,
                "options": {
                    "temperature": 0,
                    "num_predict": max(256, int(max_tokens)),
                },
            }
            response = requests.post(endpoint, json=payload, headers=headers, timeout=200)
            response.raise_for_status()
            obj = response.json()
            msg = obj.get("message", {}) if isinstance(obj, dict) else {}
            return {
                "content": msg.get("content", "") if isinstance(msg, dict) else "",
                "thinking": msg.get("thinking", "") if isinstance(msg, dict) else "",
                "done_reason": obj.get("done_reason", "") if isinstance(obj, dict) else "",
            }


    def _init_ui_tars(self, hf_api_token: Optional[str]) -> None:
        if not HF_AVAILABLE:
            print("[LLMCopilot] huggingface_hub missing — cannot use ui_tars provider.")
            self.hf_client = None
            return

        token = (hf_api_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN") or "").strip()
        if not token:
            print("[LLMCopilot] WARNING: HF token missing. Set COPILOT_HF_API_TOKEN or HF_TOKEN.")

        if self.hf_endpoint_url:
            self.hf_client = InferenceClient(base_url=self.hf_endpoint_url, token=token or None)
            print(f"[LLMCopilot] Provider=ui_tars endpoint={self.hf_endpoint_url}")
        else:
            self.hf_client = InferenceClient(token=token or None)
            print(f"[LLMCopilot] Provider=ui_tars model={self.hf_model_id}")

    def _parse_query_openai_like(
        self,
        user_query: str,
        app_context: str,
        available_controls: str,
        max_steps: int,
    ) -> list[dict]:
        if self.client is None:
            print("[LLMCopilot] No client available — returning empty steps.")
            return []

        # Build the user portion of the prompt
        prompt_parts = [
            f"Application: {app_context}",
            f"User task: {user_query}",
        ]
        if available_controls:
            prompt_parts.append(
                f"Available UI controls in the app (use ONLY these names): {available_controls}"
            )

        user_prompt = "\n".join(prompt_parts)

        try:
            messages = [
                {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0 if self.provider == "ollama" else 0.1,
                max_tokens=1400 if self.provider == "ollama" else 1024,
                **self._openai_extra_kwargs(),
            )

            raw_content, raw_reasoning, finish_reason = self._extract_message_texts(response)
            raw = raw_content or raw_reasoning
            print(
                "[LLMCopilot] Raw response logic: "
                f"content_len={len(raw_content)} reasoning_len={len(raw_reasoning)} finish={finish_reason} "
                f"preview={raw[:300]}"
            )

            steps = self._parse_response(raw) if raw else []

            # Retry once with a compact no-prose instruction when output is truncated or unparsable.
            if not steps and (finish_reason == "length" or not raw_content):
                retry_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Return one compact JSON object only. "
                            "Schema: {\"steps\": [{\"action\":\"click|double_click|right_click|type|scroll\","
                            " \"target\":\"exact label\", \"type\":\"Button|MenuItem|Edit|TabItem|ComboBox\","
                            " \"value\":\"optional text\"}]}. "
                            "Do not output reasoning, markdown, or explanations."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Application: {app_context}\n"
                            f"Task: {user_query}\n"
                            "Output JSON now."
                        ),
                    },
                ]
                retry_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=retry_messages,
                    temperature=0.0,
                    max_tokens=2200 if self.provider == "ollama" else 1200,
                    **self._openai_extra_kwargs(),
                )
                retry_content, retry_reasoning, retry_finish = self._extract_message_texts(retry_response)
                retry_raw = retry_content or retry_reasoning
                print(
                    "[LLMCopilot] Retry response: "
                    f"content_len={len(retry_content)} reasoning_len={len(retry_reasoning)} finish={retry_finish} "
                    f"preview={retry_raw[:300]}"
                )
                steps = self._parse_response(retry_raw) if retry_raw else []

            # Cap steps
            steps = steps[:max_steps]
            print(f"[LLMCopilot] Parsed {len(steps)} steps for: '{user_query}'")
            return steps

        except Exception as e:
            print(f"[LLMCopilot] Error calling LLM: {e}")
            return []

    def _openai_extra_kwargs(self) -> dict:
        """Provider-specific kwargs for OpenAI-compatible clients."""
        if self.provider != "ollama":
            return {}
        # Qwen family models on Ollama frequently emit only reasoning unless explicitly constrained.
        return {
            "response_format": {"type": "json_object"},
            "extra_body": {
                "think": False,
                "options": {
                    "think": False,
                    "num_predict": 2400,
                    "temperature": 0.0,
                },
            },
        }

    def _extract_message_texts(self, response) -> tuple[str, str, str]:
        """Extract content/reasoning text safely from OpenAI-compatible responses."""
        try:
            choice = response.choices[0]
            message = choice.message
        except Exception:
            return "", "", ""

        content = self._coerce_message_text(getattr(message, "content", ""))

        reasoning = self._coerce_message_text(getattr(message, "reasoning", ""))
        if not reasoning:
            # Some providers store additional fields in model extras.
            extra = getattr(message, "model_extra", None)
            if isinstance(extra, dict):
                reasoning = self._coerce_message_text(
                    extra.get("reasoning") or extra.get("thinking") or extra.get("reasoning_content") or ""
                )

        # Strip potential think tags if provider leaks them.
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        reasoning = re.sub(r"<think>.*?</think>", "", reasoning, flags=re.DOTALL).strip()

        finish_reason = str(getattr(choice, "finish_reason", "") or "").strip().lower()
        return content, reasoning, finish_reason

    def _coerce_message_text(self, value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            chunks: list[str] = []
            for item in value:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    text_val = item.get("text") or item.get("content") or ""
                    if isinstance(text_val, str) and text_val:
                        chunks.append(text_val)
            return "\n".join(chunks)
        return ""

    def _parse_query_ui_tars(
        self,
        user_query: str,
        app_context: str,
        available_controls: str,
        max_steps: int,
        screenshot_bytes: Optional[bytes],
    ) -> list[dict]:
        if self.hf_client is None:
            print("[LLMCopilot] UI-TARS client unavailable — returning empty steps.")
            return []

        prompt_parts = [
            f"Application: {app_context}",
            f"User task: {user_query}",
            "Return concise actionable steps.",
        ]
        if available_controls:
            prompt_parts.append(f"Known controls (if useful): {available_controls}")
        user_prompt = "\n".join(prompt_parts)

        raw = ""
        if screenshot_bytes:
            try:
                b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")
                response = self.hf_client.chat.completions.create(
                    model=self.hf_model_id,
                    messages=[
                        {"role": "system", "content": COPILOT_UI_TARS_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                                },
                            ],
                        },
                    ],
                    temperature=self.hf_temperature,
                    max_tokens=self.hf_max_new_tokens,
                )
                raw = response.choices[0].message.content or ""
            except Exception as e:
                print(f"[LLMCopilot] UI-TARS vision call failed, falling back to text generation: {e}")

        if not raw:
            try:
                raw = self.hf_client.text_generation(
                    model=self.hf_model_id,
                    prompt=(
                        f"{COPILOT_UI_TARS_SYSTEM_PROMPT}\n\n"
                        f"{user_prompt}\n\n"
                        "Return JSON now:"
                    ),
                    max_new_tokens=self.hf_max_new_tokens,
                    temperature=self.hf_temperature,
                    return_full_text=False,
                )
            except Exception as e:
                print(f"[LLMCopilot] UI-TARS text call failed: {e}")
                return []

        raw = re.sub(r"<think>.*?</think>", "", str(raw), flags=re.DOTALL).strip()
        print(f"[LLMCopilot] UI-TARS raw response: {raw[:300]}")
        steps = self._parse_response(raw)
        steps = steps[:max_steps]
        print(f"[LLMCopilot] UI-TARS parsed {len(steps)} steps for: '{user_query}'")
        return steps

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> list[dict]:
        """Parse LLM output tolerantly — strips markdown, extracts JSON array."""
        raw = raw.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()

        # Try direct parse
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [s for s in parsed if isinstance(s, dict)]
            if isinstance(parsed, dict):
                # Model might wrap in {"steps": [...]}
                if "steps" in parsed and isinstance(parsed["steps"], list):
                    return [s for s in parsed["steps"] if isinstance(s, dict)]
                if "actions" in parsed and isinstance(parsed["actions"], list):
                    return [s for s in parsed["actions"] if isinstance(s, dict)]
            return []
        except json.JSONDecodeError:
            pass

        # Try to find JSON object substring
        match_obj = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match_obj:
            try:
                parsed = json.loads(match_obj.group())
                if isinstance(parsed, dict) and "steps" in parsed and isinstance(parsed["steps"], list):
                    return [s for s in parsed["steps"] if isinstance(s, dict)]
            except json.JSONDecodeError:
                pass

        # Try to find JSON array substring
        match_arr = re.search(r"\[.*\]", raw, flags=re.DOTALL)
        if match_arr:
            try:
                parsed = json.loads(match_arr.group())
                if isinstance(parsed, list):
                    return [s for s in parsed if isinstance(s, dict)]
            except json.JSONDecodeError:
                pass

        print(f"[LLMCopilot] Failed to parse response: {raw[:200]}")
        return []
