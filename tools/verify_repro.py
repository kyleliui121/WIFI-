"""Re-run the baseline against the official summary.

Usage:  python tools/verify_repro.py
        python tools/verify_repro.py --all
Needs only simpy (no scipy / matplotlib).
"""
import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="check all 36 official cases")
    args = parser.parse_args()
    with (ROOT / "data" / "official_summary.csv").open(encoding="utf-8", newline="") as source:
        official = {(int(row["stations"]), row["mode"], int(row["seed"])): row
                    for row in csv.DictReader(source)}

    stations = (10, 20, 30) if args.all else (10,)
    seeds = (42, 43, 44) if args.all else (42,)
    ok = True
    cases = [(n, mode, seed) for n in stations for mode in MODES for seed in seeds]
    for n, mode, seed in cases:
        ref = official[n, mode, seed]
        config = MACConfig(stations=n, mode=mode, seed=seed, duration_s=float(ref["duration_s"]))
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
        print(f"N={n} {mode:7} seed={seed} "
              + ("MATCH" if not diffs else "DIFF -> " + ", ".join(diffs)))

    print("VERDICT:", "reproducible" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
