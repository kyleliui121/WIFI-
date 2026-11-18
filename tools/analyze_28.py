# -*- coding: utf-8 -*-
"""题目 28 专项分析：尾时延改善幅度、低优先级吞吐代价、均值/尾部分位差异。

输入：results/summary.csv、results/high_delays.csv（由 wifi_sim.experiments 生成）
输出：改善幅度和低优先级吞吐 CSV，以及图 05、06 的 PNG/PDF。

用法：
    python -m wifi_sim.experiments --out results --duration 10 --seeds 42 43 44
    python -m tools.analyze_28 --results results --out results/analysis28
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

MODES = ("DCF", "EDCA", "P-EDCA", "NPCA")
QUANTILES = (("p50", 50), ("p90", 90), ("p99", 99), ("p99.9", 99.9))
EXTERNAL_MEAN_MS = 2.0


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def quantile(sorted_values: list[float], q: float) -> float:
    """线性插值分位数（与 numpy 默认一致），q 取百分比。"""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_values[int(pos)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def per_seed_quantiles(delays: list[dict]) -> dict:
    """每个种子单独算分位数，再对种子取均值（与方法论文档口径一致）。"""
    buckets: dict[tuple[int, str, str], list[float]] = defaultdict(list)
    for row in delays:
        buckets[(int(row["stations"]), row["mode"], row["seed"])].append(float(row["delay_ms"]))

    out: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(list))
    for (stations, mode, _seed), values in buckets.items():
        values.sort()
        for name, q in QUANTILES:
            out[(stations, mode)][name].append(quantile(values, q))
        out[(stations, mode)]["mean"].append(mean(values))
    return {key: {k: mean(v) for k, v in d.items()} for key, d in out.items()}


def pct_improve(before: float, after: float) -> float:
    return (before - after) / before * 100.0


def exponential_quantile_ms(q_pct: float, mean_ms: float = EXTERNAL_MEAN_MS) -> float:
    """Exp(mean) 的分位数，用于对照外部忙期残留等待。"""
    return -mean_ms * math.log(1 - q_pct / 100.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="题目 28：NPCA/P-EDCA 收益与代价分析")
    parser.add_argument("--results", type=Path, default=ROOT / "results")
    parser.add_argument("--out", type=Path, help="分析产物目录，默认与输入相同")
    args = parser.parse_args()

    folder: Path = args.results
    output = args.out or folder
    try:
        summary = read_csv(folder / "summary.csv")
        delays = read_csv(folder / "high_delays.csv")
    except FileNotFoundError as exc:
        parser.error(f"缺少输入文件 {exc.filename}，请先运行实验矩阵或解压正式归档")

    def run_key(row):
        return int(row["stations"]), row["mode"], row["seed"]

    runs = {run_key(row) for row in summary}
    seeds = {seed for _, _, seed in runs}
    expected = {(n, mode, seed) for n in (10, 20, 30) for mode in MODES for seed in seeds}
    if not runs or runs != expected or len(runs) != len(summary):
        parser.error("summary.csv 中的站点数 × 方案 × 种子矩阵不完整，或含有重复记录")
    counts = Counter({run_key(row): int(row["high_success"]) for row in summary})
    if Counter(map(run_key, delays)) != counts:
        parser.error("high_delays.csv 的逐次成功帧数与 summary.csv 不一致")
    qmap = per_seed_quantiles(delays)
    missing = [(n, mode) for n in (10, 20, 30) for mode in MODES[1:] if (n, mode) not in qmap]
    if missing:
        parser.error(f"以下组合缺少成功帧，无法计算改善幅度：{missing}")

    print("=" * 92)
    print(f"一、各分位时延（成功高优先级帧，ms；{len(seeds)} 个种子）")
    print("=" * 92)
    header = f"{'N':>3} {'方案':>7} {'均值':>8} {'p50':>8} {'p90':>8} {'p99':>9} {'p99.9':>9}"
    print(header)
    print("-" * len(header))
    for n in (10, 20, 30):
        for mode in MODES:
            q = qmap.get((n, mode))
            if not q:
                continue
            print(f"{n:>3} {mode:>7} {q['mean']:>8.2f} {q['p50']:>8.2f} "
                  f"{q['p90']:>8.2f} {q['p99']:>9.2f} {q['p99.9']:>9.2f}")

    # ---- 与 Exp(2 ms) 理论分位对照 ----
    print("\n" + "=" * 92)
    print("二、外部忙期残留等待的理论分位 vs EDCA 实测尾时延")
    print("=" * 92)
    print(f"  {'分位':>6} {'Exp(mean=2ms)理论(ms)':>22} "
          f"{'EDCA N=10':>11} {'EDCA N=20':>11} {'EDCA N=30':>11}")
    for name, q in QUANTILES:
        theory = exponential_quantile_ms(q)
        vals = [qmap[(n, "EDCA")][name] for n in (10, 20, 30) if (n, "EDCA") in qmap]
        print(f"  {name:>6} {theory:>22.2f} " + " ".join(f"{v:>11.2f}" for v in vals))

    # ---- 改善幅度 ----
    print("\n" + "=" * 92)
    print("三、改善幅度（负值表示变差）")
    print("=" * 92)
    transitions = (("EDCA", "P-EDCA"), ("P-EDCA", "NPCA"), ("EDCA", "NPCA"))
    rows = []
    for n in (10, 20, 30):
        for before, after in transitions:
            qa, qb = qmap[(n, before)], qmap[(n, after)]
            row = {"stations": n, "transition": f"{before}->{after}"}
            for key in ("mean", "p50", "p90", "p99", "p99.9"):
                row[key] = pct_improve(qa[key], qb[key])
            rows.append(row)
            print(f"  N={n:>2} {before:>7} -> {after:<7}  均值 {row['mean']:>6.1f}%  "
                  f"p50 {row['p50']:>6.1f}%  p90 {row['p90']:>6.1f}%  "
                  f"p99 {row['p99']:>6.1f}%  p99.9 {row['p99.9']:>6.1f}%")

    # ---- 低优先级吞吐代价 ----
    print("\n" + "=" * 92)
    print(f"四、低优先级吞吐代价（Mbit/s，{len(seeds)} 个种子 均值±标准差）")
    print("=" * 92)
    grouped: dict[tuple[int, str], list[float]] = defaultdict(list)
    for row in summary:
        grouped[(int(row["stations"]), row["mode"])].append(float(row["low_throughput_mbps"]))
    print(f"  {'N':>3} {'P-EDCA':>16} {'NPCA':>16} {'变化':>10} {'相对':>9}")
    cost_rows = []
    for n in (10, 20, 30):
        a = grouped.get((n, "P-EDCA"), [])
        b = grouped.get((n, "NPCA"), [])
        if not a or not b:
            print(f"  {n:>3}   数据缺失（P-EDCA {len(a)} 条 / NPCA {len(b)} 条），跳过")
            continue
        sd_a = stdev(a) if len(a) > 1 else 0.0
        sd_b = stdev(b) if len(b) > 1 else 0.0
        delta = mean(b) - mean(a)
        rel = delta / mean(a) * 100
        cost_rows.append({"stations": n, "p_edca_mbps": mean(a), "npca_mbps": mean(b),
                          "delta_mbps": delta, "delta_pct": rel, "npca_std": sd_b})
        print(f"  {n:>3} {mean(a):>9.2f}±{sd_a:.2f} {mean(b):>9.2f}±{sd_b:.2f} "
              f"{delta:>+10.2f} {rel:>+8.2f}%")

    # ---- 写 CSV ----
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "analysis28_quantiles.csv", rows)
    _write_csv(output / "analysis28_cost.csv", cost_rows)

    # ---- 图 05：改善幅度随分位变化 ----
    labels = ["mean", "p50", "p90", "p99", "p99.9"]
    fig, ax = plt.subplots(figsize=(6.7, 4.1))
    for transition in ("EDCA->P-EDCA", "P-EDCA->NPCA"):
        ys = []
        for n in (10, 20, 30):
            row = next(r for r in rows if r["stations"] == n and r["transition"] == transition)
            ys.append([row[k] for k in labels])
        series = [sum(col) / len(col) for col in zip(*ys)]
        ax.plot(labels, series, marker="o", label=f"{transition} (mean of N=10/20/30)")
    ax.set(xlabel="Delay statistic", ylabel="Improvement vs previous scheme (%)",
           title="High-priority delay improvement by statistic")
    ax.axhline(0, color="black", lw=0.8, ls=":")
    ax.legend()
    ax.grid(alpha=0.24)
    _save(fig, output, "05_improvement_by_quantile")

    # ---- 图 06：低优先级吞吐 ----
    fig, ax = plt.subplots(figsize=(6.7, 4.1))
    xs = [10, 20, 30]
    for mode, marker in (("DCF", "s"), ("EDCA", "o"), ("P-EDCA", "^"), ("NPCA", "D")):
        means = [mean(grouped[(n, mode)]) for n in xs]
        stds = [stdev(grouped[(n, mode)]) if len(grouped[(n, mode)]) > 1 else 0.0 for n in xs]
        ax.errorbar(xs, means, yerr=stds, marker=marker, capsize=3, label=mode)
    ax.set(xlabel="Total stations (N)", ylabel="Low-priority throughput (Mbit/s)",
           title="Low-priority throughput by access scheme")
    ax.set_xticks(xs)
    ax.legend()
    _save(fig, output, "06_low_throughput_cost")

    print(f"\nCSV 与图已写入 {output}")
    return 0


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _save(fig, folder: Path, name: str) -> None:
    fig.savefig(folder / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(folder / f"{name}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
