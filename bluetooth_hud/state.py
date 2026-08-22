from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from time import time
from typing import Any


_PROXIMITY_LEVELS = ("very_far", "far", "near", "close", "very_close")
# Boundary to move from level N to N+1, from weak to strong signal.
_PROXIMITY_BOUNDARIES = (-78.0, -68.0, -58.0, -48.0)


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
    rssi_samples: int = 0
    rssi_updated_at: float = 0.0
    proximity: str = "unknown"
    player_status: str | None = None
    player_position_ms: int | None = None
    last_event: str = "boot"
    updated_at: float = 0.0
    _rssi_window: list[int] = field(default_factory=list, repr=False)
    _proximity_level: int | None = field(default=None, repr=False)

    def set_rssi(self, value: int) -> None:
        """Filter a noisy RSSI sample and update qualitative proximity.

        Pipeline:
        1. Keep the last 5 raw samples.
        2. Median filter rejects short spikes/outliers.
        3. Adaptive EMA smooths jitter but reacts faster to sustained movement.
        4. Hysteresis prevents proximity labels oscillating at zone boundaries.
        """
        previous = self.rssi_smooth
        self.rssi = value

        self._rssi_window.append(value)
        if len(self._rssi_window) > 5:
            del self._rssi_window[0]

        filtered = float(median(self._rssi_window))
        self.rssi_median = filtered

        if previous is None:
            smoothed = filtered
            trend = "stable"
        else:
            # Fast enough when the median genuinely moves, conservative on jitter.
            gap = abs(filtered - previous)
            alpha = 0.52 if gap >= 8.0 else 0.30
            smoothed = alpha * filtered + (1.0 - alpha) * previous
            delta = smoothed - previous
            if delta >= 1.5:
                trend = "approaching"
            elif delta <= -1.5:
                trend = "moving_away"
            else:
                trend = "stable"

        self.rssi_smooth = smoothed
        self.rssi_trend = trend
        self.rssi_samples += 1
        self.rssi_updated_at = time()
        self.proximity = self._proximity_with_hysteresis(smoothed)
        self.touch("rssi")

    @staticmethod
    def _base_proximity_level(rssi: float) -> int:
        if rssi >= -48:
            return 4
        if rssi >= -58:
            return 3
        if rssi >= -68:
            return 2
        if rssi >= -78:
            return 1
        return 0

    def _proximity_with_hysteresis(self, rssi: float, margin: float = 3.0) -> str:
        """Return a stable qualitative zone using a +/- dB hysteresis margin."""
        if self._proximity_level is None:
            self._proximity_level = self._base_proximity_level(rssi)
            return _PROXIMITY_LEVELS[self._proximity_level]

        level = self._proximity_level

        # Moving closer requires exceeding the next boundary by the margin.
        while level < 4 and rssi >= _PROXIMITY_BOUNDARIES[level] + margin:
            level += 1

        # Moving farther requires falling below the current boundary by the margin.
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
