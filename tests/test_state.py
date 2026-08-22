import unittest

from bluetooth_hud.state import TelemetryState


class TelemetryStateTests(unittest.TestCase):
    def test_median_filter_rejects_single_rssi_spike(self) -> None:
        state = TelemetryState(address="AA:BB:CC:DD:EE:FF")
        for value in (-60, -61, -59, -60):
            state.set_rssi(value)

        before = state.rssi_smooth
        state.set_rssi(-90)  # isolated bad sample

        self.assertEqual(state.rssi, -90)
        self.assertEqual(state.rssi_median, -60.0)
        self.assertIsNotNone(before)
        self.assertGreater(state.rssi_smooth, -65.0)

    def test_sustained_signal_change_moves_filtered_value(self) -> None:
        state = TelemetryState()
        for value in (-70, -70, -69, -70, -69):
            state.set_rssi(value)

        baseline = state.rssi_smooth
        for value in (-50, -49, -50, -48, -49):
            state.set_rssi(value)

        self.assertIsNotNone(baseline)
        self.assertGreater(state.rssi_smooth, baseline)
        self.assertIn(state.proximity, {"near", "close", "very_close"})

    def test_proximity_hysteresis_avoids_boundary_flapping(self) -> None:
        state = TelemetryState()
        for value in (-66, -66, -66, -66, -66):
            state.set_rssi(value)
        self.assertEqual(state.proximity, "near")

        # Small noise around the -68 dBm base boundary must not flip to far.
        for value in (-69, -68, -70, -67, -69):
            state.set_rssi(value)
        self.assertEqual(state.proximity, "near")

        # A sustained move clearly beyond the hysteresis margin may change zone.
        for value in (-75, -74, -76, -75, -74, -75):
            state.set_rssi(value)
        self.assertEqual(state.proximity, "far")

    def test_to_dict_hides_internal_filter_state(self) -> None:
        state = TelemetryState()
        state.set_rssi(-60)
        payload = state.to_dict()
        self.assertNotIn("_rssi_window", payload)
        self.assertNotIn("_proximity_level", payload)
        self.assertEqual(payload["rssi_median"], -60.0)

    def test_update_ignores_unknown_and_private_fields(self) -> None:
        state = TelemetryState()
        state.update(connected=True, battery=80, unknown="ignored", _proximity_level=4)
        self.assertTrue(state.connected)
        self.assertEqual(state.battery, 80)
        self.assertFalse(hasattr(state, "unknown"))
        self.assertIsNone(state._proximity_level)


if __name__ == "__main__":
    unittest.main()
