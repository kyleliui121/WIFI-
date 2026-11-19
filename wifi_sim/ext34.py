"""Extension 3 experiments: four access categories (VO/VI/BE/BK).

Runs the AC_VO / AC_VI / AC_BE / AC_BK model of :mod:`wifi_sim.multiac`
through the same N x scheme x seed matrix used by the mandatory experiment, plus
a clean-channel subset that is later compared against the ns-3 EDCA scenario
(extension 4).

Usage:
    python -m wifi_sim.ext34 --out results --duration 10 --seeds 42 43 44
    python -m wifi_sim.ext34 --out results --crosscheck-only

Outputs (all under ``--out``):
    ext4ac_runs.csv         one row per scheme x N x seed x AC
    ext4ac_summary.csv      mean +/- sample std across seeds
    ext4ac_metadata.json    matrix, traffic contract, model notes
    ns3_simpy_crosscheck.csv clean-channel SimPy subset for the ns-3 check
    11..15_ext4ac_*.png/pdf extension figures
"""
from __future__ import annotations

import argparse
import hashlib
import json
from math import isfinite
from pathlib import Path
from statistics import mean, stdev

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .multiac import AC_ORDER, MODES, MultiACConfig, MultiACSimulator  # noqa: E402
from .experiments import _write_csv  # noqa: E402

N_VALUES = (10, 20, 30)
METRICS = ("throughput_mbps", "mean_ms", "p99_ms", "p999_ms", "attempts",
           "deadline_observed_failure_pct", "deadline_failure_pct", "success_late_pct",
           "drop_pct", "unfinished_pct", "collision_pct")

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.24,
                     "savefig.bbox": "tight"})


def run_cell(stations: int, mode: str, seed: int, duration: float,
             **overrides) -> list[dict]:
    simulator = MultiACSimulator(MultiACConfig(
        stations=stations, mode=mode, seed=seed, duration_s=duration,
        **overrides))
    simulator.run()
    return simulator.rows()


def run_sweep(folder: Path, duration: float, seeds: tuple[int, ...],
              n_values: tuple[int, ...] = N_VALUES) -> list[dict]:
    rows: list[dict] = []
    for n in n_values:
        for mode in MODES:
            for seed in seeds:
                rows.extend(run_cell(n, mode, seed, duration))
                print(f"four-AC sweep: N={n}, {mode}, seed={seed}", flush=True)
    _write_csv(folder / "ext4ac_runs.csv", rows)
    return rows


def aggregate(rows: list[dict]) -> list[dict]:
    buckets: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["mode"], int(row["stations"]), row["ac"])
        buckets.setdefault(key, []).append(row)
    output = []
    for (mode, stations, ac), group in sorted(buckets.items()):
        record = {"mode": mode, "stations": stations, "ac": ac,
                  "seeds": len(group)}
        for metric in METRICS:
            values = [float(row[metric]) for row in group
                      if row.get(metric) not in ("", None)]
            record[f"{metric}_mean"] = mean(values) if values else None
            record[f"{metric}_std"] = stdev(values) if len(values) > 1 else 0.0
        record["success_mean"] = mean(int(row["success"]) for row in group)
        record["generated_mean"] = mean(int(row["generated"]) for row in group)
        output.append(record)
    return output


def run_crosscheck(folder: Path, duration: float = 10.0,
                   seed: int = 42, stations: int = 10) -> list[dict]:
    """Clean channel (no external neighbour traffic) for the ns-3 comparison."""
    rows = []
    for mode in MODES:
        rows.extend(run_cell(stations, mode, seed, duration,
                             primary_busy_fraction=0.0))
        print(f"clean-channel cross-check: {mode}, N={stations}, seed={seed}",
              flush=True)
    _write_csv(folder / "ns3_simpy_crosscheck.csv", rows)
    return rows


def _save(fig, folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / f"{name}.pdf")
    fig.savefig(folder / f"{name}.png", dpi=300)
    plt.close(fig)


