"""Regression checks for the four-AC extension model (SimPy required)."""
import unittest

from wifi_sim.multiac import (ACParams, MultiACConfig, MultiACSimulator, Packet,
                              DEFAULT_ACS)


def run(stations=10, mode="EDCA", duration=0.2, seed=42, **kwargs):
    simulator = MultiACSimulator(MultiACConfig(
        stations=stations, mode=mode, duration_s=duration, seed=seed,
        **kwargs))
    simulator.run()
    return simulator


class FourACTests(unittest.TestCase):
    def test_accounting_both_modes(self):
        for mode in ("DCF", "EDCA"):
            with self.subTest(mode=mode):
                simulator = run(mode=mode, duration=0.5)
                total = 0
                for row in simulator.rows():
                    self.assertEqual(
                        row["generated"],
                        row["success"] + row["dropped"] + row["unfinished"])
                    if row["ac"] in ("VO", "VI"):
                        self.assertIsNotNone(row["deadline_observed_failure_pct"])
                    else:
                        self.assertIsNone(row["deadline_observed_failure_pct"])
                    total += row["success"]
                self.assertEqual(simulator.attempts,
                                 total + simulator.collisions)
                self.assertGreater(total, 0)

    def test_same_seed_is_deterministic(self):
        first = run(mode="EDCA", duration=0.3, seed=44).rows()
        second = run(mode="EDCA", duration=0.3, seed=44).rows()
        self.assertEqual(first, second)

    def test_periodic_arrivals_and_saturated_sources(self):
        simulator = run(mode="EDCA", duration=0.5, seed=42)
        rows = {row["ac"]: row for row in simulator.rows()}
        # 0.5 s at 10 ms period = 50 arrivals per VO station, 2 stations.
        self.assertEqual(rows["VO"]["generated"], 100)
        self.assertEqual(rows["VI"]["generated"], 100)
        # Saturated sources keep generating; tiny windows may under-count by one.
        self.assertGreaterEqual(rows["BE"]["generated"], 40)
        self.assertGreaterEqual(rows["BK"]["generated"], 40)

    def test_edca_protects_vo_and_vi(self):
        edca = run(mode="EDCA", duration=2.0, seed=42)
        dcf = run(mode="DCF", duration=2.0, seed=42)
        edca_rows = {row["ac"]: row for row in edca.rows()}
        dcf_rows = {row["ac"]: row for row in dcf.rows()}
        self.assertLess(edca_rows["VO"]["mean_ms"], 5.0)
        self.assertLess(edca_rows["VI"]["mean_ms"], 8.0)
        self.assertGreater(dcf_rows["VO"]["mean_ms"], edca_rows["VO"]["mean_ms"])
        self.assertGreater(dcf_rows["VO"]["deadline_observed_failure_pct"],
                           edca_rows["VO"]["deadline_observed_failure_pct"])
        self.assertGreater(edca_rows["BE"]["throughput_mbps"],
                           edca_rows["BK"]["throughput_mbps"])

    def test_external_busy_calendar_matches_target(self):
        simulator = run(mode="EDCA", duration=10.0, stations=10)
        fraction = simulator.external_busy_us / simulator.config.duration_us
        self.assertTrue(0.24 < fraction < 0.36, fraction)

    def test_admission_checks_each_frame_before_neighbour_busy_period(self):
        for mode in ("DCF", "EDCA"):
            with self.subTest(mode=mode):
                sim = MultiACSimulator(MultiACConfig(mode=mode, duration_s=0.001))
                sim.external_events = [(200.0, True), (400.0, False)]
                sim.next_arrival = {"VO": 1000.0, "VI": 1000.0}
                for node in sim.nodes:
                    for queue in node.queues.values():
                        queue.packets.clear()
                        queue.backoff = 0
                        queue.ifs_remaining = 0
                short = sim._queue_for(sim.nodes[0], "VO")
                long = sim._queue_for(sim.nodes[4], "BE")
                short.packets.append(Packet(0, "VO", 100))
                long.packets.append(Packet(0, "BE", 1500))
                short.ifs_remaining = 50
                sim._start_ready_transmissions(0)
                self.assertFalse(sim.busy)
                self.assertEqual(sim._next_event(0), 50)
                sim._advance(50)
                sim._start_ready_transmissions(50)
                self.assertEqual(sim.busy[0].contenders[0][0].station_id, 0)
                self.assertEqual(len(sim.busy[0].contenders), 1)
                self.assertLessEqual(sim.busy[0].end_us, 200)

    def test_observed_deadlines_include_only_overdue_unfinished_frames(self):
        sim = MultiACSimulator(MultiACConfig(duration_s=0.025))
        sim.external_events = [(0, True), (25_000, False)]
        sim.run()
        by_ac = {row["ac"]: row for row in sim.rows()}
        self.assertEqual(by_ac["VO"]["unfinished"], 6)
        self.assertEqual(by_ac["VO"]["deadline_observed"], 4)
        self.assertEqual(by_ac["VO"]["deadline_observed_failure_pct"], 100)
        self.assertIsNone(by_ac["VO"]["deadline_failure_pct"])
        self.assertIsNone(by_ac["VI"]["deadline_observed_failure_pct"])

    def test_internal_collision_with_shared_station(self):
        assignments = {
            "VO": (0, 1), "VI": (2, 3),
            "BE": (0, 4, 5, 6),   # station 0 carries VO and BE: internal contention
            "BK": (7, 8, 9),
        }
        simulator = run(mode="EDCA", duration=2.0, seed=42,
                        assignments=assignments)
        internal = sum(row["internal_collisions"] for row in simulator.rows())
        self.assertGreater(internal, 0)
        total = sum(row["success"] for row in simulator.rows())
        self.assertEqual(simulator.attempts, total + simulator.collisions)

    def test_invalid_configs(self):
        with self.assertRaises(ValueError):
            MultiACConfig(stations=5)
        with self.assertRaises(ValueError):
            MultiACConfig(mode="NPCA")
        with self.assertRaises(ValueError):
            MultiACConfig(primary_busy_fraction=1.0)
        with self.assertRaises(ValueError):
            ACParams("VO", 2, 15, 7, 100)
        with self.assertRaises(ValueError):
            MultiACConfig(assignments={"VO": (99,), "VI": (1,), "BE": (2,),
                                       "BK": (3,)})


class DefaultParameterTests(unittest.TestCase):
    def test_80211e_defaults(self):
        self.assertEqual((DEFAULT_ACS["VO"].aifsn, DEFAULT_ACS["VO"].cw_min,
                          DEFAULT_ACS["VO"].cw_max), (2, 3, 7))
        self.assertEqual((DEFAULT_ACS["VI"].aifsn, DEFAULT_ACS["VI"].cw_min,
                          DEFAULT_ACS["VI"].cw_max), (2, 7, 15))
        self.assertEqual((DEFAULT_ACS["BE"].aifsn, DEFAULT_ACS["BE"].cw_min,
                          DEFAULT_ACS["BE"].cw_max), (3, 15, 1023))
        self.assertEqual((DEFAULT_ACS["BK"].aifsn, DEFAULT_ACS["BK"].cw_min,
                          DEFAULT_ACS["BK"].cw_max), (7, 15, 1023))

    def test_station_assignment_split(self):
        config = MultiACConfig(stations=10)
        self.assertEqual(config.ac_stations("VO"), [0, 1])
        self.assertEqual(config.ac_stations("VI"), [2, 3])
        self.assertEqual(config.ac_stations("BE"), [4, 5, 6])
        self.assertEqual(config.ac_stations("BK"), [7, 8, 9])


if __name__ == "__main__":
    unittest.main()
