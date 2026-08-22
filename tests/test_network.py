import unittest
from unittest.mock import AsyncMock, patch

from bluetooth_hud.network import LanMonitor
from bluetooth_hud.state import TelemetryState


class LanMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_ip_command_degrades_to_no_data(self) -> None:
        callback = AsyncMock()
        monitor = LanMonitor(TelemetryState(), callback)

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await monitor._run_json("ip", "-j", "neigh")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
