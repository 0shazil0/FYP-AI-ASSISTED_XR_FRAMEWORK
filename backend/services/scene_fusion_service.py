from __future__ import annotations

from datetime import datetime

from schemas import DetectionObject, SceneState, TaskContext


class SceneFusionService:
    def build_scene(
        self,
        detections: list[DetectionObject],
        *,
        task_context: TaskContext | None = None,
        diff_score: float = 0.0,
        detector_enabled: bool = True,
        detector_error: str = "",
        detector_model_path: str = "",
        extra_metadata: dict[str, object] | None = None,
    ) -> SceneState:
        context = task_context or TaskContext()
        labels = [item.label for item in detections]

        if labels:
            unique_labels = sorted(dict.fromkeys(labels))
            summary = f"Detected {', '.join(unique_labels[:5])}"
            system_confidence = round(sum(item.confidence for item in detections) / len(detections), 4)
        else:
            summary = "No confident detections in the current frame"
            system_confidence = 0.0

        metadata = {
            "diff_score": round(diff_score, 2),
            "detector_enabled": detector_enabled,
            "detector_error": detector_error,
            "detector_model_path": detector_model_path,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        return SceneState(
            scene_id=f"scene_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}",
            task_context=context,
            objects=detections,
            scene_summary=summary,
            system_confidence=system_confidence,
            metadata=metadata,
        )
