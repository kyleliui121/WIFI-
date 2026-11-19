"""Mechanism check: why AC_BK is squeezed out in the four-AC EDCA runs.

Sweeps the AC_BK AIFSN (3, 5, 7) while keeping every other 802.11e parameter
unchanged.  With AIFSN=3 the BK channel-access defer time equals BE's AIFS, so the
BK share should recover; at AIFSN=7 (the standard value) the 79 us defer time
cannot be satisfied between back-to-back BE frames and BK is starved.

Usage:
    python -m tools.aifs_sensitivity --out results/ext34
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from pathlib import Path
from statistics import mean

from wifi_sim.multiac import DEFAULT_ACS, MultiACConfig, MultiACSimulator

N_VALUES = (10, 30)
SEEDS = (42, 43, 44)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("results/ext34"))
    parser.add_argument("--duration", type=float, default=10.0)
    args = parser.parse_args()

    rows = []
    for aifsn in (3, 5, 7):
        acs = dict(DEFAULT_ACS)
        acs["BK"] = replace(acs["BK"], aifsn=aifsn)
        for n in N_VALUES:
            for seed in SEEDS:
                simulator = MultiACSimulator(MultiACConfig(
                    stations=n, mode="EDCA", seed=seed,
                    duration_s=args.duration, acs=acs))
                simulator.run()
                per_ac = {row["ac"]: row for row in simulator.rows()}
                rows.append({
                    "bk_aifsn": aifsn,
                    "stations": n,
                    "seed": seed,
                    "bk_throughput_mbps": per_ac["BK"]["throughput_mbps"],
                    "be_throughput_mbps": per_ac["BE"]["throughput_mbps"],
                    "bk_mean_ms": per_ac["BK"]["mean_ms"],
                    "bk_p99_ms": per_ac["BK"]["p99_ms"],
                    "bk_share_pct": 100.0 * per_ac["BK"]["throughput_mbps"]
                                    / max(1e-9, per_ac["BK"]["throughput_mbps"]
                                          + per_ac["BE"]["throughput_mbps"]),
                })
                print(f"AIFSN={aifsn} N={n} seed={seed}", flush=True)

    output = args.out / "ext4ac_bk_aifs_sensitivity.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print("\nmeans:")
    for aifsn in (3, 5, 7):
        for n in N_VALUES:
            cells = [row for row in rows
                     if row["bk_aifsn"] == aifsn and row["stations"] == n]
            print(f"AIFSN={aifsn} N={n}: BK {mean(r['bk_throughput_mbps'] for r in cells):.2f} "
                  f"Mbit/s, BE {mean(r['be_throughput_mbps'] for r in cells):.2f} Mbit/s, "
                  f"BK share {mean(r['bk_share_pct'] for r in cells):.1f}%")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
