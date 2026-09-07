from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx

from config import (
    DEFAULT_PERSONA,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_MODE,
    OLLAMA_MODEL,
    OLLAMA_NUM_PREDICT,
    OLLAMA_REQUEST_TIMEOUT_SECONDS,
    OLLAMA_TEMPERATURE,
    OLLAMA_THINK,
)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "gym_coach.txt"
DEMO_SCENE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "demo_scene.txt"
DEMO_FOLLOWUP_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "demo_followup.txt"
PERSONA_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


class VlmService:
    def __init__(self) -> None:
        self._enabled = True
        self._chat_url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        self._show_url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/show"
        self._prompt = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""
        self._demo_scene_prompt = DEMO_SCENE_PROMPT_PATH.read_text(encoding="utf-8") if DEMO_SCENE_PROMPT_PATH.exists() else ""
        self._demo_followup_prompt = DEMO_FOLLOWUP_PROMPT_PATH.read_text(encoding="utf-8") if DEMO_FOLLOWUP_PROMPT_PATH.exists() else ""
        self._vision_check_done = False
        self._supports_vision = False
        # ── Persona system ────────────────────────────────────────────────────
        self._active_persona: str = DEFAULT_PERSONA
        self._persona_prefix: str = self._load_persona_prefix(DEFAULT_PERSONA)
        # ── Session conversation history (max 8 turns) ────────────────────────
        self._conversation_history: list[dict[str, str]] = []

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def active_persona(self) -> str:
        return self._active_persona

    def clear_history(self) -> None:
        """Reset conversation history (call on new session/connection)."""
        self._conversation_history = []
        print("[VlmService] Conversation history cleared.")

    def set_persona(self, persona_id: str) -> None:
        """Switch active persona. Loads the corresponding prompt prefix file."""
        persona_id = persona_id.strip().lower()
        valid = {"gym_trainer", "chef", "physiotherapist"}
        if persona_id not in valid:
            print(f"[VlmService] Unknown persona '{persona_id}', keeping '{self._active_persona}'.")
            return
        self._active_persona = persona_id
        self._persona_prefix = self._load_persona_prefix(persona_id)
        print(f"[VlmService] Persona set to: {persona_id}")

    def _load_persona_prefix(self, persona_id: str) -> str:
        """Load persona system prefix from prompts/persona_<id>.txt"""
        path = PERSONA_PROMPT_DIR / f"persona_{persona_id}.txt"
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            print(f"[VlmService] Loaded persona prefix: {path.name} ({len(content)} chars)")
            return content
        print(f"[VlmService] Persona file not found: {path}")
        return ""

    @staticmethod
    def _format_yolo_context(yolo_detections: list[dict] | None) -> str:
        """Serialize YOLO detections as a compact context string for the model."""
        if not yolo_detections:
            return ""
        lines = ["\n--- YOLO Detections in current scene ---"]
        for det in yolo_detections[:6]:  # cap at 6 to avoid prompt bloat
            label = det.get("label", det.get("class_name", "unknown"))
            conf = det.get("confidence", 0.0)
            cx = det.get("cx_norm", det.get("x", 0.0))
            cy = det.get("cy_norm", det.get("y", 0.0))
            lines.append(f"  - {label} (conf={conf:.2f}, center=[{cx:.3f},{cy:.3f}])")
        lines.append("--- End YOLO Detections ---")
        return "\n".join(lines)

    def _record_history(self, *, role: str, content: str, coach: str) -> None:
        """Append a turn to the rolling conversation history (capped at 8 turns)."""
        if content or coach:
            self._conversation_history.append({"role": role, "content": content, "coach": coach})
        if len(self._conversation_history) > 8:
            self._conversation_history = self._conversation_history[-8:]

    def _format_history(self) -> str:
        """Serialise conversation history as a compact context block for the prompt."""
        if not self._conversation_history:
            return ""
        lines = ["--- Session history (most recent last) ---"]
        for turn in self._conversation_history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            coach = turn.get("coach", "")
            if role == "snap":
                lines.append(f"[Snap] Scene: {content}")
            else:
                lines.append(f"[User] {content}")
            if coach:
                lines.append(f"[Coach] {coach}")
        lines.append("--- End history ---\n")
        return "\n".join(lines) + "\n"

    async def analyze_frame(self, image_bytes: bytes) -> dict[str, Any]:
        base64_jpg = base64.b64encode(image_bytes).decode("utf-8")
        try:
            parsed, data = await self._request_json_with_recovery(
                prompt=self._prompt,
                image_b64=base64_jpg,
            )
        except Exception as exception:
            return self._fallback(f"Ollama request failed: {exception}")

        if parsed is None:
            if self._is_truncated_without_content(data):
                return self._fallback("Vision model response was truncated before final JSON.")
            return self._fallback("Model returned non-JSON output.")

        return self._normalize(parsed)

    async def analyze_snapshot(
        self,
        image_bytes: bytes,
        *,
        yolo_detections: list[dict] | None = None,
    ) -> dict[str, Any]:
        try:
            print(f"[DEBUG] analyze_snapshot: received {len(image_bytes)} bytes of image data")
            base64_jpg = base64.b64encode(image_bytes).decode("utf-8")
            if len(base64_jpg) < 100:
                print(f"[DEBUG] analyze_snapshot: WARNING - base64 suspiciously short: {base64_jpg[:80]}")

            snapshot_prompt = self._snapshot_prompt(yolo_detections=yolo_detections)
            print(f"[DEBUG] analyze_snapshot: prompt_len={len(snapshot_prompt)} persona={self._active_persona}")
            parsed, data = await self._request_json_with_recovery(
                prompt=snapshot_prompt,
                image_b64=base64_jpg,
            )
            message = data.get("message", {}) if isinstance(data, dict) else {}
            content_len = len(str(message.get("content", ""))) if isinstance(message, dict) else 0
            print(f"[DEBUG] analyze_snapshot: done_reason={data.get('done_reason','')} content_len={content_len}")
        except Exception as exception:
            print(f"[DEBUG] analyze_snapshot: exception - {exception}")
            return self._snapshot_fallback(f"Ollama request failed: {exception}")

        if parsed is None:
            if self._is_truncated_without_content(data):
                return self._snapshot_fallback("Vision model response was truncated before final JSON.")
            return self._snapshot_fallback("Model returned non-JSON output.")

        result = self._normalize_snapshot(parsed)
        # Record in history
        self._record_history(
            role="snap",
            content=result.get("scene_summary", ""),
            coach=result.get("response_text", result.get("instruction_text", "")),
        )
        return result

    async def answer_followup(
        self,
        image_bytes: bytes,
        *,
        scene_summary: str,
        objects_detected: list[str],
        user_prompt: str,
        yolo_detections: list[dict] | None = None,
    ) -> dict[str, Any]:
        context = {
            "scene_summary": scene_summary,
            "objects_detected": objects_detected,
            "user_prompt": user_prompt,
        }

        yolo_ctx = self._format_yolo_context(yolo_detections)
        history_ctx = self._format_history()
        persona_block = f"{self._persona_prefix}\n\n" if self._persona_prefix else ""
        followup_prompt = (
            f"{persona_block}"
            f"{history_ctx}"
            f"{self._demo_followup_prompt}{yolo_ctx}\n\n"
            f"Context JSON:\n{json.dumps(context, ensure_ascii=False)}"
        )

        try:
            base64_jpg = base64.b64encode(image_bytes).decode("utf-8")
            print(f"[DEBUG] answer_followup: persona={self._active_persona}, yolo={len(yolo_detections or [])}, history={len(self._conversation_history)}")
            parsed, data = await self._request_json_with_recovery(
                prompt=followup_prompt,
                image_b64=base64_jpg,
            )
        except Exception as exception:
            return self._followup_fallback(user_prompt, f"Ollama request failed: {exception}")

        if parsed is None:
            if self._is_truncated_without_content(data):
                return self._followup_fallback(
                    user_prompt,
                    "Vision model response was truncated before final JSON.",
                )
            return self._followup_fallback(user_prompt, "Model returned non-JSON output.")

        result = self._normalize_followup(parsed, fallback_prompt=user_prompt)
        # Record in history
        self._record_history(
            role="user",
            content=user_prompt,
            coach=result.get("response_text", result.get("instruction_text", "")),
        )
        return result

    def _build_payload(
        self,
        *,
        prompt: str,
        image_b64: str,
        num_predict_override: int | None = None,
        think_override: bool | None = None,
    ) -> dict[str, Any]:
        think_enabled = bool(OLLAMA_THINK) if think_override is None else bool(think_override)
        return {
            "model": OLLAMA_MODEL,
            "stream": False,
            "think": think_enabled,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64],
                }
            ],
            "options": {
                "temperature": OLLAMA_TEMPERATURE,
                "num_predict": int(num_predict_override or OLLAMA_NUM_PREDICT),
                "think": think_enabled,
                "reasoning_effort": "low",
            },
        }

    async def _request_json_with_recovery(self, *, prompt: str, image_b64: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        primary_payload = self._build_payload(prompt=prompt, image_b64=image_b64)
        data = await self._send_chat(primary_payload)

        parsed = self._parse_model_json(data)
        if parsed is not None:
            return parsed, data

        done_reason = str(data.get("done_reason", "")).strip().lower()
        has_content = bool(self._extract_text(data).strip())
        needs_retry = (
            done_reason in {"length", "timeout"}
            or self._is_truncated_without_content(data)
            or not has_content
        )

        if not needs_retry:
            return None, data

        retry_payload = self._build_payload(
            prompt=self._compact_json_prompt(prompt),
            image_b64=image_b64,
            num_predict_override=self._retry_num_predict(),
            think_override=False,
        )

        try:
            retry_data = await self._send_chat(retry_payload)
        except Exception:
            return None, data

        retry_parsed = self._parse_model_json(retry_data)
        if retry_parsed is not None:
            return retry_parsed, retry_data

        merged_payload = {
            "message": {
                "content": "\n\n".join(
                    part
                    for part in [
                        self._extract_text(data),
                        self._extract_thinking(data),
                        self._extract_text(retry_data),
                        self._extract_thinking(retry_data),
                    ]
                    if isinstance(part, str) and part.strip()
                )
            }
        }
        merged_parsed = self._parse_model_json(merged_payload)
        if merged_parsed is not None:
            return merged_parsed, retry_data

        return None, retry_data

    def _compact_json_prompt(self, prompt: str) -> str:
        return (
            "Return only one compact JSON object. Do not include reasoning, markdown, code fences, or prose.\n"
            "If you are unsure, still return best-effort JSON with required keys.\n\n"
            f"{prompt}"
        )

    def _retry_num_predict(self) -> int:
        return int(max(OLLAMA_NUM_PREDICT * 2, 1024))

    def _is_truncated_without_content(self, payload: dict[str, Any]) -> bool:
        if str(payload.get("done_reason", "")).strip().lower() != "length":
            return False

        message = payload.get("message", {})
        if not isinstance(message, dict):
            return False

        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            return False

        thinking = message.get("thinking", "")
        return isinstance(thinking, str) and bool(thinking.strip())

    def _snapshot_prompt(self, *, yolo_detections: list[dict] | None = None) -> str:
        persona_block = f"{self._persona_prefix}\n\n" if self._persona_prefix else ""
        yolo_ctx = self._format_yolo_context(yolo_detections)
        history_ctx = self._format_history()
        return (
            f"{persona_block}"
            f"{history_ctx}"
            "Respond immediately with final JSON. Do not output <think>.\n"
            f"{self._demo_scene_prompt}"
            f"{yolo_ctx}"
        )


    def _build_http_client(self) -> httpx.AsyncClient:
        """Build an httpx client with the correct auth header for cloud mode."""
        headers: dict[str, str] = {}
        if OLLAMA_MODE == "cloud" and OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        return httpx.AsyncClient(timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS, headers=headers)

    async def _send_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._build_http_client() as client:
            await self._ensure_model_supports_vision(client)
            response = await client.post(self._chat_url, json=payload)
            response.raise_for_status()
            return response.json()

    async def _ensure_model_supports_vision(self, client: httpx.AsyncClient) -> None:
        if self._vision_check_done:
            if not self._supports_vision:
                raise RuntimeError(
                    f"Ollama model '{OLLAMA_MODEL}' does not support vision input. "
                    "Set OLLAMA_MODEL to a vision-capable model."
                )
            return

        # ── Cloud mode: skip /api/show — not available on Ollama Cloud ────────
        if OLLAMA_MODE == "cloud":
            print(f"[VlmService] Cloud mode — skipping /api/show probe for '{OLLAMA_MODEL}'")
            self._supports_vision = True
            self._vision_check_done = True
            return

        # ── Local mode: probe /api/show to verify vision capability ───────────
        try:
            response = await client.post(self._show_url, json={"name": OLLAMA_MODEL})
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"[VlmService] /api/show probe failed ({exc}), assuming vision support.")
            self._supports_vision = True
            self._vision_check_done = True
            return

        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list):
            capabilities = []

        lowered = {str(item).strip().lower() for item in capabilities}
        self._supports_vision = "vision" in lowered or "image" in lowered or not capabilities
        self._vision_check_done = True

        if not self._supports_vision:
            raise RuntimeError(
                f"Ollama model '{OLLAMA_MODEL}' does not support vision input. "
                "Set OLLAMA_MODEL to a vision-capable model, e.g. 'qwen3-vl:4b'."
            )

    def _extract_text(self, payload: dict[str, Any]) -> str:
        message = payload.get("message", {})
        content = message.get("content", "")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
            return "\n".join(text_parts)

        return ""

    def _extract_thinking(self, payload: dict[str, Any]) -> str:
        message = payload.get("message", {})
        if not isinstance(message, dict):
            return ""

        thinking = message.get("thinking", "")
        if isinstance(thinking, str):
            return thinking

        if isinstance(thinking, list):
            text_parts = []
            for item in thinking:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
            return "\n".join(text_parts)

        return ""

    def _parse_model_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        text = self._extract_text(payload).strip()
        thinking = self._extract_thinking(payload).strip()

        candidates = []
        if text:
            candidates.append(text)
        if thinking:
            candidates.append(thinking)
        if text and thinking:
            candidates.append(f"{text}\n\n{thinking}")
            candidates.append(f"{thinking}\n\n{text}")

        best_payload = None
        best_score = -1
        best_size = -1

        for candidate in candidates:
            parsed = self._parse_json(candidate)
            if parsed is None:
                continue

            score = self._score_payload(parsed)
            size = len(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")))
            if score > best_score or (score == best_score and size > best_size):
                best_payload = parsed
                best_score = score
                best_size = size

        return best_payload

    def _parse_json(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None

        # Direct parse first for strict JSON responses.
        parsed = self._try_parse_dict(text.strip())
        if parsed is not None:
            return parsed

        candidates = [text]
        candidates.extend(self._extract_fenced_blocks(text))

        best_payload = None
        best_score = -1
        best_size = -1
        for candidate in candidates:
            direct = self._try_parse_dict(candidate.strip())
            if direct is not None:
                score = self._score_payload(direct)
                size = len(json.dumps(direct, ensure_ascii=False, separators=(",", ":")))
                if score > best_score or (score == best_score and size > best_size):
                    best_payload = direct
                    best_score = score
                    best_size = size

            for fragment in self._extract_balanced_json_fragments(candidate):
                parsed_fragment = self._try_parse_dict(fragment)
                if parsed_fragment is None:
                    continue

                score = self._score_payload(parsed_fragment)
                size = len(fragment)
                if score > best_score or (score == best_score and size > best_size):
                    best_payload = parsed_fragment
                    best_score = score
                    best_size = size

            repaired = self._repair_and_parse_truncated_json(candidate)
            if repaired is not None:
                score = self._score_payload(repaired)
                size = len(json.dumps(repaired, ensure_ascii=False, separators=(",", ":")))
                if score > best_score or (score == best_score and size > best_size):
                    best_payload = repaired
                    best_score = score
                    best_size = size

        return best_payload

    def _try_parse_dict(self, candidate: str) -> dict[str, Any] | None:
        if not candidate:
            return None

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None

        return parsed if isinstance(parsed, dict) else None

    def _extract_fenced_blocks(self, text: str) -> list[str]:
        blocks: list[str] = []
        for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE):
            block = match.group(1).strip()
            if block:
                blocks.append(block)
        return blocks

    def _extract_balanced_json_fragments(self, text: str) -> list[str]:
        fragments: list[str] = []
        stack: list[str] = []
        start = -1
        in_string = False
        escaped = False

        for index, char in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char in "{[":
                if not stack:
                    start = index
                stack.append(char)
                continue

            if char in "}]" and stack:
                opener = stack[-1]
                if (opener == "{" and char == "}") or (opener == "[" and char == "]"):
                    stack.pop()
                    if not stack and start >= 0:
                        fragment = text[start : index + 1].strip()
                        if fragment.startswith("{") and fragment.endswith("}"):
                            fragments.append(fragment)
                        start = -1
                else:
                    stack.clear()
                    start = -1

        return fragments

    def _repair_and_parse_truncated_json(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None

        start = text.find("{")
        if start < 0:
            return None

        candidate = text[start:].strip()
        if not candidate:
            return None

        repaired = self._close_open_json(candidate)
        if not repaired:
            return None

        return self._try_parse_dict(repaired)

    def _close_open_json(self, text: str) -> str:
        out: list[str] = []
        stack: list[str] = []
        in_string = False
        escaped = False

        for char in text:
            if in_string:
                out.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                out.append(char)
                in_string = True
                continue

            if char in "{[":
                stack.append(char)
                out.append(char)
                continue

            if char in "}]":
                if not stack:
                    continue

                opener = stack[-1]
                if (opener == "{" and char == "}") or (opener == "[" and char == "]"):
                    stack.pop()
                    out.append(char)
                continue

            out.append(char)

        if in_string:
            out.append('"')

        while stack:
            opener = stack.pop()
            out.append("}" if opener == "{" else "]")

        repaired = "".join(out).strip()

        # Remove dangling commas introduced by truncation.
        previous = None
        while previous != repaired:
            previous = repaired
            repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

        return repaired

    def _score_payload(self, payload: dict[str, Any]) -> int:
        key_weights = {
            "task": 3,
            "instruction_text": 3,
            "visual_type": 2,
            "location_3d": 2,
            "objects_detected": 2,
            "scene_summary": 2,
            "response_text": 2,
            "user_message": 2,
            "suggested_queries": 1,
            "step_guidance": 2,
        }
        return sum(weight for key, weight in key_weights.items() if key in payload)

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = str(payload.get("task", "general_guidance"))
        instruction_text = str(payload.get("instruction_text", "Align your posture and keep steady movement."))

        visual_type = str(payload.get("visual_type", "highlight")).lower()
        if visual_type not in {"arrow", "highlight"}:
            visual_type = "highlight"

        location = payload.get("location_3d", [0.0, 0.0, 1.3])
        if not isinstance(location, list) or len(location) != 3:
            location = [0.0, 0.0, 1.3]

        try:
            x, y, z = float(location[0]), float(location[1]), float(location[2])
        except (TypeError, ValueError):
            x, y, z = 0.0, 0.0, 1.3

        z = min(1.8, max(1.1, z))

        objects = payload.get("objects_detected", [])
        if not isinstance(objects, list):
            objects = []

        step_number = payload.get("step_number", 1)
        total_steps = payload.get("total_steps", 1)

        try:
            step_number = int(step_number)
        except (TypeError, ValueError):
            step_number = 1

        try:
            total_steps = int(total_steps)
        except (TypeError, ValueError):
            total_steps = 1

        return {
            "task": task,
            "instruction_text": instruction_text,
            "visual_type": visual_type,
            "location_3d": [x, y, z],
            "objects_detected": [str(obj) for obj in objects],
            "step_number": max(1, step_number),
            "total_steps": max(1, total_steps),
        }

    def _fallback(self, reason: str) -> dict[str, Any]:
        return {
            "task": "general_guidance",
            "instruction_text": f"{reason} Keep device steady and center the target object.",
            "visual_type": "highlight",
            "location_3d": [0.0, 0.0, 1.3],
            "objects_detected": [],
            "step_number": 1,
            "total_steps": 1,
        }

    def _normalize_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(payload)
        scene_summary = str(payload.get("scene_summary", "Scene analyzed."))
        response_text = str(payload.get("response_text", ""))
        user_message = response_text or str(payload.get("user_message", "Scene analyzed. What do you want to do?"))
        suggested_queries = payload.get("suggested_queries", [])
        if not isinstance(suggested_queries, list):
            suggested_queries = []
        coach_note = str(payload.get("coach_note", "")).strip()
        fetch_exercise = payload.get("fetch_exercise")  # dict or None
        if not isinstance(fetch_exercise, dict):
            fetch_exercise = None

        step_guidance = self._build_step_guidance(
            context_text=scene_summary,
            objects=normalized.get("objects_detected", []),
            instruction=str(normalized.get("instruction_text", "")),
            location_3d=normalized.get("location_3d", [0.0, 0.0, 1.3]),
        )

        return {
            **normalized,
            "scene_summary": scene_summary,
            "response_text": response_text,
            "user_message": user_message,
            "suggested_queries": [str(item) for item in suggested_queries[:4]],
            "coach_note": coach_note,
            "fetch_exercise": fetch_exercise,
            "step_guidance": step_guidance,
        }

    def _normalize_followup(self, payload: dict[str, Any], *, fallback_prompt: str) -> dict[str, Any]:
        normalized = self._normalize(payload)
        response_text = str(payload.get("response_text", payload.get("instruction_text", f"Response ready for: {fallback_prompt}")))
        coach_note = str(payload.get("coach_note", "")).strip()
        fetch_exercise = payload.get("fetch_exercise")
        if not isinstance(fetch_exercise, dict):
            fetch_exercise = None
        suggested_queries = payload.get("suggested_queries", [])
        if not isinstance(suggested_queries, list):
            suggested_queries = []
        step_guidance = self._build_step_guidance(
            context_text=response_text,
            objects=normalized.get("objects_detected", []),
            instruction=str(normalized.get("instruction_text", "")),
            location_3d=normalized.get("location_3d", [0.0, 0.0, 1.3]),
        )
        return {
            **normalized,
            "response_text": response_text,
            "coach_note": coach_note,
            "fetch_exercise": fetch_exercise,
            "suggested_queries": [str(item) for item in suggested_queries[:4]],
            "step_guidance": step_guidance,
        }

    def _snapshot_fallback(self, reason: str) -> dict[str, Any]:
        base = self._fallback(reason)
        step_guidance = self._build_step_guidance(
            context_text="Fallback guidance",
            objects=base.get("objects_detected", []),
            instruction=str(base.get("instruction_text", "")),
            location_3d=base.get("location_3d", [0.0, 0.0, 1.3]),
        )
        return {
            **base,
            "scene_summary": "Scene analyzed with fallback response.",
            "user_message": "Scene has been analyzed. What do you want to do?",
            "suggested_queries": [
                "From the available ingredients, suggest a quick recipe.",
                "What objects do you see in this scene?",
            ],
            "step_guidance": step_guidance,
        }

    def _followup_fallback(self, user_prompt: str, reason: str) -> dict[str, Any]:
        base = self._fallback(reason)
        response_text = f"I could not fully process '{user_prompt}'. Please try again with a shorter request."
        step_guidance = self._build_step_guidance(
            context_text=response_text,
            objects=base.get("objects_detected", []),
            instruction=str(base.get("instruction_text", "")),
            location_3d=base.get("location_3d", [0.0, 0.0, 1.3]),
        )
        return {
            **base,
            "response_text": response_text,
            "step_guidance": step_guidance,
        }

    def _build_step_guidance(
        self,
        *,
        context_text: str,
        objects: list[str],
        instruction: str,
        location_3d: list[float],
    ) -> dict[str, Any]:
        normalized_objects = [str(item).strip() for item in objects if str(item).strip()]
        recipe_title = "Scene Guidance"
        primary_target = normalized_objects[0] if normalized_objects else "scene"
        secondary_target = normalized_objects[1] if len(normalized_objects) > 1 else primary_target

        steps = [
            {
                "step_id": "s1",
                "title": "Stabilize view",
                "instruction": f"Keep the camera steady and center {primary_target}.",
                "target_object": primary_target,
                "visual_hint": "highlight",
                "confidence": 0.66,
                "estimated_seconds": 15,
            },
            {
                "step_id": "s2",
                "title": "Follow instruction",
                "instruction": instruction or "Follow the on-screen instruction card.",
                "target_object": primary_target,
                "visual_hint": "arrow",
                "confidence": 0.63,
                "estimated_seconds": 25,
            },
            {
                "step_id": "s3",
                "title": "Confirm result",
                "instruction": f"Check {secondary_target} and verify the expected outcome before continuing.",
                "target_object": secondary_target,
                "visual_hint": "highlight",
                "confidence": 0.6,
                "estimated_seconds": 18,
            },
        ]

        active_step = steps[0]
        return {
            "type": "step_guidance",
            "recipe_title": recipe_title,
            "current_step": 1,
            "total_steps": len(steps),
            "completed_steps": [],
            "is_complete": False,
            "steps": steps,
            "active_hint": {
                "visual_type": active_step.get("visual_hint", "highlight"),
                "target_object": active_step.get("target_object", "scene"),
                "location_3d": location_3d if isinstance(location_3d, list) and len(location_3d) == 3 else [0.0, 0.0, 1.3],
                "context_text": context_text[:200],
            },
        }
