from __future__ import annotations

from dataclasses import asdict, dataclass
from time import time
from typing import Any


@dataclass(slots=True)
class TelemetryState:
    name: str = "Unknown device"
    address: str = ""
    connected: bool = False
    paired: bool = False
    trusted: bool = False
    battery: int | None = None
    rssi: int | None = None
    rssi_smooth: float | None = None
    rssi_trend: str = "stable"
    rssi_samples: int = 0
    rssi_updated_at: float = 0.0
    proximity: str = "unknown"
    player_status: str | None = None
    player_position_ms: int | None = None
    last_event: str = "boot"
    updated_at: float = 0.0

    def set_rssi(self, value: int, alpha: float = 0.42) -> None:
        previous = self.rssi_smooth
        self.rssi = value

        if previous is None:
            smoothed = float(value)
            trend = "stable"
        else:
            smoothed = alpha * value + (1.0 - alpha) * previous
            delta = smoothed - previous
            if delta >= 1.2:
                trend = "approaching"
            elif delta <= -1.2:
                trend = "moving_away"
            else:
                trend = "stable"

        self.rssi_smooth = smoothed
        self.rssi_trend = trend
        self.rssi_samples += 1
        self.rssi_updated_at = time()
        self.proximity = self._proximity(smoothed)
        self.touch("rssi")

    @staticmethod
    def _proximity(rssi: float) -> str:
        # RSSI is not distance. These bands are intentionally qualitative.
        if rssi >= -48:
            return "very_close"
        if rssi >= -58:
            return "close"
        if rssi >= -68:
            return "near"
        if rssi >= -78:
            return "far"
        return "very_far"

    def touch(self, event: str) -> None:
        self.last_event = event
        self.updated_at = time()

    def update(self, **values: Any) -> None:
        changed = False
        for key, value in values.items():
            if hasattr(self, key) and getattr(self, key) != value:
                setattr(self, key, value)
                changed = True
        if changed:
            self.touch("state")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
