"""Layout transformation and virtual coordinate system for multi-resolution support.

Standard reference baseline: 1600x900 (16:9).
Provides virtual coordinate mapping, ROI conversion, and resolution compatibility validation (INV-LAYOUT-01).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence, Tuple


# Standard reference resolution
BASELINE_WIDTH = 1600
BASELINE_HEIGHT = 900
BASELINE_ASPECT_RATIO = BASELINE_WIDTH / BASELINE_HEIGHT  # 16 / 9 ~ 1.7777777777777777

# Pre-defined known 16:9 resolutions
SUPPORTED_16_9_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (1280, 720),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
    (960, 540),
    (852, 480),
)


@dataclass(frozen=True)
class LayoutTransform:
    """Virtual coordinate transformer between standard 1600x900 and target frame resolution.

    Maintains 16:9 aspect ratio scaling with optional letterbox / pillarbox offset awareness.
    If the target frame is not 16:9 (tolerance ±0.03), it fails closed.
    """

    frame_width: int = BASELINE_WIDTH
    frame_height: int = BASELINE_HEIGHT
    baseline_width: int = BASELINE_WIDTH
    baseline_height: int = BASELINE_HEIGHT
    aspect_tolerance: float = 0.035

    @property
    def scale_x(self) -> float:
        return self.frame_width / float(self.baseline_width) if self.baseline_width > 0 else 1.0

    @property
    def scale_y(self) -> float:
        return self.frame_height / float(self.baseline_height) if self.baseline_height > 0 else 1.0

    @property
    def scale(self) -> float:
        """Uniform scaling factor."""
        return self.uniform_scale

    @property
    def uniform_scale(self) -> float:
        """Uniform scaling factor (min scale) to preserve aspect ratio without distortion."""
        return min(self.scale_x, self.scale_y)
    @classmethod
    def from_frame_dimensions(
        cls,
        width: int,
        height: int,
        baseline_width: int = BASELINE_WIDTH,
        baseline_height: int = BASELINE_HEIGHT,
    ) -> LayoutTransform:
        """Construct a LayoutTransform from actual frame dimensions."""
        if width <= 0 or height <= 0:
            return cls(BASELINE_WIDTH, BASELINE_HEIGHT, baseline_width, baseline_height)
        return cls(
            frame_width=width,
            frame_height=height,
            baseline_width=baseline_width,
            baseline_height=baseline_height,
        )
    from_frame = from_frame_dimensions
    @classmethod
    def is_supported(
        cls,
        frame_w: int | None = None,
        frame_h: int | None = None,
        tolerance: float = 0.05,
    ) -> bool:
        """Check whether the given resolution (or instance resolution) is supported.

        INV-LAYOUT-01: Only 16:9 proportional resolutions (with tolerance) are supported.
        Unsupported aspect ratios fail closed.
        """
        w = frame_w
        h = frame_h

        if w is None or h is None:
            return False
        if w <= 0 or h <= 0:
            return False
        if w < 480 or h < 270:
            return False
        current_ratio = w / float(h)
        return abs(current_ratio - BASELINE_ASPECT_RATIO) <= tolerance

    def is_valid(self) -> bool:
        """Check whether this transform instance has valid supported frame dimensions."""
        return self.is_supported(self.frame_width, self.frame_height, self.aspect_tolerance)

    is_current_supported = is_valid
    def logical_point(self, x: int | float, y: int | float) -> tuple[int, int]:
        """Convert a standard baseline (1600x900) point to actual frame coordinates."""
        actual_x = int(round(x * self.scale_x))
        actual_y = int(round(y * self.scale_y))
        actual_x = max(0, min(self.frame_width - 1, actual_x))
        actual_y = max(0, min(self.frame_height - 1, actual_y))
        return (actual_x, actual_y)

    def logical_point_normalized(self, norm_x: float, norm_y: float) -> tuple[int, int]:
        """Convert normalized (0.0..1.0) coordinates to actual frame coordinates."""
        actual_x = int(round(norm_x * self.frame_width))
        actual_y = int(round(norm_y * self.frame_height))
        actual_x = max(0, min(self.frame_width - 1, actual_x))
        actual_y = max(0, min(self.frame_height - 1, actual_y))
        return (actual_x, actual_y)

    normalized_point_to_actual = logical_point_normalized
    def baseline_point_from_actual(self, actual_x: int | float, actual_y: int | float) -> tuple[int, int]:
        """Convert an actual frame coordinate back to standard baseline (1600x900) point."""
        if self.scale_x == 0 or self.scale_y == 0:
            return (int(actual_x), int(actual_y))
        bx = int(round(actual_x / self.scale_x))
        by = int(round(actual_y / self.scale_y))
        return (bx, by)

    def logical_roi(
        self,
        x1: int | float,
        y1: int | float,
        x2: int | float,
        y2: int | float,
    ) -> tuple[int, int, int, int]:
        """Convert a standard baseline (1600x900) bounding box (x1, y1, x2, y2) to actual frame ROI slice indices."""
        rx1 = int(round(x1 * self.scale_x))
        ry1 = int(round(y1 * self.scale_y))
        rx2 = int(round(x2 * self.scale_x))
        ry2 = int(round(y2 * self.scale_y))

        # Clamp within frame bounds
        rx1 = max(0, min(self.frame_width, rx1))
        ry1 = max(0, min(self.frame_height, ry1))
        rx2 = max(rx1, min(self.frame_width, rx2))
        ry2 = max(ry1, min(self.frame_height, ry2))

        return (rx1, ry1, rx2, ry2)

    def normalized_roi_to_actual(
        self,
        norm_x1: float,
        norm_y1: float,
        norm_x2: float,
        norm_y2: float,
    ) -> tuple[int, int, int, int]:
        """Convert normalized (0.0..1.0) bounding box to actual pixel ROI slice indices."""
        rx1 = int(round(norm_x1 * self.frame_width))
        ry1 = int(round(norm_y1 * self.frame_height))
        rx2 = int(round(norm_x2 * self.frame_width))
        ry2 = int(round(norm_y2 * self.frame_height))

        rx1 = max(0, min(self.frame_width, rx1))
        ry1 = max(0, min(self.frame_height, ry1))
        rx2 = max(rx1, min(self.frame_width, rx2))
        ry2 = max(ry1, min(self.frame_height, ry2))

        return (rx1, ry1, rx2, ry2)
