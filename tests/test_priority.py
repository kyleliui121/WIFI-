"""Focused regression checks for the MAC approximation (SimPy required)."""
import unittest

from wifi_sim.priority import MACConfig, MACSimulator, MODES, Packet
from wifi_sim.theory import collision_probability, attempt_probability


class PriorityMACTests(unittest.TestCase):
    def _guard_scenario(self, mode, short_ready_us):
        sim = MACSimulator(MACConfig(stations=3, high_stations=1,
                                     mode=mode, duration_s=0.001))
        sim.external_events = [(200.0, True), (400.0, False)]
        sim.next_arrival = sim.config.duration_us
        for node in sim.nodes:
            node.queue.clear()
            node.backoff = 0
            node.ifs_remaining = 0.0
        short, long = sim.nodes[:2]
        short.queue.append(Packet(0.0))
        short.ifs_remaining = short_ready_us
        long.queue.append(Packet(0.0))
        sim.report.high_generated = 1
        return sim, short, long

    def test_deferred_long_frame_keeps_later_short_frame_wakeup(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                sim, short, long = self._guard_scenario(mode, 50.0)
                sim._start_ready_transmissions(0.0)
                self.assertIsNone(sim.busy[0])
                self.assertEqual(sim._next_event(0.0), 50.0)
                sim._advance(50.0)
                sim._start_ready_transmissions(50.0)
                self.assertEqual(sim.busy[0].contenders, [short])
                self.assertFalse(long.transmitting)
                self.assertLessEqual(sim.busy[0].end_us, 200.0)

    def test_simultaneous_short_frame_and_exact_fit_are_admitted(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                sim, short, long = self._guard_scenario(mode, 0.0)
                boundary = sim.config.tx_us([sim.config.high_frame_bytes])
                sim.external_events[0] = (boundary, True)
                sim._start_ready_transmissions(0.0)
                self.assertEqual(sim.busy[0].contenders, [short])
                self.assertEqual(sim.busy[0].end_us, boundary)
                self.assertFalse(long.transmitting)
                self.assertEqual(sim.report.attempts, 1)

    def test_deferral_advances_time_and_long_frame_resumes(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                sim, _, _ = self._guard_scenario(mode, 50.0)
                next_event = sim._next_event
                wakeups = []

                def checked_next_event(now):
                    self.assertLess(len(wakeups), 1000)
                    if wakeups:
                        self.assertGreater(now, wakeups[-1])
                    wakeups.append(now)
                    future = next_event(now)
                    self.assertGreater(future, now)
                    return future

                sim._next_event = checked_next_event
                result = sim.run()
                self.assertEqual(sim.env.now, sim.config.duration_us)
                self.assertEqual(result.high_success, 1)
                self.assertLess(result.high_delays_us[0], 200.0)
                self.assertGreater(result.low_success, 0)

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
