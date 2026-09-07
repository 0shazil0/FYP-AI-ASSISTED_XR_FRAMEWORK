"""
Roboflow-hosted inference service for custom gym machine detection.

Custom model classes:
    0 - Flat Bench Press Machine
    1 - Incline Bench Press Machine
    2 - Lat Pulldown Machine
    3 - Leg Press Machine

Configure via environment variables:
    ROBOFLOW_API_KEY       — your Roboflow API key
    ROBOFLOW_PROJECT       — project slug (e.g. "gym-machines")
    ROBOFLOW_VERSION       — model version number (e.g. "1")
    ROBOFLOW_CONFIDENCE    — minimum confidence 0-100 (default 40)
    ROBOFLOW_OVERLAP       — NMS overlap threshold 0-100 (default 30)
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
from pathlib import Path
from typing import Any

# Class labels for the custom Roboflow gym machine model
ROBOFLOW_GYM_CLASSES: list[str] = [
    "Flat Bench Press Machine",
    "Incline Bench Press Machine",
    "Lat Pulldown Machine",
    "Leg Press Machine",
]

# Normalized machine name → friendly display name
MACHINE_DISPLAY_NAMES: dict[str, str] = {
    "flat bench press machine": "Flat Bench Press",
    "incline bench press machine": "Incline Bench Press",
    "lat pulldown machine": "Lat Pulldown",
    "leg press machine": "Leg Press",
}


class RoboflowDetectionService:
    """
    Calls the Roboflow Hosted Inference API to detect gym machines.

    Falls back gracefully when API key / project is not configured.
    """

    def __init__(self) -> None:
        self._api_key: str = os.getenv("ROBOFLOW_API_KEY", "").strip()
        self._project: str = os.getenv("ROBOFLOW_PROJECT", "").strip()
        self._version: str = os.getenv("ROBOFLOW_VERSION", "1").strip()
        self._confidence: int = int(os.getenv("ROBOFLOW_CONFIDENCE", "40"))
        self._overlap: int = int(os.getenv("ROBOFLOW_OVERLAP", "30"))
        self._enabled: bool = bool(self._api_key and self._project)
        self._last_error: str = "" if self._enabled else "ROBOFLOW_API_KEY or ROBOFLOW_PROJECT not set"
        self._client: Any = None

        if self._enabled:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from roboflow import Roboflow  # type: ignore[import]
            rf = Roboflow(api_key=self._api_key)
            project = rf.workspace().project(self._project)
            self._client = project.version(int(self._version)).model
            print(
                f"[RoboflowDetection] Loaded: project='{self._project}' "
                f"v{self._version} conf={self._confidence}"
            )
        except ImportError:
            self._enabled = False
            self._last_error = "roboflow package not installed — run: pip install roboflow"
            print(f"[RoboflowDetection] {self._last_error}")
        except Exception as exc:
            self._enabled = False
            self._last_error = str(exc)
            print(f"[RoboflowDetection] Init failed: {exc}")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def classes(self) -> list[str]:
        return ROBOFLOW_GYM_CLASSES

    def get_display_name(self, raw_label: str) -> str:
        """Return short friendly name for popup display."""
        return MACHINE_DISPLAY_NAMES.get(raw_label.strip().lower(), raw_label)

    async def detect(self, image_bytes: bytes) -> list[dict]:
        """
        Run async Roboflow inference on image bytes.

        Returns list of dicts:
            {
                "label": str,            # exact class name
                "display_name": str,     # friendly short name
                "confidence": float,     # 0.0 - 1.0
                "bbox_norm": [x1,y1,x2,y2],  # normalized 0-1
                "cx_norm": float,        # normalized center-x
                "cy_norm": float,        # normalized center-y
                "source": "roboflow",
            }
        """
        if not self._enabled or self._client is None:
            return []

        return await asyncio.to_thread(self._detect_sync, image_bytes)

    def _detect_sync(self, image_bytes: bytes) -> list[dict]:
        try:
            # Save bytes to a temp in-memory path Roboflow can read
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            result = self._client.predict(
                tmp_path,
                confidence=self._confidence,
                overlap=self._overlap,
            ).json()

            Path(tmp_path).unlink(missing_ok=True)

            detections: list[dict] = []
            image_w = result.get("image", {}).get("width", 1) or 1
            image_h = result.get("image", {}).get("height", 1) or 1

            for pred in result.get("predictions", []):
                label = str(pred.get("class", ""))
                conf = float(pred.get("confidence", 0.0))
                # Roboflow returns center x,y and width/height
                cx_px = float(pred.get("x", 0))
                cy_px = float(pred.get("y", 0))
                w_px = float(pred.get("width", 0))
                h_px = float(pred.get("height", 0))

                x1 = max(0.0, (cx_px - w_px / 2) / image_w)
                y1 = max(0.0, (cy_px - h_px / 2) / image_h)
                x2 = min(1.0, (cx_px + w_px / 2) / image_w)
                y2 = min(1.0, (cy_px + h_px / 2) / image_h)
                cx_norm = cx_px / image_w
                cy_norm = cy_px / image_h

                detections.append({
                    "label": label,
                    "display_name": self.get_display_name(label),
                    "confidence": round(conf, 4),
                    "bbox_norm": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    "cx_norm": round(cx_norm, 4),
                    "cy_norm": round(cy_norm, 4),
                    "source": "roboflow",
                })

            detections.sort(key=lambda d: d["confidence"], reverse=True)
            return detections

        except Exception as exc:
            self._last_error = str(exc)
            print(f"[RoboflowDetection] Inference error: {exc}")
            return []
