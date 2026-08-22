from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from time import time
from typing import Any


_PROXIMITY_LEVELS = ("very_far", "far", "near", "close", "very_close")
# Empirical calibration for the current notebook + Samsung A17 pair.
# User measurements: about -58 dBm when touching the notebook, about -78 dBm at ~2 m.
# Boundaries are intentionally conservative and use hysteresis below.
_PROXIMITY_BOUNDARIES = (-82.0, -75.0, -68.0, -62.0)


@dataclass(slots=True)
class TelemetryState:
    name: str = "Unknown device"
    address: str = ""
    connected: bool = False
    paired: bool = False
    trusted: bool = False
    battery: int | None = None
    rssi: int | None = None
    rssi_median: float | None = None
    rssi_smooth: float | None = None
    rssi_trend: str = "stable"
    rssi_trend_slope: float = 0.0
    rssi_samples: int = 0
    rssi_updated_at: float = 0.0
    proximity: str = "unknown"
    rssi_recent: list[int] = field(default_factory=list)
    rssi_filtered_recent: list[float] = field(default_factory=list)
    player_status: str | None = None
    player_position_ms: int | None = None
    last_event: str = "boot"
    updated_at: float = 0.0
    _rssi_window: list[int] = field(default_factory=list, repr=False)
    _proximity_level: int | None = field(default=None, repr=False)

    def set_rssi(self, value: int) -> None:
        """Filter RSSI and update proximity/trend from a recent reading sequence.

        Pipeline:
        raw -> 5-sample median -> adaptive EMA -> least-squares trend -> hysteresis.
        """
        previous = self.rssi_smooth
        self.rssi = value

        self.rssi_recent.append(value)
        if len(self.rssi_recent) > 20:
            del self.rssi_recent[0]

        self._rssi_window.append(value)
        if len(self._rssi_window) > 5:
            del self._rssi_window[0]

        filtered = float(median(self._rssi_window))
        self.rssi_median = filtered

        if previous is None:
            smoothed = filtered
        else:
            gap = abs(filtered - previous)
            alpha = 0.50 if gap >= 8.0 else 0.26
            smoothed = alpha * filtered + (1.0 - alpha) * previous

        self.rssi_smooth = smoothed
        self.rssi_filtered_recent.append(smoothed)
        if len(self.rssi_filtered_recent) > 20:
            del self.rssi_filtered_recent[0]

        slope = self._least_squares_slope(self.rssi_filtered_recent[-8:])
        self.rssi_trend_slope = slope
        if slope >= 0.70:
            self.rssi_trend = "approaching"
        elif slope <= -0.70:
            self.rssi_trend = "moving_away"
        else:
            self.rssi_trend = "stable"

        self.rssi_samples += 1
        self.rssi_updated_at = time()
        self.proximity = self._proximity_with_hysteresis(smoothed)
        self.touch("rssi")

    @staticmethod
    def _least_squares_slope(values: list[float]) -> float:
        """OLS slope of RSSI versus sample index; positive means getting stronger."""
        n = len(values)
        if n < 3:
            return 0.0
        mean_x = (n - 1) / 2.0
        mean_y = sum(values) / n
        numerator = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values))
        denominator = sum((i - mean_x) ** 2 for i in range(n))
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _base_proximity_level(rssi: float) -> int:
        if rssi >= -62:
            return 4
        if rssi >= -68:
            return 3
        if rssi >= -75:
            return 2
        if rssi >= -82:
            return 1
        return 0

    def _proximity_with_hysteresis(self, rssi: float, margin: float = 2.5) -> str:
        if self._proximity_level is None:
            self._proximity_level = self._base_proximity_level(rssi)
            return _PROXIMITY_LEVELS[self._proximity_level]

        level = self._proximity_level
        while level < 4 and rssi >= _PROXIMITY_BOUNDARIES[level] + margin:
            level += 1
        while level > 0 and rssi < _PROXIMITY_BOUNDARIES[level - 1] - margin:
            level -= 1

        self._proximity_level = level
        return _PROXIMITY_LEVELS[level]

    def touch(self, event: str) -> None:
        self.last_event = event
        self.updated_at = time()

    def update(self, **values: Any) -> None:
        changed = False
        for key, value in values.items():
            if hasattr(self, key) and not key.startswith("_") and getattr(self, key) != value:
                setattr(self, key, value)
                changed = True
        if changed:
            self.touch("state")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_rssi_window", None)
        data.pop("_proximity_level", None)
        return data
