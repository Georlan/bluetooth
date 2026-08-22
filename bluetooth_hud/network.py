from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from typing import Any

from .state import TelemetryState

StateCallback = Callable[[TelemetryState], Awaitable[None]]
_RTT_RE = re.compile(r"time[=<]([0-9.]+)\s*ms")


class LanMonitor:
    """Best-effort LAN presence monitor for the phone.

    This does not pretend that RTT is physical distance. It answers a different
    question quickly: is the target still reachable on the same LAN? If
    PHONE_LAN_IP is not configured, the monitor auto-selects only when there is
    exactly one non-gateway neighbour, avoiding silent misidentification.
    """

    def __init__(self, state: TelemetryState, on_state: StateCallback) -> None:
        self.state = state
        self.on_state = on_state
        self.target_ip = os.getenv("PHONE_LAN_IP") or None
        self.interval = max(0.25, float(os.getenv("PHONE_LAN_INTERVAL", "0.50")))
        self._closed = False
        self._task: asyncio.Task[None] | None = None
        self._discover_counter = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def close(self) -> None:
        self._closed = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_json(self, *args: str) -> Any:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            return None
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        try:
            return json.loads(stdout.decode(errors="ignore"))
        except json.JSONDecodeError:
            return None

    async def _gateway(self) -> str | None:
        data = await self._run_json("ip", "-j", "route", "show", "default")
        if not data:
            return None
        return data[0].get("gateway")

    async def _local_addresses(self) -> set[str]:
        data = await self._run_json("ip", "-j", "addr", "show") or []
        result: set[str] = set()
        for interface in data:
            for addr in interface.get("addr_info", []):
                if addr.get("family") == "inet" and addr.get("local"):
                    result.add(addr["local"])
        return result

    async def _discover_candidates(self) -> list[dict[str, str]]:
        data = await self._run_json("ip", "-j", "neigh") or []
        gateway = await self._gateway()
        locals_ = await self._local_addresses()
        candidates: list[dict[str, str]] = []
        for item in data:
            ip = item.get("dst")
            if not ip or ip == gateway or ip in locals_ or ":" in ip:
                continue
            state = str(item.get("state", "")).upper()
            if state in {"FAILED", "INCOMPLETE", "NOARP"}:
                continue
            candidates.append({
                "ip": ip,
                "mac": item.get("lladdr", ""),
                "state": state,
                "dev": item.get("dev", ""),
            })
        return candidates

    async def _ping_once(self, ip: str) -> tuple[bool, float | None]:
        ping = shutil.which("ping")
        if not ping:
            return False, None
        try:
            proc = await asyncio.create_subprocess_exec(
                ping,
                "-n",
                "-c",
                "1",
                "-W",
                "1",
                ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1.25)
        except (asyncio.TimeoutError, OSError):
            return False, None
        text = stdout.decode(errors="ignore")
        match = _RTT_RE.search(text)
        return proc.returncode == 0, float(match.group(1)) if match else None

    async def _refresh_target(self) -> None:
        candidates = await self._discover_candidates()
        self.state.update(lan_candidates=candidates)

        if os.getenv("PHONE_LAN_IP"):
            self.target_ip = os.getenv("PHONE_LAN_IP")
            self.state.update(lan_target_mode="configured")
            return

        if len(candidates) == 1:
            self.target_ip = candidates[0]["ip"]
            self.state.update(lan_target_mode="auto-single")
        else:
            self.target_ip = None
            self.state.update(lan_target_mode="ambiguous" if candidates else "none")

    async def _loop(self) -> None:
        while not self._closed:
            started = asyncio.get_running_loop().time()
            self._discover_counter += 1
            if self.target_ip is None or self._discover_counter % 10 == 1:
                await self._refresh_target()

            if self.target_ip:
                present, rtt = await self._ping_once(self.target_ip)
                self.state.set_lan_sample(self.target_ip, present, rtt)
                await self.on_state(self.state)
            else:
                self.state.set_lan_sample(None, False, None)
                await self.on_state(self.state)

            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.05, self.interval - elapsed))
