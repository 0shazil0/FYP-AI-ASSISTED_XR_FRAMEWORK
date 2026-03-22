from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class FrameDiffer:
    threshold: float = 15.0
    resize_width: int = 320
    _last_gray: Optional[np.ndarray] = None

    def should_process(self, bgr_image: np.ndarray) -> tuple[bool, float]:
        if bgr_image is None or bgr_image.size == 0:
            return False, 0.0

        gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        if self.resize_width > 0 and gray.shape[1] > self.resize_width:
            scale = self.resize_width / float(gray.shape[1])
            gray = cv2.resize(gray, (self.resize_width, int(gray.shape[0] * scale)))

        if self._last_gray is None:
            self._last_gray = gray
            return True, 100.0

        if self._last_gray.shape != gray.shape:
            self._last_gray = gray
            return True, 100.0

        diff = cv2.absdiff(self._last_gray, gray)
        score = float(np.mean(diff))

        should = score >= self.threshold
        if should:
            self._last_gray = gray

        return should, score
