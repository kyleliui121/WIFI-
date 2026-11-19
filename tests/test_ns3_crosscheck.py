"""Regression coverage for comparing a matched ns-3/SimPy matrix."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.compare_ns3 import ACS, EXPECTED_TID_MASK, MODES, PAYLOAD_BYTES, compare


class MatchedCrosscheckTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(prefix="wifi-crosscheck-test-")
        self.addCleanup(scratch.cleanup)
        folder = Path(scratch.name)
        self.simpy, self.ns3 = folder / "simpy.csv", folder / "ns3.csv"
        self.sim_rows, self.ns3_rows = [], []
        for mode in MODES:
            for ac in ACS:
                row = {
                    "stations": 10, "duration_s": 1.0, "seed": 42,
                    "mode": mode, "ac": ac, "attempts": 3, "external_busy_fraction": 0,
                    "throughput_mbps": 2 * PAYLOAD_BYTES[ac] * 8 / 1e6,
                    "mean_ms": 1.0, "p99_ms": 2.0, "p999_ms": 2.5,
                }
                self.sim_rows.append({**row, "success": 2})
                self.ns3_rows.append({
                    **row, "frames": 2, "qos_matched_attempts": 3 if mode == "EDCA" else 0,
                    "tid_mask": EXPECTED_TID_MASK[ac] if mode == "EDCA" else 0,
                })
        self.write(self.simpy, self.sim_rows)

    def write(self, path, rows):
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_matched_rows_retain_the_observed_tids(self):
        self.write(self.ns3, self.ns3_rows)
        rows, totals = compare(self.simpy, self.ns3)
        self.assertEqual(len(rows), 8)
        self.assertEqual(len(totals), 2)
        self.assertEqual({r["ac"]: r["ns3_tid"] for r in rows if r["mode"] == "EDCA"},
                         {"VO": "6", "VI": "4", "BE": "0", "BK": "1"})
        self.assertTrue(all(r["diff_pct"] == 0 for r in totals))

    def test_mismatched_seed_is_rejected(self):
        for row in self.ns3_rows:
            row["seed"] = 43
        self.write(self.ns3, self.ns3_rows)
        with self.assertRaisesRegex(ValueError, "same complete"):
            compare(self.simpy, self.ns3)

    def test_misclassified_qos_frames_are_rejected(self):
        sample = next(r for r in self.ns3_rows if r["mode"] == "EDCA" and r["ac"] == "VO")
        sample["tid_mask"] = EXPECTED_TID_MASK["BE"]
        self.write(self.ns3, self.ns3_rows)
        with self.assertRaisesRegex(ValueError, "on-air QoS"):
            compare(self.simpy, self.ns3)


if __name__ == "__main__":
    unittest.main()
