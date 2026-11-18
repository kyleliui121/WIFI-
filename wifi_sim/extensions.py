"""Paired experiments for frame errors and hidden terminals."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from math import isfinite
from pathlib import Path
from statistics import mean, stdev

import matplotlib
import simpy

from .experiments import _write_csv
from .priority import MACConfig, MACSimulator, MODES

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

N_VALUES = (10, 20, 30)
DEFAULT_RATES = (0.01, 0.025, 0.05)
DEFAULT_OUTPUT = Path("results/extensions")
METRICS = (
    "high_mean_ms", "high_p99_ms", "high_p999_ms", "high_success_pct",
    "high_success_late_pct", "high_drop_pct", "high_unfinished_pct",
    "deadline_observed_failure_pct", "low_throughput_mbps",
    "collision_pct", "frame_errors", "frame_error_pct",
    "frame_error_given_no_collision_pct", "hidden_collision_events",
)


def run_scenario(scenario: str, duration: float, seeds: tuple[int, ...],
                 rate: float = 0.0, hidden: bool = False) -> list[dict]:
    rows = []
    for n in N_VALUES:
        for mode in MODES:
            for seed in seeds:
                config = MACConfig(stations=n, mode=mode, seed=seed, duration_s=duration,
                                   frame_error_rate=rate, hidden_terminals=hidden)
                report = MACSimulator(config).run()
                clean_attempts = report.attempts - report.collisions
                rows.append({
                    **report.as_dict(),
                    "scenario": scenario,
                    "frame_error_rate": rate,
                    "hidden_terminals": hidden,
                    "high_success_pct": (100 * report.high_success / report.high_generated
                                         if report.high_generated else None),
                    "frame_errors": report.frame_errors,
                    "frame_error_pct": (100 * report.frame_errors / report.attempts
                                        if report.attempts else None),
                    "frame_error_given_no_collision_pct": (100 * report.frame_errors / clean_attempts
                                                          if clean_attempts else None),
                    "hidden_collision_events": report.hidden_collision_events,
                    "high_dropped_by_error": report.high_dropped_by_error,
                    "high_dropped_by_collision": report.high_dropped_by_collision,
                })
            print(f"{scenario} rate={rate:g}: N={n}, {mode}, {len(seeds)} seed(s)", flush=True)
    return rows


def aggregate(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    buckets = defaultdict(list)
    for row in rows:
        buckets[tuple(row[k] for k in keys)].append(row)
    output = []
    for key, group in sorted(buckets.items()):
        record = dict(zip(keys, key))
        for metric in METRICS:
            values = [row[metric] for row in group if row[metric] is not None]
            record[f"{metric}_mean"] = mean(values) if values else None
            record[f"{metric}_std"] = stdev(values) if len(values) > 1 else None
        output.append(record)
    return output


def _save(fig, folder: Path, name: str) -> None:
    fig.savefig(folder / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(folder / f"{name}.png", bbox_inches="tight", dpi=300)
    plt.close(fig)


def plot_frame_error(folder: Path, rows: list[dict]) -> None:
    lookup = {(r["stations"], r["mode"], r["frame_error_rate"]): r for r in rows}
    rates = sorted({r["frame_error_rate"] for r in rows})
    for metric, name, ylabel in (
        ("low_throughput_mbps", "07_ext_frame_error_throughput", "Low-priority throughput (Mbit/s)"),
        ("deadline_observed_failure_pct", "08_ext_frame_error_miss", "Observed deadline failures (%)"),
    ):
        fig, axes = plt.subplots(1, 3, figsize=(11.4, 3.8), sharey=True)
        for axis, n in zip(axes, N_VALUES):
            for mode, marker in zip(MODES, ("s", "o", "^", "D")):
                values = [lookup[n, mode, rate][f"{metric}_mean"] for rate in rates]
                axis.plot([100 * rate for rate in rates],
                          [float("nan") if value is None else value for value in values],
                          marker=marker, label=mode)
            axis.set(xlabel="Data-frame error probability (%)", title=f"N={n}")
            axis.grid(alpha=0.25)
        axes[0].set_ylabel(ylabel)
        axes[-1].legend()
        fig.suptitle(f"{ylabel} by frame error probability")
        _save(fig, folder, name)


def plot_hidden(folder: Path, rows: list[dict]) -> None:
    lookup = {(r["stations"], r["mode"], r["scenario"]): r for r in rows}
    for metric, name, ylabel in (
        ("high_p999_ms", "09_ext_hidden_p999", "Successful-frame p99.9 (ms)"),
        ("low_throughput_mbps", "10_ext_hidden_throughput", "Low-priority throughput (Mbit/s)"),
    ):
        fig, axes = plt.subplots(1, 3, figsize=(11.4, 3.8), sharey=True)
        for axis, n in zip(axes, N_VALUES):
            for scenario, offset, label in (
                ("baseline", -0.19, "All stations audible"),
                ("hidden", 0.19, "Hidden terminals"),
            ):
                cases = [lookup[n, mode, scenario] for mode in MODES]
                values = [r[f"{metric}_mean"] for r in cases]
                positions = [i + offset for i in range(len(MODES))]
                bars = axis.bar(positions, [float("nan") if value is None else value for value in values],
                                width=0.38, label=label)
                if metric == "high_p999_ms" and scenario == "hidden":
                    for bar, value, case in zip(bars, values, cases):
                        if value is not None:
                            axis.annotate(f'{case["high_success_pct_mean"]:.0f}% ok',
                                          (bar.get_x() + bar.get_width() / 2, value),
                                          textcoords="offset points", xytext=(0, 3),
                                          ha="center", fontsize=8)
            axis.set_xticks(range(len(MODES)), MODES)
            axis.set_title(f"N={n}")
            axis.grid(axis="y", alpha=0.25)
            if metric == "high_p999_ms":
                axis.set_yscale("log")
        axes[0].set_ylabel(ylabel)
        axes[-1].legend(fontsize=8)
        fig.suptitle("Two mutually hidden station groups")
        _save(fig, folder, name)


def run_extensions(folder: Path, duration: float, seeds: tuple[int, ...],
                   rates: tuple[float, ...], make_plots: bool = True) -> None:
    if not isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and strictly positive")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be non-empty and unique")
    if not rates or len(set(rates)) != len(rates) or any(not 0 < rate < 1 for rate in rates):
        raise ValueError("frame error rates must be unique and lie in (0, 1)")

    metadata_path = folder / "ext_metadata.json"
    metadata_path.unlink(missing_ok=True)
    baseline = run_scenario("baseline", duration, seeds)
    _write_csv(folder / "ext_baseline.csv", baseline)
    frame_rows = []
    for rate in rates:
        frame_rows.extend(run_scenario("frame_error", duration, seeds, rate=rate))
        _write_csv(folder / "ext_frame_error.csv", frame_rows)
    hidden = run_scenario("hidden", duration, seeds, hidden=True)
    _write_csv(folder / "ext_hidden.csv", hidden)

    by_rate = aggregate(baseline + frame_rows, ("frame_error_rate", "stations", "mode"))
    by_visibility = aggregate(baseline + hidden, ("scenario", "stations", "mode"))
    _write_csv(folder / "ext_aggregated.csv", by_rate)
    _write_csv(folder / "ext_hidden_aggregated.csv", by_visibility)
    if make_plots:
        plot_frame_error(folder, by_rate)
        plot_hidden(folder, by_visibility)

    metadata = {
        "duration_s": duration, "seeds": seeds, "A_class_N": N_VALUES,
        "frame_error_rates": rates, "hidden_group_rule": "station_id % 2",
        "runs_baseline": len(baseline), "runs_frame_error": len(frame_rows),
        "runs_hidden": len(hidden), "simpy_version": simpy.__version__,
        "source_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()
                                .replace(b"\r\n", b"\n")).hexdigest()
            for name in ("priority.py", "extensions.py", "dcf.py")
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Extension results written to {folder}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--rates", type=float, nargs="+", default=DEFAULT_RATES)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    run_extensions(args.out, args.duration, tuple(args.seeds), tuple(args.rates), not args.no_plots)


if __name__ == "__main__":
    main()
