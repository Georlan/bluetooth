from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from typing import Any

from dbus_next import BusType, Variant
from dbus_next.aio import MessageBus

from .state import TelemetryState

BLUEZ = "org.bluez"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = "org.freedesktop.DBus.Properties"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
MEDIA_PLAYER = "org.bluez.MediaPlayer1"

StateCallback = Callable[[TelemetryState], Awaitable[None]]
_RSSI_RE = re.compile(r"RSSI return value:\s*(-?\d+)")


def _unwrap(values: dict[str, Variant]) -> dict[str, Any]:
    return {key: value.value for key, value in values.items()}


class BlueZMonitor:
    """Event-driven monitor for one already-known BlueZ device.

    D-Bus remains the source for connection state, battery and media metadata.
    For RSSI, the monitor prefers a fast HCI link sampler when `hcitool` is
    available and the device has an active ACL connection. This produces a much
    denser signal stream than BlueZ discovery notifications. If that path is not
    available, the monitor transparently falls back to D-Bus RSSI events.
    """

    def __init__(self, address: str, state: TelemetryState, on_state: StateCallback) -> None:
        self.address = address.upper()
        self.state = state
        self.on_state = on_state
        self.bus: MessageBus | None = None
        self.object_manager = None
        self.device_path: str | None = None
        self.adapter_path: str | None = None
        self._reconcile_task: asyncio.Task[None] | None = None
        self._fast_rssi_task: asyncio.Task[None] | None = None
        self._closed = False
        self._subscribed_paths: set[str] = set()
        self._fast_rssi_active = False
        self._fast_rssi_interval = max(
            0.10,
            float(os.getenv("BLUETOOTH_FAST_RSSI_INTERVAL", "0.25")),
        )

    async def start(self) -> None:
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        root = await self.bus.introspect(BLUEZ, "/")
        root_object = self.bus.get_proxy_object(BLUEZ, "/", root)
        self.object_manager = root_object.get_interface(OBJECT_MANAGER)
        self.object_manager.on_interfaces_added(self._interfaces_added)
        self.object_manager.on_interfaces_removed(self._interfaces_removed)

        await self._resolve_paths()
        if not self.device_path:
            raise RuntimeError(
                f"Bluetooth device {self.address} was not found in BlueZ. "
                "Pair it first with bluetoothctl."
            )

        await self._subscribe_properties(self.device_path)
        await self._subscribe_existing_children()
        await self._start_discovery()
        await self.refresh()
        self._fast_rssi_task = asyncio.create_task(self._fast_rssi_loop())
        self._reconcile_task = asyncio.create_task(self._reconcile_loop())

    async def close(self) -> None:
        self._closed = True
        for task in (self._fast_rssi_task, self._reconcile_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self.bus:
            self.bus.disconnect()

    async def _resolve_paths(self) -> None:
        assert self.object_manager is not None
        managed = await self.object_manager.call_get_managed_objects()
        for path, interfaces in managed.items():
            if ADAPTER in interfaces and self.adapter_path is None:
                self.adapter_path = path
            props = interfaces.get(DEVICE)
            if props and props.get("Address") and props["Address"].value.upper() == self.address:
                self.device_path = path

    async def _subscribe_existing_children(self) -> None:
        assert self.object_manager is not None
        if not self.device_path:
            return
        managed = await self.object_manager.call_get_managed_objects()
        for path, interfaces in managed.items():
            if path.startswith(self.device_path) and any(
                name in interfaces for name in (BATTERY, MEDIA_PLAYER)
            ):
                await self._subscribe_properties(path)

    async def _start_discovery(self) -> None:
        if not self.adapter_path or not self.bus:
            return

        introspection = await self.bus.introspect(BLUEZ, self.adapter_path)
        obj = self.bus.get_proxy_object(BLUEZ, self.adapter_path, introspection)
        adapter = obj.get_interface(ADAPTER)

        discovery_filter = {
            "Transport": Variant("s", "auto"),
            "RSSI": Variant("n", -127),
            "DuplicateData": Variant("b", True),
        }
        try:
            await adapter.call_set_discovery_filter(discovery_filter)
        except Exception:
            pass

        try:
            await adapter.call_start_discovery()
        except Exception as exc:
            if "InProgress" not in str(exc):
                raise

    async def _subscribe_properties(self, path: str) -> None:
        if not self.bus or path in self._subscribed_paths:
            return
        introspection = await self.bus.introspect(BLUEZ, path)
        obj = self.bus.get_proxy_object(BLUEZ, path, introspection)
        props = obj.get_interface(PROPERTIES)

        def changed(interface_name: str, changed_props: dict[str, Variant], invalidated: list[str]) -> None:
            del invalidated
            self._handle_properties(interface_name, changed_props)

        props.on_properties_changed(changed)
        self._subscribed_paths.add(path)

    def _handle_properties(self, interface_name: str, changed_props: dict[str, Variant]) -> None:
        values = _unwrap(changed_props)
        changed = False

        if interface_name == DEVICE:
            if "RSSI" in values and not self._fast_rssi_active:
                self.state.set_rssi(int(values["RSSI"]), source="dbus")
                changed = True
            mapping = {
                "Name": "name",
                "Connected": "connected",
                "Paired": "paired",
                "Trusted": "trusted",
            }
            update = {
                target: values[source]
                for source, target in mapping.items()
                if source in values
            }
            if update:
                self.state.update(**update)
                changed = True

        elif interface_name == BATTERY and "Percentage" in values:
            self.state.update(battery=int(values["Percentage"]))
            changed = True

        elif interface_name == MEDIA_PLAYER:
            update: dict[str, Any] = {}
            if "Status" in values:
                update["player_status"] = str(values["Status"])
            if "Position" in values:
                update["player_position_ms"] = int(values["Position"])
            if update:
                self.state.update(**update)
                changed = True

        if changed:
            asyncio.create_task(self.on_state(self.state))

    async def _fast_rssi_loop(self) -> None:
        """Poll controller link RSSI at a practical UI rate when possible."""
        hcitool = shutil.which("hcitool")
        if not hcitool:
            return

        failures = 0
        while not self._closed:
            started = asyncio.get_running_loop().time()
            try:
                if not self.state.connected:
                    self._fast_rssi_active = False
                    failures = 0
                else:
                    proc = await asyncio.create_subprocess_exec(
                        hcitool,
                        "rssi",
                        self.address,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1.0)
                    text = stdout.decode(errors="ignore")
                    match = _RSSI_RE.search(text)
                    if proc.returncode == 0 and match:
                        failures = 0
                        self._fast_rssi_active = True
                        self.state.set_rssi(int(match.group(1)), source="hci")
                        await self.on_state(self.state)
                    else:
                        failures += 1
            except (asyncio.TimeoutError, OSError):
                failures += 1

            # If the connected-link reader repeatedly fails, allow D-Bus RSSI
            # events back in instead of freezing the signal pipeline.
            if failures >= 3:
                self._fast_rssi_active = False

            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.02, self._fast_rssi_interval - elapsed))

    def _interfaces_added(self, path: str, interfaces: dict[str, dict[str, Variant]]) -> None:
        device_props = interfaces.get(DEVICE)
        if device_props and device_props.get("Address"):
            if device_props["Address"].value.upper() == self.address:
                self.device_path = path

        if self.device_path and path.startswith(self.device_path):
            for interface_name, props in interfaces.items():
                if interface_name in {DEVICE, BATTERY, MEDIA_PLAYER}:
                    self._handle_properties(interface_name, props)
            asyncio.create_task(self._subscribe_properties(path))

    def _interfaces_removed(self, path: str, interfaces: list[str]) -> None:
        if not self.device_path or not path.startswith(self.device_path):
            return
        self._subscribed_paths.discard(path)
        if MEDIA_PLAYER in interfaces:
            self.state.update(player_status=None, player_position_ms=None)
            asyncio.create_task(self.on_state(self.state))

    async def refresh(self) -> None:
        assert self.object_manager is not None
        managed = await self.object_manager.call_get_managed_objects()

        if not self.device_path:
            await self._resolve_paths()
            if not self.device_path:
                return

        interfaces = managed.get(self.device_path, {})
        if DEVICE in interfaces:
            self._handle_properties(DEVICE, interfaces[DEVICE])
        if BATTERY in interfaces:
            self._handle_properties(BATTERY, interfaces[BATTERY])

        for path, child_interfaces in managed.items():
            if path.startswith(self.device_path) and MEDIA_PLAYER in child_interfaces:
                self._handle_properties(MEDIA_PLAYER, child_interfaces[MEDIA_PLAYER])
                await self._subscribe_properties(path)

        self.state.address = self.address
        self.state.touch("snapshot")
        await self.on_state(self.state)

    async def _reconcile_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(5)
            try:
                await self.refresh()
            except Exception:
                pass
