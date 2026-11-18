"""Focused regression checks for the MAC approximation (SimPy required)."""
import unittest
from unittest.mock import patch

from wifi_sim.priority import MACConfig, MACResult, MACSimulator, MODES, Packet
from wifi_sim.theory import collision_probability, attempt_probability


class PriorityMACTests(unittest.TestCase):
    def _outcome_scenario(self, mode, high_stations=1, deadline_us=1000.0, **options):
        sim = MACSimulator(MACConfig(stations=4, high_stations=high_stations,
            mode=mode, duration_s=0.0005, retry_limit=0, deadline_us=deadline_us, **options))
        sim.external_events = []
        sim.next_arrival = sim.config.duration_us
        for node in sim.nodes:
            node.queue.clear()
            node.backoff = 0
            node.ifs_remaining = 0.0
            if node.high:
                node.queue.append(Packet(0.0))
        sim.report.high_generated = high_stations
        return sim

    def test_retry_drop_before_deadline_is_not_successful_delay_timeout(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                sim = self._outcome_scenario(mode, high_stations=2)
                r = sim.run()
                self.assertLess(sim.config.duration_us, sim.config.deadline_us)
                self.assertEqual(r.high_success, 0)
                self.assertEqual(r.high_dropped, 2)
                self.assertEqual(r.high_success_late, 0)
                self.assertEqual(r.high_delays_us, [])
                row = r.as_dict()
                self.assertIsNone(row['high_success_late_pct'])
                self.assertEqual(row['high_drop_pct'], 100.0)
                self.assertEqual(row['high_deadline_failure'], 2)
                self.assertEqual(row['deadline_failure_pct'], 100.0)
                self.assertEqual(row['high_unfinished'], 0)

    def test_success_delay_deadline_boundary(self):
        duration = MACConfig().tx_us([MACConfig().high_frame_bytes])
        for mode in MODES:
            for deadline, late in ((duration, 0), (duration - 1, 1)):
                with self.subTest(mode=mode, deadline=deadline):
                    r = self._outcome_scenario(mode, deadline_us=deadline).run()
                    self.assertEqual(r.high_success, 1)
                    self.assertEqual(r.high_success_late, late)
                    self.assertEqual(r.high_dropped, 0)
                    self.assertEqual(r.as_dict()['high_success_late_pct'], 100 * late)
                    self.assertEqual(r.as_dict()['deadline_failure_pct'], 100 * late)

    def test_unfinished_frames_are_separate_from_resolved_outcomes(self):
        sim = self._outcome_scenario('EDCA', deadline_us=10.0)
        sim.external_events = [(0.0, True), (sim.config.duration_us, False)]
        row = sim.run().as_dict()
        self.assertEqual(row['high_unfinished'], 1)
        self.assertEqual(row['high_unfinished_pct'], 100.0)
        self.assertEqual(row['high_resolved'], 0)
        self.assertEqual(row['high_success_late'], 0)
        self.assertEqual(row['high_dropped'], 0)
        self.assertEqual(row['high_deadline_failure'], 0)
        self.assertEqual(row['high_deadline_observed'], 1)
        self.assertEqual(row['high_unfinished_overdue'], 1)
        self.assertEqual(row['deadline_observed_failure_pct'], 100.0)
        for key in ('high_success_late_pct', 'high_drop_pct', 'deadline_failure_pct'):
            self.assertIsNone(row[key])

    def test_deadline_cohort_excludes_recent_arrivals_even_if_resolved(self):
        sim = self._outcome_scenario('EDCA', high_stations=2, deadline_us=1000.0)
        row = sim.run().as_dict()
        self.assertEqual(row['high_dropped'], 2)
        self.assertEqual(row['high_deadline_observed'], 0)
        self.assertIsNone(row['deadline_observed_failure_pct'])

    def test_metric_numerators_and_denominators(self):
        r = MACResult(MACConfig(), high_generated=10, high_success=4,
                      high_success_late=1, high_dropped=2, unfinished_high=4)
        row = r.as_dict()
        self.assertEqual(row['high_resolved'], 6)
        self.assertEqual(row['high_success_late_pct'], 25.0)
        self.assertAlmostEqual(row['high_drop_pct'], 100 * 2 / 6)
        self.assertEqual(row['high_deadline_failure'], 3)
        self.assertEqual(row['deadline_failure_pct'], 50.0)
        self.assertEqual(row['high_unfinished_pct'], 40.0)
        self.assertNotIn('deadline_miss_pct', row)
        empty = MACResult(MACConfig()).as_dict()
        for key in ('high_success_late_pct', 'high_drop_pct',
                    'deadline_failure_pct', 'high_unfinished_pct'):
            self.assertIsNone(empty[key])

    def _guard_scenario(self, mode, short_ready_us, hidden_terminals=False):
        sim = MACSimulator(MACConfig(stations=4, high_stations=1, mode=mode,
                           duration_s=0.001, hidden_terminals=hidden_terminals))
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
                self.assertFalse(sim.busy[0])
                self.assertEqual(sim._next_event(0.0), 50.0)
                sim._advance(50.0)
                sim._start_ready_transmissions(50.0)
                self.assertEqual(sim.busy[0][0].contenders, [short])
                self.assertFalse(long.transmitting)
                self.assertLessEqual(sim.busy[0][0].end_us, 200.0)

    def test_simultaneous_short_frame_and_exact_fit_are_admitted(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                sim, short, long = self._guard_scenario(mode, 0.0)
                boundary = sim.config.tx_us([sim.config.high_frame_bytes])
                sim.external_events[0] = (boundary, True)
                sim._start_ready_transmissions(0.0)
                self.assertEqual(sim.busy[0][0].contenders, [short])
                self.assertEqual(sim.busy[0][0].end_us, boundary)
                self.assertFalse(long.transmitting)
                self.assertEqual(sim.report.attempts, 1)

    def test_hidden_terminals_keep_later_short_frame_eligible(self):
        sim, short, long = self._guard_scenario("EDCA", 50.0, hidden_terminals=True)
        sim._start_ready_transmissions(0.0)
        self.assertFalse(sim.busy[0])
        self.assertEqual(sim._next_event(0.0), 50.0)
        sim._advance(50.0)
        sim._start_ready_transmissions(50.0)
        self.assertEqual(sim.busy[0][short.group].contenders, [short])
        self.assertFalse(long.transmitting)

    def test_hidden_groups_continue_countdown_and_both_fail_on_overlap(self):
        sim = self._outcome_scenario("EDCA", high_stations=2, deadline_us=200.0,
                                     hidden_terminals=True, frame_error_rate=0.05)
        sim.nodes[1].ifs_remaining = 30.0
        with patch.object(sim.error_rng, "random", return_value=0.0) as draw:
            report = sim.run()
        draw.assert_not_called()
        self.assertEqual(report.hidden_collision_events, 1)
        self.assertEqual(report.collision_events, 1)
        self.assertEqual(report.collisions, 2)
        self.assertEqual(report.high_dropped_by_collision, 2)
        self.assertEqual(report.frame_errors, 0)
        self.assertEqual(len({packet["completed_us"] for packet in report.high_packets}), 1)
        self.assertEqual(report.as_dict()["deadline_observed_failure_pct"], 100.0)

    def test_corruption_drop_is_recorded_without_counting_collision_or_late_success(self):
        sim = self._outcome_scenario("EDCA", deadline_us=200.0, frame_error_rate=0.05)
        with patch.object(sim.error_rng, "random", return_value=0.0) as draw:
            report = sim.run()
        draw.assert_called_once()
        self.assertEqual(report.frame_errors, 1)
        self.assertEqual(report.collisions, 0)
        self.assertEqual(report.high_dropped_by_error, 1)
        self.assertEqual(report.high_success_late, 0)
        self.assertEqual(report.high_packets[0]["outcome"], "dropped")
        self.assertEqual(report.as_dict()["deadline_observed_failure_pct"], 100.0)

    def test_extension_options_default_to_off_and_validate_parameters(self):
        sim = self._outcome_scenario("EDCA")
        self.assertFalse(sim.config.hidden_terminals)
        self.assertEqual(sim.config.frame_error_rate, 0.0)
        with patch.object(sim.error_rng, "random") as draw:
            self.assertEqual(sim.run().high_success, 1)
        draw.assert_not_called()
        for options in ({"frame_error_rate": 1.0}, {"frame_error_rate": -0.01},
                        {"stations": 3, "hidden_terminals": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                MACConfig(**options)

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
