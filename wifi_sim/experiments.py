"""Repeatable A-class experiment matrix and Bianchi validation."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path
from statistics import mean, stdev

import simpy

from .dcf import DCFConfig, DCFSimulator
from .plotting import plot_all
from .priority import MACConfig, MACSimulator, MODES
from .theory import collision_probability


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        if not rows:
            return
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_experiments(folder: Path, duration: float = 10.0,
                    seeds: tuple[int, ...] = (42, 43, 44),
                    bianchi_step: int = 5, make_plots: bool = True) -> None:
    """Run N=10,20,30; 4 schemes; >=3 independent random seeds.

    The Bianchi sweep uses N=5, 5+step, ..., 50 under all-saturated DCF.
    Full deliverable defaults: 10 seconds each, 3 seeds each.
    """
    if duration <= 0 or not seeds:
        raise ValueError("duration and seeds must be positive/nonempty")
    if bianchi_step <= 0 or 45 % bianchi_step:
        raise ValueError("bianchi_step must divide 45 and be positive")
    folder.mkdir(parents=True, exist_ok=True)
    summary, delays, theory_rows, packets, dcf_rows, configs = [], [], [], [], [], []
    for n in range(5, 51, bianchi_step):
        simulated = []
        for seed in seeds:
            config = DCFConfig(stations=n, duration_s=duration, seed=seed)
            result = DCFSimulator(config).run()
            simulated.append(result.collision_probability)
            dcf_rows.append(result.as_dict() | {'config': json.dumps(asdict(config), sort_keys=True)})
        theory_rows.append({
            "stations": n, "bianchi_classic": collision_probability(n),
            "bianchi_finite": collision_probability(n, retry_limit=7),
            "sim_mean": mean(simulated),
            "sim_std": stdev(simulated) if len(simulated) > 1 else 0.0,
        })
        _write_csv(folder / "bianchi.csv", theory_rows)
        print(f"Bianchi: N={n}", flush=True)

    for n in (10, 20, 30):
        for mode in MODES:
            for seed in seeds:
                report = MACSimulator(MACConfig(stations=n, mode=mode,
                    seed=seed, duration_s=duration)).run()
                summary.append(report.as_dict())
                configs.append(asdict(report.config))
                packets.extend({'stations': n, 'mode': mode, 'seed': seed, **p}
                               for p in report.high_packets)
                delays.extend({"stations": n, "mode": mode,
                               "seed": seed, "delay_ms": delay / 1000}
                              for delay in report.high_delays_us)
                _write_csv(folder / "summary.csv", summary)
                _write_csv(folder / "high_delays.csv", delays)
                print(f"A class: N={n}, {mode}, seed={seed}", flush=True)
    _write_csv(folder / "bianchi.csv", theory_rows)
    _write_csv(folder / "summary.csv", summary)
    _write_csv(folder / "high_delays.csv", delays)
    _write_csv(folder / "high_packets.csv", packets)
    _write_csv(folder / "dcf_runs.csv", dcf_rows)
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    source_dirty = bool(subprocess.check_output(
        ['git', 'status', '--porcelain', '--untracked-files=no'], text=True).strip())
    metadata = {"duration_s": duration, "seeds": seeds,
                "A_class_N": [10, 20, 30], "high_stations": 2,
                "external_busy_target": 0.30,
                "model": "SimPy simplified independent-channel access, see docs/methodology.md",
                "experiment_runs": len(summary), "dcf_validation_runs": len(seeds) * len(theory_rows),
                "simpy_version": getattr(simpy, "__version__", "UNVERIFIED_TEST_SCHEDULER"),
                "schema_version": 3, "source_commit": source_commit,
                "source_files_sha256": {str(p).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted(Path('wifi_sim').glob('*.py'))},
                "source_dirty": source_dirty,
                "started_from": "python -m wifi_sim.experiments",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(),
                "dependencies": {p: version(p) for p in ('simpy', 'scipy', 'numpy', 'matplotlib')},
                "mac_configs": configs,
                "dcf_configs": [json.loads(r['config']) for r in dcf_rows]}
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if make_plots:
        plot_all(folder)
    metadata['sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'metadata.json'}
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete A-class Wi-Fi MAC experiments")
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--bianchi-step", type=int, default=5)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    run_experiments(args.out, args.duration, tuple(args.seeds),
                    args.bianchi_step, not args.no_plots)


if __name__ == "__main__":
    main()
