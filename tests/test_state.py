import unittest

from bluetooth_hud.state import TelemetryState


class TelemetryStateTests(unittest.TestCase):
    def test_median_filter_rejects_single_rssi_spike(self) -> None:
        state = TelemetryState(address="AA:BB:CC:DD:EE:FF")
        for value in (-60, -61, -59, -60):
            state.set_rssi(value)
        state.set_rssi(-90)
        self.assertEqual(state.rssi, -90)
        self.assertEqual(state.rssi_median, -60.0)
        self.assertGreater(state.rssi_smooth, -65.0)

    def test_invalid_zero_rssi_is_rejected(self) -> None:
        state = TelemetryState()
        self.assertFalse(state.set_rssi(0, source="hci"))
        self.assertEqual(state.rssi_samples, 0)
        self.assertIsNone(state.rssi)

    def test_source_switch_resets_filter_history(self) -> None:
        state = TelemetryState()
        for value in (-20, -21, -22, -21, -20):
            state.set_rssi(value, source="hci")
        state.set_rssi(-65, source="dbus")
        self.assertEqual(state.rssi_source, "dbus")
        self.assertEqual(state.rssi_median, -65.0)
        self.assertEqual(state.rssi_smooth, -65.0)
        self.assertEqual(state.rssi_recent, [-65])

    def test_proximity_uses_median_not_stale_ema(self) -> None:
        state = TelemetryState()
        for value in (-58, -58, -58, -58, -58):
            state.set_rssi(value)
        self.assertEqual(state.proximity, "very_close")
        for value in (-66, -66, -66, -66, -66):
            state.set_rssi(value)
        self.assertEqual(state.rssi_median, -66.0)
        self.assertEqual(state.proximity, "close")
        self.assertLessEqual(abs(state.rssi_smooth - state.rssi_median), 4.0)

    def test_calibration_matches_measured_near_and_two_meter_points(self) -> None:
        near = TelemetryState()
        for value in (-58, -58, -59, -57, -58):
            near.set_rssi(value)
        self.assertEqual(near.proximity, "very_close")

        two_m = TelemetryState()
        for value in (-78, -78, -79, -77, -78):
            two_m.set_rssi(value)
        self.assertIn(two_m.proximity, {"far", "near"})

    def test_least_squares_trend_detects_sustained_motion(self) -> None:
        state = TelemetryState()
        for value in (-78, -76, -74, -72, -69, -66, -63, -60):
            state.set_rssi(value)
        self.assertGreater(state.rssi_trend_slope, 0.7)
        self.assertEqual(state.rssi_trend, "approaching")

        state = TelemetryState()
        for value in (-58, -60, -63, -66, -70, -73, -76, -79):
            state.set_rssi(value)
        self.assertLess(state.rssi_trend_slope, -0.7)
        self.assertEqual(state.rssi_trend, "moving_away")

    def test_recent_sequences_are_exposed_but_internal_window_is_hidden(self) -> None:
        state = TelemetryState()
        for value in range(-60, -85, -1):
            state.set_rssi(value)
        payload = state.to_dict()
        self.assertEqual(len(payload["rssi_recent"]), 20)
        self.assertEqual(len(payload["rssi_filtered_recent"]), 20)
        self.assertNotIn("_rssi_window", payload)
        self.assertNotIn("_proximity_level", payload)

    def test_lan_presence_sample_is_exposed_without_claiming_distance(self) -> None:
        state = TelemetryState()
        state.set_lan_sample("192.168.1.50", True, 4.2)
        payload = state.to_dict()
        self.assertEqual(payload["lan_target_ip"], "192.168.1.50")
        self.assertTrue(payload["lan_present"])
        self.assertEqual(payload["lan_rtt_ms"], 4.2)
        self.assertGreater(payload["lan_updated_at"], 0)
        self.assertNotIn("_lan_sample_times", payload)

    def test_update_ignores_unknown_and_private_fields(self) -> None:
        state = TelemetryState()
        state.update(connected=True, battery=80, unknown="ignored", _proximity_level=4)
        self.assertTrue(state.connected)
        self.assertEqual(state.battery, 80)
        self.assertFalse(hasattr(state, "unknown"))
        self.assertIsNone(state._proximity_level)


if __name__ == "__main__":
    unittest.main()
