from __future__ import annotations

import base64
from time import monotonic

import cv2
import numpy as np

from config import (
    GROUNDING_DINO_MIN_TRIGGER_INTERVAL_SECONDS,
    GROUNDING_DINO_TRIGGER_CONFIDENCE,
    GROUNDING_DINO_TRIGGER_DIFF_SCORE,
    IMU_HIGH_MOTION_THRESHOLD,
)
from schemas import GuidancePayload, TaskContext
from services.detection_service import DetectionService
from services.open_vocab_service import OpenVocabularyDetectionService
from services.reasoning_service import ReasoningService
from services.scene_fusion_service import SceneFusionService
from services.vlm_service import VlmService


class PipelineService:
    def __init__(self) -> None:
        self._detection_service = DetectionService()
        self._open_vocab_service = OpenVocabularyDetectionService()
        self._scene_fusion_service = SceneFusionService()
        self._reasoning_service = ReasoningService(fallback_vlm=VlmService())
        self._last_open_vocab_trigger_at = 0.0

    @property
    def detection_service(self) -> DetectionService:
        return self._detection_service

    @property
    def open_vocab_service(self) -> OpenVocabularyDetectionService:
        return self._open_vocab_service

    async def process_frame(
        self,
        image_bytes: bytes,
        bgr_image: np.ndarray,
        *,
        diff_score: float,
        raw_payload: dict | None = None,
    ) -> GuidancePayload:
        payload = raw_payload or {}
        imu_motion_score = self._extract_imu_motion_score(payload)
        task_context = TaskContext(
            use_case=str(payload.get("use_case", "gym_coach")),
            task=str(payload.get("task", "general_guidance")),
            step_number=self._safe_int(payload.get("step_number"), default=1),
            total_steps=self._safe_int(payload.get("total_steps"), default=1),
        )

        detections = await self._detection_service.detect(bgr_image)
        open_vocab_triggered, trigger_reason = self._should_trigger_open_vocab(
            detections,
            diff_score=diff_score,
            raw_payload=payload,
            imu_motion_score=imu_motion_score,
        )
        open_vocab_labels = self._extract_open_vocab_labels(payload, use_case=task_context.use_case)
        open_vocab_detections = []
        if open_vocab_triggered:
            open_vocab_detections = await self._open_vocab_service.detect(image_bytes, labels=open_vocab_labels)

        merged_detections = self._merge_detections(detections, open_vocab_detections)
        scene = self._scene_fusion_service.build_scene(
            merged_detections,
            task_context=task_context,
            diff_score=diff_score,
            detector_enabled=self._detection_service.is_enabled,
            detector_error=self._detection_service.last_error,
            detector_model_path=self._detection_service.runtime_model_path,
            extra_metadata={
                "open_vocab_triggered": open_vocab_triggered,
                "open_vocab_reason": trigger_reason,
                "open_vocab_enabled": self._open_vocab_service.is_enabled,
                "open_vocab_model_id": self._open_vocab_service.model_id,
                "open_vocab_error": self._open_vocab_service.last_error,
                "open_vocab_detection_count": len(open_vocab_detections),
                "open_vocab_labels": open_vocab_labels,
            },
        )
        guidance = await self._reasoning_service.generate_guidance(scene, image_bytes=image_bytes)
        guidance.debug.update(
            {
                "detection_count": len(merged_detections),
                "yolo_detection_count": len(detections),
                "open_vocab_detection_count": len(open_vocab_detections),
                "imu_motion_score": round(imu_motion_score, 5),
                "scene_id": scene.scene_id,
                "detector_model_path": self._detection_service.runtime_model_path,
                "detector_error": self._detection_service.last_error,
                "open_vocab_triggered": open_vocab_triggered,
                "open_vocab_reason": trigger_reason,
                "open_vocab_enabled": self._open_vocab_service.is_enabled,
                "open_vocab_model_id": self._open_vocab_service.model_id,
                "open_vocab_error": self._open_vocab_service.last_error,
                "object_hints": [
                    {
                        "label": item.label,
                        "bbox": item.bbox,
                        "confidence": item.confidence,
                        "source": item.source,
                    }
                    for item in merged_detections
                ],
            }
        )
        return guidance

    def decode_frame(self, image_data: str) -> tuple[bytes | None, np.ndarray | None]:
        try:
            # Log the size of incoming base64 data
            data_len = len(image_data) if image_data else 0
            print(f"[DEBUG] decode_frame: received base64 string of length {data_len}")
            
            image_bytes = base64.b64decode(image_data)
            print(f"[DEBUG] decode_frame: decoded to {len(image_bytes)} bytes")
            
            np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
            bgr_image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
            
            if bgr_image is not None:
                print(f"[DEBUG] decode_frame: successfully decoded image shape={bgr_image.shape}, dtype={bgr_image.dtype}")
                # Sample a few pixel values to verify image content
                sample_pixels = bgr_image[0, 0, :]
                print(f"[DEBUG] decode_frame: sample pixel at [0,0]={sample_pixels}")
            else:
                print(f"[DEBUG] decode_frame: cv2.imdecode returned None - image data may be corrupted")
                
        except Exception as e:
            print(f"[DEBUG] decode_frame: exception during decode - {e}")
            return None, None

        if bgr_image is None:
            return None, None

        return image_bytes, bgr_image

    def _safe_int(self, value, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _extract_open_vocab_labels(self, payload: dict, *, use_case: str) -> list[str]:
        labels = payload.get("open_vocab_labels")
        if isinstance(labels, str):
            return [item.strip() for item in labels.split(",") if item.strip()]
        if isinstance(labels, list):
            return [str(item).strip() for item in labels if str(item).strip()]
        return self._open_vocab_service.get_default_labels(use_case)

    def _should_trigger_open_vocab(
        self,
        detections,
        *,
        diff_score: float,
        raw_payload: dict,
        imu_motion_score: float,
    ) -> tuple[bool, str]:
        if not self._open_vocab_service.is_enabled:
            return False, "disabled"

        if imu_motion_score >= IMU_HIGH_MOTION_THRESHOLD and not bool(raw_payload.get("force_open_vocab", False)):
            return False, "imu_high_motion_hold"

        current_time = monotonic()
        if current_time - self._last_open_vocab_trigger_at < GROUNDING_DINO_MIN_TRIGGER_INTERVAL_SECONDS:
            return False, "cooldown"

        if bool(raw_payload.get("force_open_vocab", False)):
            self._last_open_vocab_trigger_at = current_time
            return True, "forced"

        request_mode = str(raw_payload.get("request_mode", "")).strip().lower()
        if request_mode in {"explain_scene", "open_vocab"}:
            self._last_open_vocab_trigger_at = current_time
            return True, f"request_mode:{request_mode}"

        if not detections:
            self._last_open_vocab_trigger_at = current_time
            return True, "no_yolo_detections"

        highest_confidence = max(item.confidence for item in detections)
        if highest_confidence < GROUNDING_DINO_TRIGGER_CONFIDENCE:
            self._last_open_vocab_trigger_at = current_time
            return True, "low_yolo_confidence"

        if diff_score >= GROUNDING_DINO_TRIGGER_DIFF_SCORE:
            self._last_open_vocab_trigger_at = current_time
            return True, "scene_change"

        return False, "high_conf_yolo"

    def _extract_imu_motion_score(self, payload: dict) -> float:
        imu_data = payload.get("imu_data")
        if not isinstance(imu_data, dict):
            return 0.0

        try:
            explicit_score = imu_data.get("motion_score")
            if explicit_score is not None:
                return max(0.0, float(explicit_score))
        except (TypeError, ValueError):
            pass

        gyro = imu_data.get("gyro")
        accel = imu_data.get("accel")

        gyro_mag = 0.0
        accel_mag = 0.0
        try:
            if isinstance(gyro, list) and len(gyro) >= 3:
                gx, gy, gz = float(gyro[0]), float(gyro[1]), float(gyro[2])
                gyro_mag = (gx * gx + gy * gy + gz * gz) ** 0.5
            if isinstance(accel, list) and len(accel) >= 3:
                ax, ay, az = float(accel[0]), float(accel[1]), float(accel[2])
                accel_mag = abs(((ax * ax + ay * ay + az * az) ** 0.5) - 1.0)
        except (TypeError, ValueError):
            return 0.0

        return max(0.0, gyro_mag + accel_mag)

    def _merge_detections(self, base_detections, open_vocab_detections):
        merged = list(base_detections)
        for candidate in open_vocab_detections:
            if any(self._is_duplicate(existing, candidate) for existing in merged):
                continue
            merged.append(candidate)
        merged.sort(key=lambda item: item.confidence, reverse=True)
        return merged

    def _is_duplicate(self, left, right) -> bool:
        if left.label.strip().lower() != right.label.strip().lower():
            return False
        if len(left.bbox) != 4 or len(right.bbox) != 4:
            return False
        return self._bbox_iou(left.bbox, right.bbox) >= 0.5

    def _bbox_iou(self, left: list[float], right: list[float]) -> float:
        left_x1, left_y1, left_x2, left_y2 = left
        right_x1, right_y1, right_x2, right_y2 = right

        inter_x1 = max(left_x1, right_x1)
        inter_y1 = max(left_y1, right_y1)
        inter_x2 = min(left_x2, right_x2)
        inter_y2 = min(left_y2, right_y2)

        inter_width = max(0.0, inter_x2 - inter_x1)
        inter_height = max(0.0, inter_y2 - inter_y1)
        inter_area = inter_width * inter_height

        left_area = max(0.0, left_x2 - left_x1) * max(0.0, left_y2 - left_y1)
        right_area = max(0.0, right_x2 - right_x1) * max(0.0, right_y2 - right_y1)
        union = left_area + right_area - inter_area
        if union <= 0.0:
            return 0.0
        return inter_area / union
