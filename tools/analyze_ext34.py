"""Summarise the extension-3/4 CSVs into Markdown tables (no manual numbers).

Usage:
    python -m tools.analyze_ext34 --results results/ext34
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.compare_ns3 import compare  # noqa: E402


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def fmt(value: str | float | None, digits: int = 2) -> str:
    if value in ("", None):
        return "-"
    number = float(value)
    return f"{number:.{digits}f}"


def table_rate(summary: list[dict]) -> str:
    lines = ["| AC | N | DCF (Mbit/s) | EDCA (Mbit/s) | 变化 |",
             "|---|---:|---:|---:|---:|"]
    index = {(row["mode"], int(row["stations"]), row["ac"]): row
             for row in summary}
    for n in sorted({int(row["stations"]) for row in summary}):
        for ac in ("VO", "VI", "BE", "BK"):
            dcf = index.get(("DCF", n, ac))
            edca = index.get(("EDCA", n, ac))
            if not dcf or not edca:
                continue
            d = float(dcf["throughput_mbps_mean"])
            e = float(edca["throughput_mbps_mean"])
            change = f"{(e - d) / d * 100:+.1f}%" if d else "-"
            lines.append(f"| {ac} | {n} | {d:.2f} | {e:.2f} | {change} |")
    return "\n".join(lines)


def table_delay(summary: list[dict]) -> str:
    lines = ["| AC | N | DCF 均值 | EDCA 均值 | DCF p99 | EDCA p99 | DCF p99.9 | EDCA p99.9 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    index = {(row["mode"], int(row["stations"]), row["ac"]): row
             for row in summary}
    for n in sorted({int(row["stations"]) for row in summary}):
        for ac in ("VO", "VI", "BE", "BK"):
            d = index.get(("DCF", n, ac))
            e = index.get(("EDCA", n, ac))
            if not d or not e:
                continue
            lines.append(
                f"| {ac} | {n} | {fmt(d['mean_ms_mean'])} | {fmt(e['mean_ms_mean'])} | "
                f"{fmt(d['p99_ms_mean'], 1)} | {fmt(e['p99_ms_mean'], 1)} | "
                f"{fmt(d['p999_ms_mean'], 1)} | {fmt(e['p999_ms_mean'], 1)} |")
    return "\n".join(lines)


def table_deadline(summary: list[dict]) -> str:
    lines = ["| N | AC | DCF 截止失败 (%) | EDCA 截止失败 (%) | DCF 丢弃 (%) | EDCA 丢弃 (%) | DCF 未完成 (%) | EDCA 未完成 (%) |",
             "|---:|---|---:|---:|---:|---:|---:|---:|"]
    index = {(row["mode"], int(row["stations"]), row["ac"]): row
             for row in summary}
    for n in sorted({int(row["stations"]) for row in summary}):
        for ac in ("VO", "VI"):
            d = index.get(("DCF", n, ac))
            e = index.get(("EDCA", n, ac))
            if not d or not e:
                continue
            metrics = ("deadline_observed_failure_pct_mean", "drop_pct_mean", "unfinished_pct_mean")
            cells = [fmt(row[metric]) for metric in metrics for row in (d, e)]
            lines.append("| " + " | ".join([str(n), ac, *cells]) + " |")
    return "\n".join(lines)


def table_totals(summary: list[dict]) -> str:
    lines = ["| N | 方案 | 总吞吐 (Mbit/s) | 各 AC 平均碰撞尝试占比 (%) |", "|---:|---|---:|---:|"]
    for n in sorted({int(row["stations"]) for row in summary}):
        for mode in ("DCF", "EDCA"):
            rows = [row for row in summary
                    if row["mode"] == mode and int(row["stations"]) == n]
            total = sum(float(row["throughput_mbps_mean"]) for row in rows)
            shares = [float(row["collision_pct_mean"]) for row in rows if row["collision_pct_mean"]]
            collision = fmt(mean(shares), 1) if shares else "-"
            lines.append(f"| {n} | {mode} | {total:.2f} | {collision} |")
    return "\n".join(lines)


def table_ns3(rows: list[dict]) -> str:
    lines = ["| N | 时长 (s) | 种子 | 方案 | AC | 实测 TID | SimPy 吞吐 | ns-3 吞吐 | SimPy 均值 | ns-3 均值 |",
             "|---:|---:|---:|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        identity = [str(row[key]) for key in ("stations", "duration_s", "seed", "mode", "ac")]
        measurements = [fmt(row[key]) for key in ("simpy_throughput_mbps", "ns3_throughput_mbps",
                                                   "simpy_mean_ms", "ns3_mean_ms")]
        lines.append("| " + " | ".join([*identity, row["ns3_tid"] or "—", *measurements]) + " |")
    return "\n".join(lines)


def build_summary(folder: Path, comparison: list[dict] | None = None) -> str:
    summary = read(folder / "ext4ac_summary.csv")
    if not summary:
        raise ValueError("missing four-AC summary rows")
    sections = ["# 选做拓展 3、4 实验结果", "",
                "吞吐使用 Mbit/s，时延使用 ms。时延只统计成功帧。",
                "截止失败率仅统计截止落入观测窗口的帧，包括已逾期的未完成帧。", "",
                "## 四类业务吞吐", "", table_rate(summary), "",
                "## 成功帧时延", "", table_delay(summary), "",
                "## 实时业务截止失败、丢弃与未完成", "", table_deadline(summary), "",
                "## 四类业务汇总", "", table_totals(summary), ""]
    if comparison is not None:
        sections += ["## 干净信道 SimPy 与 ns-3 对照", "",
                     "ns-3 使用 AP 收到应用帧的时刻，SimPy 使用 ACK 完成时刻。",
                     "表中 TID 来自实际发出的应用数据帧。", "", table_ns3(comparison), ""]
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("results/ext34"))
    parser.add_argument("--ns3-csv", type=Path)
    args = parser.parse_args()
    local_ns3 = args.results / "ns3_crosscheck.csv"
    ns3 = args.ns3_csv or (local_ns3 if local_ns3.is_file() else None)
    output = args.results / "ext4ac_tables.md"
    try:
        rows = compare(args.results / "ns3_simpy_crosscheck.csv", ns3)[0] if ns3 else None
        output.write_text(build_summary(args.results, rows), encoding="utf-8")
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(1, f"Could not build tables: {exc}\n")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
