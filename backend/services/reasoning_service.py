from __future__ import annotations

from typing import Iterable

from config import REASONING_USE_VLM_FALLBACK
from schemas import GuidancePayload, SceneState
from services.vlm_service import VlmService


class ReasoningService:
    def __init__(self, fallback_vlm: VlmService | None = None) -> None:
        self._fallback_vlm = fallback_vlm if REASONING_USE_VLM_FALLBACK else None

    async def generate_guidance(self, scene: SceneState, image_bytes: bytes | None = None) -> GuidancePayload:
        labels = [item.label.lower() for item in scene.objects]
        primary = scene.objects[0] if scene.objects else None

        if self._contains_any(labels, {"barbell", "bench", "dumbbell", "kettlebell"}):
            return GuidancePayload(
                task="gym_coach",
                instruction_text="Focus on posture first. Align shoulders, brace your core, and move with control.",
                visual_type="highlight",
                location_3d=self._location_from_primary(primary),
                objects_detected=[item.label for item in scene.objects],
                step_number=scene.task_context.step_number,
                total_steps=max(scene.task_context.total_steps, 4),
                confidence=max(0.55, scene.system_confidence),
                reasoning_source="rule_based_yolo26",
                debug={"scene_summary": scene.scene_summary},
            )

        if self._contains_any(labels, {"person"}):
            return GuidancePayload(
                task="body_alignment",
                instruction_text="Keep the subject centered and reduce camera shake for better guidance quality.",
                visual_type="highlight",
                location_3d=self._location_from_primary(primary),
                objects_detected=[item.label for item in scene.objects],
                step_number=scene.task_context.step_number,
                total_steps=scene.task_context.total_steps,
                confidence=max(0.45, scene.system_confidence),
                reasoning_source="rule_based_yolo26",
                debug={"scene_summary": scene.scene_summary},
            )

        if self._fallback_vlm is not None and image_bytes and not scene.objects:
            fallback = await self._fallback_vlm.analyze_frame(image_bytes)
            return GuidancePayload(
                **fallback,
                confidence=max(scene.system_confidence, 0.35),
                reasoning_source="vlm_fallback",
                debug={"scene_summary": scene.scene_summary},
            )

        return GuidancePayload(
            task=scene.task_context.task,
            instruction_text="No reliable target detected yet. Keep the device steady and bring the object into view.",
            visual_type="highlight",
            location_3d=[0.0, 0.0, 1.3],
            objects_detected=[item.label for item in scene.objects],
            step_number=scene.task_context.step_number,
            total_steps=scene.task_context.total_steps,
            confidence=scene.system_confidence,
            reasoning_source="rule_based_yolo26",
            debug={"scene_summary": scene.scene_summary},
        )

    def _contains_any(self, labels: Iterable[str], expected: set[str]) -> bool:
        return any(label in expected for label in labels)

    def _location_from_primary(self, primary) -> list[float]:
        if primary is None or len(primary.bbox) != 4:
            return [0.0, 0.0, 1.3]

        x1, y1, x2, y2 = primary.bbox
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0

        return [
            round((center_x - 0.5) * 0.8, 3),
            round((0.5 - center_y) * 0.6, 3),
            1.3,
        ]
