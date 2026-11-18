"""Re-run the four modes at N=10, seed=42 against the official summary.

Usage:  python tools/verify_repro.py
Needs only simpy (no scipy / matplotlib).
"""
import csv
import sys
from math import isclose
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wifi_sim.priority import MACConfig, MACSimulator, MODES  # noqa: E402

KEYS = ("high_mean_ms", "high_p99_ms", "high_p999_ms", "high_success_late_pct",
        "high_drop_pct", "deadline_failure_pct", "deadline_observed_failure_pct",
        "low_throughput_mbps", "attempts", "high_success", "collision_pct")


def main() -> int:
    with (ROOT / "data" / "official_summary.csv").open(encoding="utf-8", newline="") as source:
        official = {row["mode"]: row for row in csv.DictReader(source)
                    if int(row["stations"]) == 10 and int(row["seed"]) == 42}

    ok = True
    for mode in MODES:
        ref = official[mode]
        config = MACConfig(stations=10, mode=mode, seed=42, duration_s=float(ref["duration_s"]))
        got = MACSimulator(config).run().as_dict()
        diffs = []
        for key in KEYS:
            expected = float(ref[key]) if ref[key] else None
            actual = got[key]
            if actual is None or expected is None:
                match = actual is expected
            else:
                match = isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
            if not match:
                diffs.append(f"{key}: got {actual} vs csv {expected}")
        ok &= not diffs
        print(f"{mode:7} " + ("MATCH" if not diffs else "DIFF -> " + ", ".join(diffs)))

    print("VERDICT:", "reproducible" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
