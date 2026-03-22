from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from config import (
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_EXPORT_ONNX,
    YOLO_IMAGE_SIZE,
    YOLO_MAX_DETECTIONS,
    YOLO_MODEL_NAME,
)
from schemas import DetectionObject

try:
    from ultralytics import YOLO
except Exception:  # pragma: no cover - optional dependency at runtime
    YOLO = None


class DetectionService:
    def __init__(self) -> None:
        self._enabled = YOLO is not None
        self._model = None
        self._last_error = "" if self._enabled else "ultralytics is not installed"
        self._runtime_model_path = ""

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def runtime_model_path(self) -> str:
        return self._runtime_model_path

    @property
    def last_error(self) -> str:
        return self._last_error

    async def detect(self, bgr_image: np.ndarray) -> list[DetectionObject]:
        if not self._enabled:
            return []

        return await asyncio.to_thread(self._detect_sync, bgr_image)

    def _ensure_model_loaded(self) -> None:
        if self._model is not None or not self._enabled:
            return

        try:
            runtime_model_path = YOLO_MODEL_NAME
            model_name_lower = str(YOLO_MODEL_NAME).lower()

            if YOLO_EXPORT_ONNX and model_name_lower.endswith(".pt"):
                onnx_candidate = Path(YOLO_MODEL_NAME).with_suffix(".onnx")
                if onnx_candidate.exists():
                    runtime_model_path = str(onnx_candidate)
                else:
                    source_model = YOLO(YOLO_MODEL_NAME, task="detect")
                    exported_path = source_model.export(format="onnx", imgsz=YOLO_IMAGE_SIZE)
                    runtime_model_path = str(exported_path)

            self._model = YOLO(runtime_model_path, task="detect")
            self._runtime_model_path = runtime_model_path
            self._last_error = ""
        except Exception as exception:  # pragma: no cover - runtime model dependency
            self._enabled = False
            self._last_error = str(exception)
            self._model = None

    def _detect_sync(self, bgr_image: np.ndarray) -> list[DetectionObject]:
        self._ensure_model_loaded()
        if self._model is None:
            return []

        results = self._model.predict(
            source=bgr_image,
            conf=YOLO_CONFIDENCE_THRESHOLD,
            imgsz=YOLO_IMAGE_SIZE,
            max_det=YOLO_MAX_DETECTIONS,
            verbose=False,
        )

        if not results:
            return []

        result = results[0]
        names = result.names or {}
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []

        height, width = bgr_image.shape[:2]
        detections: list[DetectionObject] = []
        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            confidence = float(box.conf[0]) if box.conf is not None else 0.0
            class_id = int(box.cls[0]) if box.cls is not None else -1
            label = str(names.get(class_id, class_id))

            x1, y1, x2, y2 = xyxy
            normalized_bbox = [
                round(max(0.0, min(1.0, x1 / width)), 4),
                round(max(0.0, min(1.0, y1 / height)), 4),
                round(max(0.0, min(1.0, x2 / width)), 4),
                round(max(0.0, min(1.0, y2 / height)), 4),
            ]
            detections.append(
                DetectionObject(
                    label=label,
                    confidence=round(confidence, 4),
                    bbox=normalized_bbox,
                    source="yolo26_onnx" if self._runtime_model_path.endswith(".onnx") else "yolo26_pt",
                )
            )

        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections
