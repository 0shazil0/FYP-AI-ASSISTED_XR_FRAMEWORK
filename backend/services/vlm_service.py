from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_PREDICT,
    OLLAMA_TEMPERATURE,
    OLLAMA_THINK,
)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "gym_coach.txt"
DEMO_SCENE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "demo_scene.txt"
DEMO_FOLLOWUP_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "demo_followup.txt"


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

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def analyze_frame(self, image_bytes: bytes) -> dict[str, Any]:
        base64_jpg = base64.b64encode(image_bytes).decode("utf-8")

        payload = self._build_payload(prompt=self._prompt, image_b64=base64_jpg)

        try:
            data = await self._send_chat(payload)
        except Exception as exception:
            return self._fallback(f"Ollama request failed: {exception}")

        text = self._extract_text(data).strip()

        parsed = self._parse_json(text)
        if parsed is None:
            return self._fallback("Model returned non-JSON output.")

        return self._normalize(parsed)

    async def analyze_snapshot(self, image_bytes: bytes) -> dict[str, Any]:
        try:
            print(f"[DEBUG] analyze_snapshot: received {len(image_bytes)} bytes of image data")
            
            base64_jpg = base64.b64encode(image_bytes).decode("utf-8")
            print(f"[DEBUG] analyze_snapshot: encoded to {len(base64_jpg)} chars of base64")
            
            # Check if base64 looks valid
            if len(base64_jpg) < 100:
                print(f"[DEBUG] analyze_snapshot: WARNING - base64 is suspiciously short! {base64_jpg[:100]}")
            
            snapshot_prompt = self._snapshot_prompt()
            payload = self._build_payload(
                prompt=snapshot_prompt,
                image_b64=base64_jpg,
            )
            print(f"[DEBUG] analyze_snapshot: sending to Ollama with prompt length={len(snapshot_prompt)}")
            
            data = await self._send_chat(payload)
            print(f"[DEBUG] analyze_snapshot: Ollama responded with data={str(data)[:200]}")
            message = data.get("message", {}) if isinstance(data, dict) else {}
            content_len = len(str(message.get("content", ""))) if isinstance(message, dict) else 0
            thinking_len = len(str(message.get("thinking", ""))) if isinstance(message, dict) else 0
            print(
                "[DEBUG] analyze_snapshot: "
                f"done_reason={data.get('done_reason', '')} "
                f"content_len={content_len} "
                f"thinking_len={thinking_len}"
            )
            if self._is_truncated_without_content(data):
                return self._snapshot_fallback(
                    "Vision model response was truncated before final JSON."
                )
            
        except Exception as exception:
            print(f"[DEBUG] analyze_snapshot: exception - {exception}")
            return self._snapshot_fallback(f"Ollama request failed: {exception}")

        parsed = self._parse_json(self._extract_text(data).strip())
        if parsed is None:
            parsed = self._parse_json(self._extract_thinking(data).strip())
        if parsed is None:
            return self._snapshot_fallback("Model returned non-JSON output.")

        return self._normalize_snapshot(parsed)

    async def answer_followup(
        self,
        image_bytes: bytes,
        *,
        scene_summary: str,
        objects_detected: list[str],
        user_prompt: str,
    ) -> dict[str, Any]:
        context = {
            "scene_summary": scene_summary,
            "objects_detected": objects_detected,
            "user_prompt": user_prompt,
        }

        try:
            base64_jpg = base64.b64encode(image_bytes).decode("utf-8")
            data = await self._send_chat(
                self._build_payload(
                    prompt=f"{self._demo_followup_prompt}\n\nContext JSON:\n{json.dumps(context, ensure_ascii=False)}",
                    image_b64=base64_jpg,
                )
            )
            if self._is_truncated_without_content(data):
                return self._followup_fallback(
                    user_prompt,
                    "Vision model response was truncated before final JSON.",
                )
        except Exception as exception:
            return self._followup_fallback(user_prompt, f"Ollama request failed: {exception}")

        parsed = self._parse_json(self._extract_text(data).strip())
        if parsed is None:
            parsed = self._parse_json(self._extract_thinking(data).strip())
        if parsed is None:
            return self._followup_fallback(user_prompt, "Model returned non-JSON output.")

        return self._normalize_followup(parsed, fallback_prompt=user_prompt)

    def _build_payload(
        self,
        *,
        prompt: str,
        image_b64: str,
        num_predict_override: int | None = None,
    ) -> dict[str, Any]:
        return {
            "model": OLLAMA_MODEL,
            "stream": False,
            "think": bool(OLLAMA_THINK),
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
                "think": bool(OLLAMA_THINK),
                "reasoning_effort": "low",
            },
        }

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

    def _snapshot_prompt(self) -> str:
        return (
            "Respond immediately with final JSON. Do not output <think>.\n"
            f"{self._demo_scene_prompt}"
        )

    async def _send_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=45) as client:
            await self._ensure_model_supports_vision(client)
            response = await client.post(self._chat_url, json=payload)
            response.raise_for_status()
            return response.json()

    async def _ensure_model_supports_vision(self, client: httpx.AsyncClient) -> None:
        if self._vision_check_done:
            if not self._supports_vision:
                raise RuntimeError(
                    f"Ollama model '{OLLAMA_MODEL}' does not support vision input. "
                    "Set OLLAMA_MODEL to a vision model, for example 'qwen3-vl:4b'."
                )
            return

        response = await client.post(self._show_url, json={"name": OLLAMA_MODEL})
        response.raise_for_status()
        data = response.json()

        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list):
            capabilities = []

        lowered = {str(item).strip().lower() for item in capabilities}
        self._supports_vision = "vision" in lowered or "image" in lowered
        self._vision_check_done = True

        if not self._supports_vision:
            raise RuntimeError(
                f"Ollama model '{OLLAMA_MODEL}' does not support vision input. "
                "Set OLLAMA_MODEL to a vision model, for example 'qwen3-vl:4b'."
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

    def _parse_json(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None

        candidate = text
        if "```" in candidate:
            candidate = candidate.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                return None

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
        user_message = str(payload.get("user_message", "Scene has been analyzed. What do you want to do?"))
        suggested_queries = payload.get("suggested_queries", [])
        if not isinstance(suggested_queries, list):
            suggested_queries = []

        step_guidance = self._build_step_guidance(
            context_text=scene_summary,
            objects=normalized.get("objects_detected", []),
            instruction=str(normalized.get("instruction_text", "")),
            location_3d=normalized.get("location_3d", [0.0, 0.0, 1.3]),
        )

        return {
            **normalized,
            "scene_summary": scene_summary,
            "user_message": user_message,
            "suggested_queries": [str(item) for item in suggested_queries[:4]],
            "step_guidance": step_guidance,
        }

    def _normalize_followup(self, payload: dict[str, Any], *, fallback_prompt: str) -> dict[str, Any]:
        normalized = self._normalize(payload)
        response_text = str(payload.get("response_text", payload.get("instruction_text", f"Response ready for: {fallback_prompt}")))
        step_guidance = self._build_step_guidance(
            context_text=response_text,
            objects=normalized.get("objects_detected", []),
            instruction=str(normalized.get("instruction_text", "")),
            location_3d=normalized.get("location_3d", [0.0, 0.0, 1.3]),
        )
        return {
            **normalized,
            "response_text": response_text,
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
        object_set = {item.lower() for item in normalized_objects}

        if {"tomato", "knife", "cutting board"}.intersection(object_set):
            recipe_title = "Quick Tomato Prep"
            steps = [
                {
                    "step_id": "s1",
                    "title": "Gather items",
                    "instruction": "Place tomato and knife on the cutting board.",
                    "target_object": "cutting board",
                    "visual_hint": "highlight",
                    "confidence": 0.78,
                    "estimated_seconds": 20,
                },
                {
                    "step_id": "s2",
                    "title": "Chop tomato",
                    "instruction": "Cut tomato into small cubes using steady strokes.",
                    "target_object": "tomato",
                    "visual_hint": "arrow",
                    "confidence": 0.74,
                    "estimated_seconds": 45,
                },
                {
                    "step_id": "s3",
                    "title": "Collect pieces",
                    "instruction": "Move chopped pieces into a bowl.",
                    "target_object": "bowl",
                    "visual_hint": "highlight",
                    "confidence": 0.7,
                    "estimated_seconds": 20,
                },
            ]
        elif {"keyboard", "monitor", "laptop"}.intersection(object_set):
            recipe_title = "Keyboard Guidance"
            steps = [
                {
                    "step_id": "s1",
                    "title": "Center keyboard",
                    "instruction": "Hold the keyboard in clear view for precise key highlighting.",
                    "target_object": "keyboard",
                    "visual_hint": "highlight",
                    "confidence": 0.8,
                    "estimated_seconds": 15,
                },
                {
                    "step_id": "s2",
                    "title": "Locate target key",
                    "instruction": "Use the highlighted region for the requested key position.",
                    "target_object": "keyboard",
                    "visual_hint": "arrow",
                    "confidence": 0.72,
                    "estimated_seconds": 20,
                },
            ]
        else:
            recipe_title = "Scene Guidance"
            primary_target = normalized_objects[0] if normalized_objects else "scene"
            steps = [
                {
                    "step_id": "s1",
                    "title": "Stabilize view",
                    "instruction": "Keep the camera steady and center the main target.",
                    "target_object": primary_target,
                    "visual_hint": "highlight",
                    "confidence": 0.65,
                    "estimated_seconds": 15,
                },
                {
                    "step_id": "s2",
                    "title": "Follow instruction",
                    "instruction": instruction or "Follow the on-screen instruction card.",
                    "target_object": primary_target,
                    "visual_hint": "arrow",
                    "confidence": 0.62,
                    "estimated_seconds": 25,
                },
            ]

        active_step = steps[0]
        return {
            "type": "step_guidance",
            "recipe_title": recipe_title,
            "current_step": 1,
            "total_steps": len(steps),
            "steps": steps,
            "active_hint": {
                "visual_type": active_step.get("visual_hint", "highlight"),
                "target_object": active_step.get("target_object", "scene"),
                "location_3d": location_3d if isinstance(location_3d, list) and len(location_3d) == 3 else [0.0, 0.0, 1.3],
                "context_text": context_text[:200],
            },
        }
