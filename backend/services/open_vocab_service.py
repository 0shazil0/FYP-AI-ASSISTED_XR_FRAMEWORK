from __future__ import annotations

import asyncio
import io
from typing import Iterable

from PIL import Image

from config import (
    GROUNDING_DINO_BOX_THRESHOLD,
    GROUNDING_DINO_COOKING_LABELS,
    GROUNDING_DINO_DEFAULT_LABELS,
    GROUNDING_DINO_ENABLED,
    GROUNDING_DINO_GYM_LABELS,
    GROUNDING_DINO_MAX_DETECTIONS,
    GROUNDING_DINO_MODEL_ID,
    GROUNDING_DINO_TEXT_THRESHOLD,
)
from schemas import DetectionObject

try:
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
except Exception:  # pragma: no cover - optional runtime dependency
    torch = None
    AutoModelForZeroShotObjectDetection = None
    AutoProcessor = None


class OpenVocabularyDetectionService:
    def __init__(self) -> None:
        runtime_ready = torch is not None and AutoProcessor is not None and AutoModelForZeroShotObjectDetection is not None
        self._enabled = GROUNDING_DINO_ENABLED and runtime_ready
        self._processor = None
        self._model = None
        self._device = "cpu"
        self._last_error = ""
        if not runtime_ready:
            self._last_error = "transformers/torch runtime not available"
        elif not GROUNDING_DINO_ENABLED:
            self._last_error = "Grounding DINO disabled by config"

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def model_id(self) -> str:
        return GROUNDING_DINO_MODEL_ID

    @property
    def last_error(self) -> str:
        return self._last_error

    def get_default_labels(self, use_case: str = "gym_coach") -> list[str]:
        normalized = use_case.strip().lower()
        if normalized == "gym_coach":
            return list(GROUNDING_DINO_GYM_LABELS or GROUNDING_DINO_DEFAULT_LABELS)
        if normalized == "cooking_assistant":
            return list(GROUNDING_DINO_COOKING_LABELS or GROUNDING_DINO_DEFAULT_LABELS)
        return list(GROUNDING_DINO_DEFAULT_LABELS)

    async def detect(self, image_bytes: bytes, labels: Iterable[str] | None = None) -> list[DetectionObject]:
        if not self._enabled:
            return []
        label_list = [label.strip() for label in (labels or []) if str(label).strip()]
        return await asyncio.to_thread(self._detect_sync, image_bytes, label_list)

    def _ensure_model_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        if not self._enabled:
            return

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self._processor = AutoProcessor.from_pretrained(GROUNDING_DINO_MODEL_ID)
            self._model = AutoModelForZeroShotObjectDetection.from_pretrained(GROUNDING_DINO_MODEL_ID)
            self._model.to(self._device)
            self._model.eval()
            self._last_error = ""
        except Exception as exception:  # pragma: no cover - model download/runtime specific
            self._enabled = False
            self._processor = None
            self._model = None
            self._last_error = str(exception)

    def _detect_sync(self, image_bytes: bytes, labels: list[str]) -> list[DetectionObject]:
        self._ensure_model_loaded()
        if self._model is None or self._processor is None:
            return []

        if not labels:
            labels = list(GROUNDING_DINO_DEFAULT_LABELS)

        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            prompt = self._build_prompt(labels)
            inputs = self._processor(images=image, text=prompt, return_tensors="pt")
            if hasattr(inputs, "to"):
                inputs = inputs.to(self._device)

            with torch.no_grad():
                outputs = self._model(**inputs)

            results = self._processor.post_process_grounded_object_detection(
                outputs,
                inputs.input_ids,
                box_threshold=GROUNDING_DINO_BOX_THRESHOLD,
                text_threshold=GROUNDING_DINO_TEXT_THRESHOLD,
                target_sizes=[image.size[::-1]],
            )
        except Exception as exception:  # pragma: no cover - runtime/model specific
            self._last_error = str(exception)
            return []

        if not results:
            return []

        result = results[0]
        width, height = image.size
        detections: list[DetectionObject] = []
        for score, label, box in zip(result.get("scores", []), result.get("labels", []), result.get("boxes", [])):
            x1, y1, x2, y2 = [float(value) for value in box.tolist()]
            detections.append(
                DetectionObject(
                    label=str(label),
                    confidence=round(float(score), 4),
                    bbox=[
                        round(max(0.0, min(1.0, x1 / width)), 4),
                        round(max(0.0, min(1.0, y1 / height)), 4),
                        round(max(0.0, min(1.0, x2 / width)), 4),
                        round(max(0.0, min(1.0, y2 / height)), 4),
                    ],
                    source="grounding_dino",
                )
            )
            if len(detections) >= GROUNDING_DINO_MAX_DETECTIONS:
                break

        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections

    def _build_prompt(self, labels: list[str]) -> str:
        unique_labels = []
        seen: set[str] = set()
        for label in labels:
            normalized = label.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_labels.append(normalized)
        return ". ".join(unique_labels) + "."
