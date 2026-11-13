"""Minimal behavioral checks of the saturated DCF baseline."""

import unittest

from wifi_sim import DCFConfig, DCFSimulator


class DCFTests(unittest.TestCase):
    def test_contention_window_binary_exponential_backoff(self):
        sim = DCFSimulator(DCFConfig(stations=1))
        self.assertEqual([sim.contention_window(i) for i in (0, 1, 2, 7)],
                         [15, 31, 63, 1023])

    def test_single_station_never_collides(self):
        result = DCFSimulator(DCFConfig(stations=1, duration_s=0.05)).run()
        self.assertGreater(result.successful_frames, 0)
        self.assertEqual(result.collided_attempts, 0)
        self.assertEqual(result.dropped_frames, 0)
        self.assertEqual(result.attempts, result.successful_frames)

    def test_collision_and_retry_limit(self):
        config = DCFConfig(stations=2, duration_s=0.00032, retry_limit=0)
        sim = DCFSimulator(config)
        for station in sim.stations:
            station.backoff = 0
        result = sim.run()
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.collided_attempts, 2)
        self.assertEqual(result.collision_events, 1)
        self.assertEqual(result.dropped_frames, 2)
        self.assertEqual(result.successful_frames, 0)

    def test_reproducible_and_attempt_accounting(self):
        cfg = DCFConfig(stations=10, duration_s=0.1, seed=123)
        first = DCFSimulator(cfg).run()
        second = DCFSimulator(cfg).run()
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(first.attempts,
                         first.successful_frames + first.collided_attempts)
        self.assertGreater(first.collided_attempts, 0)
        self.assertGreater(first.throughput_mbps, 0)

    def test_rejects_invalid_config(self):
        with self.assertRaises(ValueError):
            DCFConfig(stations=0)
        with self.assertRaises(ValueError):
            DCFConfig(cw_min=16, cw_max=15)


if __name__ == "__main__":
    unittest.main()
