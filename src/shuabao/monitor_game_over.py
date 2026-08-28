# NOT_WIRED: 未接入主循环，仅作活动/静止辅助证据参考，不得自行点击

"""Frame-activity signal used as one input to game-over classification.

This module never declares a game over.  Callers must combine the stillness
candidate with victory, failure, or post-game page anchors.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class ActivityObservation:
    valid: bool
    changed_pixels: int | None = None
    is_still: bool | None = None
    still_for: float = 0.0
    stillness_candidate: bool = False


class GameActivityMonitor:
    """Track motion in consecutive, already-cropped game-window ROIs."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._previous: np.ndarray | None = None
        self._last_timestamp: float | None = None
        self._still_since: float | None = None

    def update(self, roi: np.ndarray | None, timestamp: float) -> ActivityObservation:
        try:
            now = float(timestamp)
        except (TypeError, ValueError):
            self.reset()
            return ActivityObservation(valid=False)

        if not math.isfinite(now):
            self.reset()
            return ActivityObservation(valid=False)

        current = self._prepare(roi)
        if current is None:
            self.reset()
            return ActivityObservation(valid=False)

        if self._last_timestamp is not None and now < self._last_timestamp:
            self.reset()

        if self._previous is None or self._previous.shape != current.shape:
            self._previous = current
            self._last_timestamp = now
            self._still_since = None
            return ActivityObservation(valid=True)

        difference = cv2.absdiff(self._previous, current)
        _, changed = cv2.threshold(difference, 15, 255, cv2.THRESH_BINARY)
        changed_pixels = int(cv2.countNonZero(changed))
        is_still = changed_pixels <= 500

        if is_still:
            if self._still_since is None:
                self._still_since = now
            still_for = max(0.0, now - self._still_since)
        else:
            self._still_since = None
            still_for = 0.0

        self._previous = current
        self._last_timestamp = now
        return ActivityObservation(
            valid=True,
            changed_pixels=changed_pixels,
            is_still=is_still,
            still_for=still_for,
            stillness_candidate=is_still and still_for >= 2.0,
        )

    @staticmethod
    def _prepare(roi: np.ndarray | None) -> np.ndarray | None:
        if not isinstance(roi, np.ndarray) or roi.dtype != np.uint8 or roi.size == 0:
            return None

        try:
            if roi.ndim == 2:
                gray = roi
            elif roi.ndim == 3 and roi.shape[2] == 3:
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            elif roi.ndim == 3 and roi.shape[2] == 4:
                gray = cv2.cvtColor(roi, cv2.COLOR_BGRA2GRAY)
            else:
                return None
            return cv2.GaussianBlur(gray, (5, 5), 0)
        except cv2.error:
            return None
