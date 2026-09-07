from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

from config import IMU_FUSION_ALPHA, IMU_MAX_STALENESS_SECONDS


@dataclass
class ImuState:
    accel: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    gyro: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    attitude: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    device_orientation: str = "Unknown"
    sample_timestamp_ms: int = 0
    received_at_ms: int = 0
    motion_score: float = 0.0


class ImuFusionService:
    def __init__(self, *, alpha: float = IMU_FUSION_ALPHA) -> None:
        self._alpha = max(0.01, min(alpha, 0.95))
        self._state = ImuState()
        self._has_state = False

    def update(self, imu_payload: dict[str, Any]) -> dict[str, Any]:
        accel = self._coerce_vector(imu_payload.get("accel"), 3, fallback=[0.0, 0.0, 0.0])
        gyro = self._coerce_vector(imu_payload.get("gyro"), 3, fallback=[0.0, 0.0, 0.0])
        attitude = self._coerce_vector(imu_payload.get("attitude"), 4, fallback=[0.0, 0.0, 0.0, 1.0])
        orientation = str(imu_payload.get("device_orientation", "Unknown"))

        sample_timestamp = self._safe_int(imu_payload.get("sent_at_ms") or imu_payload.get("timestamp") or 0)
        now_ms = int(time() * 1000)

        if not self._has_state:
            self._state.accel = accel
            self._state.gyro = gyro
            self._state.attitude = attitude
            self._has_state = True
        else:
            self._state.accel = self._smooth(self._state.accel, accel)
            self._state.gyro = self._smooth(self._state.gyro, gyro)
            self._state.attitude = self._smooth(self._state.attitude, attitude)

        self._state.device_orientation = orientation
        self._state.sample_timestamp_ms = sample_timestamp if sample_timestamp > 0 else now_ms
        self._state.received_at_ms = now_ms
        self._state.motion_score = self._compute_motion_score(self._state.accel, self._state.gyro)

        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "accel": [round(v, 5) for v in self._state.accel],
            "gyro": [round(v, 5) for v in self._state.gyro],
            "attitude": [round(v, 5) for v in self._state.attitude],
            "device_orientation": self._state.device_orientation,
            "sample_timestamp_ms": self._state.sample_timestamp_ms,
            "received_at_ms": self._state.received_at_ms,
            "motion_score": round(self._state.motion_score, 5),
            "is_stale": self.is_stale(),
        }

    def is_stale(self) -> bool:
        if self._state.received_at_ms <= 0:
            return True
        age_seconds = max(0.0, (int(time() * 1000) - self._state.received_at_ms) / 1000.0)
        return age_seconds > IMU_MAX_STALENESS_SECONDS

    def motion_score(self) -> float:
        return float(self._state.motion_score)

    def _smooth(self, previous: list[float], current: list[float]) -> list[float]:
        return [
            (1.0 - self._alpha) * previous[index] + self._alpha * current[index]
            for index in range(min(len(previous), len(current)))
        ]

    def _compute_motion_score(self, accel: list[float], gyro: list[float]) -> float:
        accel_mag = (accel[0] ** 2 + accel[1] ** 2 + accel[2] ** 2) ** 0.5
        gyro_mag = (gyro[0] ** 2 + gyro[1] ** 2 + gyro[2] ** 2) ** 0.5
        gravity_adjusted_accel = abs(accel_mag - 1.0)
        return gravity_adjusted_accel + gyro_mag

    def _coerce_vector(self, value: Any, expected_len: int, *, fallback: list[float]) -> list[float]:
        if not isinstance(value, list) or len(value) < expected_len:
            return list(fallback)

        output: list[float] = []
        for index in range(expected_len):
            try:
                output.append(float(value[index]))
            except (TypeError, ValueError):
                output.append(float(fallback[index]))
        return output

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
