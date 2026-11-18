"""Validate paired extension runs and build a Markdown results table."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from math import isclose
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wifi_sim.priority import MODES  # noqa: E402


def read_matrix(folder: Path, metadata: dict) -> list[dict]:
    seeds = metadata["seeds"]
    stations = metadata["A_class_N"]
    duration = metadata["duration_s"]
    rows = []
    for scenario, rates in (("baseline", [0.0]),
                            ("frame_error", metadata["frame_error_rates"]),
                            ("hidden", [0.0])):
        with (folder / f"ext_{scenario}.csv").open(encoding="utf-8", newline="") as source:
            matrix = list(csv.DictReader(source))
        actual = {(int(row["stations"]), row["mode"], int(row["seed"]), float(row["frame_error_rate"]))
                  for row in matrix}
        expected = {(n, mode, seed, rate) for n in stations for mode in MODES
                    for seed in seeds for rate in rates}
        if actual != expected or len(matrix) != len(expected) or len(matrix) != metadata[f"runs_{scenario}"]:
            raise ValueError(f"{scenario} matrix is incomplete, contains duplicates or does not match its metadata")
        for row in matrix:
            if (float(row["duration_s"]) != duration or row["scenario"] != scenario
                    or row["hidden_terminals"] != str(scenario == "hidden")):
                raise ValueError(f"{scenario} row has unmatched settings")
            check_accounting(row)
        rows.extend(matrix)
    return rows


def check_accounting(row: dict) -> None:
    generated, success, dropped, unfinished, observed, failed, late = (
        int(row[column]) for column in (
            "high_generated", "high_success", "high_dropped", "high_unfinished",
            "high_deadline_observed", "high_deadline_observed_failure", "high_success_late",
        )
    )
    if (generated != success + dropped + unfinished
            or dropped != int(row["high_dropped_by_error"]) + int(row["high_dropped_by_collision"])
            or not 0 <= failed <= observed <= generated
            or not 0 <= late <= success):
        raise ValueError(f"frame counts are inconsistent in {row['scenario']}: {row['mode']} N={row['stations']} seed={row['seed']}")
    for column, numerator, denominator in (
        ("high_success_pct", success, generated),
        ("high_success_late_pct", late, success),
        ("high_drop_pct", dropped, success + dropped),
        ("high_unfinished_pct", unfinished, generated),
        ("deadline_observed_failure_pct", failed, observed),
    ):
        value = row[column]
        match = value != "" and isclose(float(value), 100 * numerator / denominator) if denominator else value == ""
        if not match:
            raise ValueError(f"{column} is inconsistent with its counts in {row['scenario']}")


def cell_mean(rows: list[dict], column: str) -> str:
    values = [float(row[column]) for row in rows if row[column] != ""]
    return f"{mean(values):.2f}" if values else "—"


def build_report(metadata: dict, rows: list[dict]) -> str:
    grouped = defaultdict(list)
    for row in rows:
        group = row["scenario"], float(row["frame_error_rate"]), int(row["stations"]), row["mode"]
        grouped[group].append(row)
    lines = [
        "# 选做拓展实验汇总",
        "",
        f"每组 {metadata['duration_s']:g} 秒。种子 {', '.join(map(str, metadata['seeds']))}。",
        "各列先按种子计算，再取平均。时延仅统计成功帧。截止失败率的分母为截止时刻已落入观测窗口的帧。",
        "丢弃率以成功和丢弃之和为分母，未完成率和成功率以生成数为分母。— 表示没有可用分母或样本。",
        "",
        "## 1. 帧错误率",
        "",
        "| N | 方案 | 输入错误率 (%) | 成功帧 p99.9 (ms) | 截止已观测失败率 (%) | 丢弃率 (%) | 未完成率 (%) | 低优先级吞吐 (Mbit/s) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    metrics = ("high_p999_ms", "deadline_observed_failure_pct", "high_drop_pct",
               "high_unfinished_pct", "low_throughput_mbps")
    for n in metadata["A_class_N"]:
        for mode in MODES:
            for rate in (0.0, *sorted(metadata["frame_error_rates"])):
                cases = grouped["frame_error" if rate else "baseline", rate, n, mode]
                cells = [cell_mean(cases, metric) for metric in metrics]
                lines.append("| " + " | ".join([str(n), mode, f"{100 * rate:g}", *cells]) + " |")
    lines += [
        "",
        "## 2. 隐藏终端",
        "",
        "| N | 方案 | 场景 | 成功率 (%) | 成功帧 p99.9 (ms) | 截止已观测失败率 (%) | 丢弃率 (%) | 未完成率 (%) | 低优先级吞吐 (Mbit/s) | 碰撞尝试 (%) |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for n in metadata["A_class_N"]:
        for mode in MODES:
            for scenario, label in (("baseline", "互相可听"), ("hidden", "两组互不可听")):
                cases = grouped[scenario, 0.0, n, mode]
                cells = [cell_mean(cases, metric)
                         for metric in ("high_success_pct", *metrics, "collision_pct")]
                lines.append("| " + " | ".join([str(n), mode, label, *cells]) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results" / "extensions")
    folder = parser.parse_args().results
    try:
        metadata = json.loads((folder / "ext_metadata.json").read_text(encoding="utf-8"))
        rows = read_matrix(folder, metadata)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    output = folder / "ext_tables.md"
    output.write_text(build_report(metadata, rows), encoding="utf-8")
    print(f"Validated {len(rows)} runs and wrote {output}")


if __name__ == "__main__":
    main()
