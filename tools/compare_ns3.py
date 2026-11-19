"""Compare matched clean-channel runs and verify ns-3's observed AC mapping."""
from __future__ import annotations

import argparse
import csv
from math import isclose, isfinite
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ACS = ("VO", "VI", "BE", "BK")
MODES = ("DCF", "EDCA")
EXPECTED_TID_MASK = {"VO": 1 << 6, "VI": 1 << 4, "BE": 1 << 0, "BK": 1 << 1}
PAYLOAD_BYTES = {"VO": 100, "VI": 1000, "BE": 1500, "BK": 500}


def read_cases(path: Path, *, ns3: bool) -> dict:
    cases = {}
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            n, duration, seed = int(row["stations"]), float(row["duration_s"]), int(row["seed"])
            mode, ac = row["mode"], row["ac"]
            key = (n, duration, seed, mode, ac)
            if (key in cases or mode not in MODES or ac not in ACS or n < 6 or seed <= 0
                    or not isfinite(duration) or duration <= 0
                    or float(row["external_busy_fraction"]) != 0):
                raise ValueError(f"{path}: invalid or duplicate clean-channel case {key}")
            attempts = int(row["attempts"])
            delivered = int(row["frames"] if ns3 else row["success"])
            throughput = delivered * PAYLOAD_BYTES[ac] * 8 / duration / 1e6
            if not (0 <= delivered <= attempts and isclose(float(row["throughput_mbps"]), throughput,
                                                           rel_tol=1e-10, abs_tol=1e-12)):
                raise ValueError(f"{path}: inconsistent throughput or attempt count for {key}")
            if ns3:
                matched, mask = int(row["qos_matched_attempts"]), int(row["tid_mask"])
                expected = (attempts, EXPECTED_TID_MASK[ac]) if mode == "EDCA" else (0, 0)
                if attempts == 0 or (matched, mask) != expected:
                    raise ValueError(f"{path}: on-air QoS did not match {mode}/{ac} for {key[:3]}")
            cases[key] = row
    if not cases:
        raise ValueError(f"{path}: expected clean-channel results")
    return cases


def compare(simpy_path: Path, ns3_path: Path) -> tuple[list[dict], list[dict]]:
    simpy = read_cases(simpy_path, ns3=False)
    ns3 = read_cases(ns3_path, ns3=True)
    conditions = {key[:3] for key in simpy}
    expected = {(*condition, mode, ac) for condition in conditions for mode in MODES for ac in ACS}
    if simpy.keys() != expected or ns3.keys() != expected:
        raise ValueError("SimPy and ns-3 require the same complete station, duration, seed, mode and AC matrix")
    rows, totals = [], []
    for n, duration, seed in sorted(conditions):
        identity = {"stations": n, "duration_s": duration, "seed": seed}
        for mode in MODES:
            sim_total, ns3_total = 0.0, 0.0
            for ac in ACS:
                key = (n, duration, seed, mode, ac)
                s, r = simpy[key], ns3[key]
                sim_mbps, ns3_mbps = float(s["throughput_mbps"]), float(r["throughput_mbps"])
                sim_total += sim_mbps
                ns3_total += ns3_mbps
                rows.append({
                    **identity, "mode": mode, "ac": ac,
                    "simpy_throughput_mbps": sim_mbps, "ns3_throughput_mbps": ns3_mbps,
                    "throughput_diff_pct": ((ns3_mbps / sim_mbps - 1) * 100 if sim_mbps else None),
                    "simpy_mean_ms": s["mean_ms"], "ns3_mean_ms": r["mean_ms"],
                    "simpy_p99_ms": s["p99_ms"], "ns3_p99_ms": r["p99_ms"],
                    "simpy_p999_ms": s["p999_ms"], "ns3_p999_ms": r["p999_ms"],
                    "ns3_data_attempts": r["attempts"], "ns3_qos_matched_attempts": r["qos_matched_attempts"],
                    "ns3_tid": str(int(r["tid_mask"]).bit_length() - 1) if mode == "EDCA" else "",
                })
            totals.append({
                **identity, "mode": mode, "simpy_total_mbps": sim_total, "ns3_total_mbps": ns3_total,
                "diff_pct": (100 * (ns3_total / sim_total - 1) if sim_total else None),
            })
    return rows, totals


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot(folder: Path, rows: list[dict]) -> None:
    conditions = sorted({(r["stations"], r["duration_s"], r["seed"]) for r in rows})
    lookup = {(r["stations"], r["duration_s"], r["seed"], r["mode"], r["ac"]): r for r in rows}
    x = np.arange(len(ACS))
    for n, duration, seed in conditions:
        suffix = "" if len(conditions) == 1 else f"_n{n}_{duration:g}s_seed{seed}"
        for metric, filename, ylabel in (
            ("throughput_mbps", "15_ext_ns3_throughput", "Delivered throughput (Mbit/s)"),
            ("mean_ms", "16_ext_ns3_delay", "Mean successful-frame delay (ms)"),
        ):
            fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8), sharey=True)
            for axis, mode in zip(axes, MODES):
                cells = [lookup[n, duration, seed, mode, ac] for ac in ACS]
                for engine, label, offset in (("simpy", "SimPy", -0.19), ("ns3", "ns-3", 0.19)):
                    values = [float(r[f"{engine}_{metric}"]) if r[f"{engine}_{metric}"] != "" else np.nan
                              for r in cells]
                    axis.bar(x + offset, values, width=0.38, label=label)
                axis.set_xticks(x, ACS)
                if metric == "mean_ms":
                    axis.set_yscale("log")
                axis.set_title(mode)
                axis.grid(axis="y", alpha=0.25)
            axes[0].set_ylabel(ylabel)
            axes[1].legend()
            fig.suptitle(f"Clean channel | N={n} | {duration:g} s | seed {seed}")
            for extension in ("png", "pdf"):
                fig.savefig(folder / f"{filename}{suffix}.{extension}", dpi=300, bbox_inches="tight")
            plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("results/ext34"))
    parser.add_argument("--ns3-csv", type=Path, help="default: ns3_crosscheck.csv in the results directory")
    args = parser.parse_args()
    folder = args.results
    try:
        rows, totals = compare(folder / "ns3_simpy_crosscheck.csv",
                               args.ns3_csv or folder / "ns3_crosscheck.csv")
        write(folder / "ext_ns3_comparison.csv", rows)
        write(folder / "ext_ns3_totals.csv", totals)
        plot(folder, rows)
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(1, f"Cross-check rejected: {exc}\n")
    print(f"Compared {len(rows)} matched AC rows in {folder}")


if __name__ == "__main__":
    main()
