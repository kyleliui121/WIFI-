"""Publication-readable diagrams from reproducible experiment CSVs."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .priority import MODES

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.grid": True, "grid.alpha": 0.24,
                     "savefig.bbox": "tight"})


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _save(fig, folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / f"{name}.pdf")
    fig.savefig(folder / f"{name}.png", dpi=300)
    plt.close(fig)


def plot_bianchi(folder: Path) -> None:
    rows = _rows(folder / "bianchi.csv")
    x = np.array([int(r["stations"]) for r in rows])
    fig, ax = plt.subplots(figsize=(6.7, 4.1))
    ax.plot(x, [float(r["bianchi_classic"]) for r in rows], label="Bianchi (infinite retry)", lw=2)
    ax.plot(x, [float(r["bianchi_finite"]) for r in rows], label="Finite-retry correction", lw=1.6, ls="--")
    ax.errorbar(x, [float(r["sim_mean"]) for r in rows],
                yerr=[float(r["sim_std"]) for r in rows],
                fmt="o", ms=3, capsize=2, label="DCF simulation (3 seeds)")
    ax.set(xlabel="Saturated stations (N)", ylabel="Collision probability", title="DCF validation vs Bianchi model")
    ax.legend()
    _save(fig, folder, "01_dcf_bianchi")


def plot_ccdf(folder: Path, stations: int = 30) -> None:
    rows = _rows(folder / "high_delays.csv")
    fig, ax = plt.subplots(figsize=(6.7, 4.1))
    for mode in MODES:
        data = sorted(float(r["delay_ms"]) for r in rows
                      if int(r["stations"]) == stations and r["mode"] == mode)
        if not data:
            continue
        x = np.array(data)
        y = (len(x) - np.arange(len(x))) / len(x)  # P(delay >= x)
        ax.semilogy(x, y, label=f"{mode} (n={len(x)})", lw=1.8)
    ax.axvline(10, ls=":", lw=1.2, color="black", label="10 ms deadline")
    ax.set(xlabel="Successful high-priority access delay (ms)",
           ylabel="CCDF: P(delay >= x)",
           title=f"High-priority delay tail (N={stations}, three seeds)")
    # DCF has multi-second backlog while EDCA delays are ~milliseconds.
    # A logarithmic X axis makes all four CCDFs readable in one figure.
    ax.set_xscale("log")
    ax.set_ylim(bottom=1e-4, top=1)
    ax.legend()
    _save(fig, folder, "02_high_delay_ccdf")


def plot_vs_n(folder: Path, metric: str, name: str, title: str, ylabel: str) -> None:
    rows = _rows(folder / "summary.csv")
    fig, ax = plt.subplots(figsize=(6.7, 4.1))
    for mode in MODES:
        grouped = sorted(set(int(r["stations"]) for r in rows if r["mode"] == mode))
        means, errors = [], []
        for n in grouped:
            values = [float(r[metric]) for r in rows if r["mode"] == mode and
                      int(r["stations"]) == n and r[metric] != ""]
            means.append(float(np.mean(values)) if values else np.nan)
            errors.append(float(np.std(values, ddof=1)) if len(values) > 1 else 0.0)
        ax.errorbar(grouped, means, yerr=errors, label=mode, marker="o", capsize=3)
    ax.set(xlabel="Total stations (N)", ylabel=ylabel, title=title)
    ax.set_xticks([10, 20, 30])
    if metric == "high_p999_ms":
        ax.set_yscale("log")  # otherwise DCF backlog hides EDCA and NPCA.
    ax.legend()
    _save(fig, folder, name)


def plot_all(folder: Path) -> None:
    plot_bianchi(folder)
    plot_ccdf(folder, stations=30)
    plot_vs_n(folder, "high_p999_ms", "03_high_p999_vs_n", "High-priority p99.9 delay vs N", "p99.9 access delay (ms)")
    plot_vs_n(folder, "low_throughput_mbps", "04_low_throughput_vs_n", "Low-priority aggregate throughput vs N", "Throughput (Mbit/s)")
