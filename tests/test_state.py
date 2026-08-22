import unittest

from bluetooth_hud.state import TelemetryState


class TelemetryStateTests(unittest.TestCase):
    def test_rssi_uses_exponential_smoothing(self) -> None:
        state = TelemetryState(address="AA:BB:CC:DD:EE:FF")
        state.set_rssi(-70)
        self.assertEqual(state.rssi, -70)
        self.assertEqual(state.rssi_smooth, -70.0)

        state.set_rssi(-50, alpha=0.5)
        self.assertEqual(state.rssi, -50)
        self.assertAlmostEqual(state.rssi_smooth, -60.0)
        self.assertEqual(state.rssi_trend, "approaching")
        self.assertEqual(state.rssi_samples, 2)

    def test_proximity_is_qualitative(self) -> None:
        state = TelemetryState()
        state.set_rssi(-44)
        self.assertEqual(state.proximity, "very_close")

        state = TelemetryState()
        state.set_rssi(-63)
        self.assertEqual(state.proximity, "near")

        state = TelemetryState()
        state.set_rssi(-84)
        self.assertEqual(state.proximity, "very_far")

    def test_update_ignores_unknown_fields(self) -> None:
        state = TelemetryState()
        state.update(connected=True, battery=80, unknown="ignored")
        self.assertTrue(state.connected)
        self.assertEqual(state.battery, 80)
        self.assertFalse(hasattr(state, "unknown"))


if __name__ == "__main__":
    unittest.main()
