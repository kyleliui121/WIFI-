"""Focused regression checks for the MAC approximation (SimPy required)."""
import unittest

from wifi_sim.priority import MACConfig, MACSimulator, MODES, Packet
from wifi_sim.theory import collision_probability, attempt_probability


class PriorityMACTests(unittest.TestCase):
    def test_four_modes_and_flow_accounting(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                r = MACSimulator(MACConfig(stations=10, duration_s=0.2,
                                           mode=mode, seed=42)).run()
                self.assertEqual(r.high_generated, 40)
                self.assertEqual(r.high_generated,
                                 r.high_success + r.high_dropped + r.unfinished_high)
                self.assertEqual(r.attempts,
                                 r.high_success + r.low_success + r.collisions)
                self.assertGreater(r.low_bits, 0)
                self.assertGreater(r.attempts, 0)

    def test_same_seed_reproduces_results(self):
        config = MACConfig(stations=20, mode="NPCA", duration_s=0.15, seed=44)
        a = MACSimulator(config).run()
        b = MACSimulator(config).run()
        self.assertEqual(a.as_dict(), b.as_dict())
        self.assertEqual(a.high_delays_us, b.high_delays_us)

    def test_npca_uses_secondary_during_external_busy(self):
        r = MACSimulator(MACConfig(stations=10, mode="NPCA",
                                   duration_s=0.5, seed=42)).run()
        self.assertGreater(r.secondary_success, 0)
        self.assertGreater(r.switch_events, 0)
        self.assertGreater(r.external_busy_us, 0)

    def test_one_frame_ack_and_priority_settings(self):
        sim = MACSimulator(MACConfig(stations=5, mode="P-EDCA"))
        self.assertEqual(sim._params(sim.nodes[0]), (2, 3, 7))
        self.assertEqual(sim._params(sim.nodes[-1]), (3, 15, 1023))
        high = sim.nodes[0]
        high.queue.append(Packet(0.0))
        sim._reset_backoff(high)
        sim._refresh_urgent_one(high, 5000)
        self.assertEqual(sim._params(high), (1, 1, 3))
        self.assertLessEqual(high.backoff, 3)

    def test_external_busy_duty_approximately_target(self):
        sim = MACSimulator(MACConfig(mode="EDCA", duration_s=10, stations=10))
        calendar = sim.external_events
        busy = sum(calendar[i+1][0] - calendar[i][0]
                   for i in range(0, len(calendar), 2))
        self.assertTrue(0.25 < busy / sim.config.duration_us < 0.35)

    def test_bianchi_fixed_point(self):
        p = collision_probability(20)
        tau = attempt_probability(p)
        self.assertAlmostEqual(p, 1-(1-tau)**19, places=9)
        self.assertTrue(0 < collision_probability(5) < p < collision_probability(50) < 1)
        self.assertTrue(0 < collision_probability(20, retry_limit=7) < 1)


if __name__ == "__main__":
    unittest.main()