def _series(summary: list[dict], mode: str, n: int, metric: str) -> list[float]:
    values = []
    for ac in AC_ORDER:
        cell = [row for row in summary
                if row["mode"] == mode and row["stations"] == n
                and row["ac"] == ac]
        values.append(cell[0][metric] if cell and cell[0][metric] is not None
                      else np.nan)
    return values


def plot_throughput(folder: Path, summary: list[dict]) -> None:
    ns = sorted({row['stations'] for row in summary})
    fig, grid = plt.subplots(1, len(ns), figsize=(3.7 * len(ns), 3.6), sharey=True, squeeze=False)
    axes = grid[0]
    x = np.arange(len(AC_ORDER))
    for axis, n in zip(axes, ns):
        for offset, mode, color in ((-0.2, "DCF", "#78909c"), (0.2, "EDCA", "#5c6bc0")):
            values = _series(summary, mode, n, "throughput_mbps_mean")
            errs = _series(summary, mode, n, "throughput_mbps_std")
            axis.bar(x + offset, values, width=0.38, yerr=errs, capsize=2,
                     label=mode, color=color)
        axis.set_xticks(x)
        axis.set_xticklabels(AC_ORDER)
        axis.set_title(f"N={n}")
        axis.set_xlabel("Access category")
    axes[0].set_ylabel("Throughput (Mbit/s)")
    axes[0].legend()
    fig.suptitle("Per-AC throughput: DCF vs four-AC EDCA")
    _save(fig, folder, "11_ext4ac_throughput")


def plot_delay(folder: Path, summary: list[dict]) -> None:
    ns = sorted({row['stations'] for row in summary})
    fig, grid = plt.subplots(1, len(ns), figsize=(3.7 * len(ns), 3.6), sharey=True, squeeze=False)
    axes = grid[0]
    x = np.arange(len(AC_ORDER))
    for axis, n in zip(axes, ns):
        for offset, mode, color in ((-0.2, "DCF", "#78909c"), (0.2, "EDCA", "#5c6bc0")):
            values = _series(summary, mode, n, "mean_ms_mean")
            axis.bar(x + offset, values, width=0.38, label=mode, color=color)
        axis.set_xticks(x)
        axis.set_xticklabels(AC_ORDER)
        axis.set_yscale("log")
        axis.set_title(f"N={n}")
    axes[0].set_ylabel("Mean MAC delay (ms, log)")
    axes[0].legend()
    fig.suptitle("Extension 3: mean per-AC delay (VO/VI are deadline traffic)")
    _save(fig, folder, "12_ext4ac_mean_delay")


def plot_tail(folder: Path, summary: list[dict]) -> None:
    ns = sorted({row['stations'] for row in summary})
    shades = ['#90caf9', '#5c6bc0', '#1a237e', '#000000']
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6), sharey=True)
    x = np.arange(len(AC_ORDER))
    for axis, mode in zip(axes, MODES):
        for index, n in enumerate(ns):
            values = _series(summary, mode, n, "p999_ms_mean")
            axis.plot(x, values, marker="o", label=f"N={n}", color=shades[index % len(shades)])
        axis.set_xticks(x)
        axis.set_xticklabels(AC_ORDER)
        axis.set_yscale("log")
        axis.set_title(mode)
        axis.set_xlabel("Access category")
        axis.legend()
    axes[0].set_ylabel("p99.9 MAC delay (ms, log)")
    fig.suptitle("Extension 3: tail delay by access category")
    _save(fig, folder, "13_ext4ac_tail_delay")


