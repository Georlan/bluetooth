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
    player_status: str | None = None
    player_position_ms: int | None = None
    last_event: str = "boot"
    updated_at: float = 0.0

    def set_rssi(self, value: int, alpha: float = 0.32) -> None:
        self.rssi = value
        if self.rssi_smooth is None:
            self.rssi_smooth = float(value)
        else:
            self.rssi_smooth = alpha * value + (1.0 - alpha) * self.rssi_smooth
        self.touch("rssi")

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