def plot_deadline_and_collision(folder: Path, summary: list[dict]) -> None:
    ns = sorted({row["stations"] for row in summary})
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.6))

    width = 0.2
    for index, ac in enumerate(("VO", "VI")):
        for j, mode in enumerate(MODES):
            values = []
            for n in ns:
                cell = [row for row in summary if row["mode"] == mode
                        and row["stations"] == n and row["ac"] == ac]
                values.append(cell[0]["deadline_observed_failure_pct_mean"]
                              if cell and cell[0]["deadline_observed_failure_pct_mean"] is not None
                              else np.nan)
            offset = (index - 0.5) * 2 * width + (j - 0.5) * width
            axes[0].bar(np.arange(len(ns)) + offset, values, width=width,
                        label=f"{ac} {mode}")
    axes[0].set_xticks(np.arange(len(ns)))
    axes[0].set_xticklabels([f"N={n}" for n in ns])
    axes[0].set_ylabel("Observed deadline failure (%)")
    axes[0].set_title("VO/VI deadline failure rate")
    axes[0].legend(fontsize=6, ncol=2)

    for mode, color in (("DCF", "#78909c"), ("EDCA", "#5c6bc0")):
        values = []
        for n in ns:
            rows = [row for row in summary
                    if row["mode"] == mode and row["stations"] == n]
            shares = [row["collision_pct_mean"] for row in rows if row["collision_pct_mean"] is not None]
            values.append(mean(shares) if shares else np.nan)
        axes[1].plot(ns, values, marker="o", label=mode, color=color)
    axes[1].set_xticks(ns)
    axes[1].set_xlabel("N (stations)")
    axes[1].set_ylabel("Collision share of attempts (%)")
    axes[1].set_title("Mean collision share across ACs")
    axes[1].legend()
    fig.suptitle("Extension 3: deadline failures and collision exposure")
    _save(fig, folder, "14_ext4ac_deadline_collision")


def run(folder: Path, duration: float = 10.0,
        seeds: tuple[int, ...] = (42, 43, 44),
        n_values: tuple[int, ...] = N_VALUES,
        crosscheck_only: bool = False, crosscheck_stations: int = 10) -> None:
    if not isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be non-empty and unique")
    if not n_values or len(set(n_values)) != len(n_values):
        raise ValueError("station counts must be non-empty and unique")
    folder.mkdir(parents=True, exist_ok=True)
    if not crosscheck_only:
        rows = run_sweep(folder, duration, seeds, n_values)
        summary = aggregate(rows)
        _write_csv(folder / "ext4ac_summary.csv", summary)
        metadata = {
            "duration_s": duration, "seeds": seeds, "N": list(n_values),
            "modes": list(MODES), "acs": {
                ac: {
                    "aifsn": spec.aifsn, "cw_min": spec.cw_min,
                    "cw_max": spec.cw_max, "frame_bytes": spec.frame_bytes,
                    "traffic": spec.traffic, "period_us": spec.period_us,
                    "deadline_us": spec.deadline_us,
                } for ac, spec in MultiACConfig().acs.items()},
            "station_assignment": {
                "VO": "stations 0..1", "VI": "stations 2..3",
                "BE": "first half of the remaining stations",
                "BK": "second half of the remaining stations"},
            "external_primary_busy": 0.30,
            "runs": len(rows) // len(AC_ORDER), "ac_rows": len(rows),
            "source_sha256": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()
                                    .replace(b"\r\n", b"\n")).hexdigest()
                for name in ("multiac.py", "ext34.py")
            },
            "model": "wifi_sim.multiac, see docs/拓展-34-说明.md",
        }
        (folder / "ext4ac_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        plot_throughput(folder, summary)
        plot_delay(folder, summary)
        plot_tail(folder, summary)
        plot_deadline_and_collision(folder, summary)
    run_crosscheck(folder, duration, seed=seeds[0], stations=crosscheck_stations)
    print(f"extension-3 artefacts written to {folder}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extension 3: four-AC EDCA (VO/VI/BE/BK) experiments")
    parser.add_argument("--out", type=Path, default=Path("results/ext34"))
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--n", type=int, nargs="+", default=list(N_VALUES))
    parser.add_argument("--crosscheck-only", action="store_true")
    parser.add_argument("--crosscheck-stations", type=int, default=10)
    args = parser.parse_args()
    run(args.out, args.duration, tuple(args.seeds), tuple(args.n),
        args.crosscheck_only, args.crosscheck_stations)


if __name__ == "__main__":
    main()
