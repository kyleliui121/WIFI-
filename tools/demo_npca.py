# -*- coding: utf-8 -*-
"""题目 26 专项：NPCA 简化模型的实现核对、参数取值与效果验证。

对应必做内容第 26 条，逐项覆盖：
  1. 主信道 + 非主信道两条信道；
  2. 主信道按设定比例被邻网占用，忙/闲交替，忙期服从 Exp(mean=2 ms)；
  3. 不启用 NPCA 时站点只能等主信道空闲；
  4. 启用 NPCA 后，外部忙期内站点可切到非主信道竞争发送；
  5. 切换时延在 50-200 us 内取值，并给出取值理由（敏感性扫描）。

用法：
    python tools/demo_npca.py                    # 默认 10 s / 3 种子 / N=10,20,30
    python tools/demo_npca.py --duration 2       # 快速自检
    python tools/demo_npca.py --no-compare       # 只做自检 + 时延扫描
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wifi_sim.priority import MACConfig, MACSimulator  # noqa: E402

DEFAULT_SEEDS = (42, 43, 44)
SWEEP_DELAYS_US = (50, 75, 100, 125, 150, 200)


# --------------------------------------------------------------------------- #
# 外部占用日历统计
# --------------------------------------------------------------------------- #
def external_calendar_stats(cfg: MACConfig) -> dict:
    """从离线生成的外部占用日历里统计忙期长度与占用率。"""
    events = MACSimulator(cfg).external_events
    busy, start = [], None
    for t, is_busy in events:
        if is_busy:
            start = t
        elif start is not None:
            busy.append(t - start)
            start = None
    if start is not None:
        busy.append(cfg.duration_us - start)
    return {
        "periods": len(busy),
        "mean_busy_ms": mean(busy) / 1000 if busy else 0.0,
        "max_busy_ms": max(busy) / 1000 if busy else 0.0,
        "occupancy": sum(busy) / cfg.duration_us,
    }


# --------------------------------------------------------------------------- #
# 第 26 条要求逐项核对
# --------------------------------------------------------------------------- #
def check_requirements(duration: float) -> bool:
    ok = True
    print("=" * 78)
    print("一、第 26 条要求逐项核对")
    print("=" * 78)

    def report(label: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        print(f"         {detail}")

    base = MACConfig(stations=10, mode="NPCA", duration_s=duration, seed=42)
    stats = external_calendar_stats(base)

    # 1) 两条信道
    sim_pe = MACSimulator(MACConfig(stations=10, mode="P-EDCA", duration_s=duration, seed=42))
    r_pe = sim_pe.run()
    report(
        "两条信道（主信道 0 / 非主信道 1）",
        set(sim_pe.busy) == {0, 1},
        f"MACSimulator.busy 的信道键 = {sorted(sim_pe.busy)}",
    )

    # 2) 忙期指数分布均值 2 ms + 目标占用率 30%
    report(
        "外部忙期样本均值 ≈ 2 ms",
        1.7 <= stats["mean_busy_ms"] <= 2.3,
        f"{duration:g} s 内 {stats['periods']} 个忙期，"
        f"实测均值 {stats['mean_busy_ms']:.3f} ms（理论 2.000 ms）",
    )
    report(
        "主信道外部占用率 ≈ 设定比例 30%",
        abs(stats["occupancy"] - 0.30) <= 0.03,
        f"实测占用率 {stats['occupancy'] * 100:.1f}%（目标 30.0%）",
    )

    # 3) 不启用 NPCA：只能等主信道空闲
    report(
        "不启用 NPCA 时主信道忙则等待（无任何非主信道发送）",
        r_pe.secondary_success == 0 and r_pe.switch_events == 0,
        f"P-EDCA: 非主信道成功 {r_pe.secondary_success} 帧，切换 {r_pe.switch_events} 次",
    )

    # 4) 启用 NPCA：外部忙期内切到非主信道竞争发送
    r_npca = MACSimulator(base).run()
    report(
        "启用 NPCA 后外部忙期可切到非主信道发送",
        r_npca.secondary_success > 0 and r_npca.switch_events > 0,
        f"NPCA: 非主信道成功 {r_npca.secondary_success} 帧，切换 {r_npca.switch_events} 次",
    )

    # 5) 切换时延约束 50-200 us
    in_range = True
    for bad in (49, 201):
        try:
            MACConfig(stations=10, mode="NPCA", duration_s=duration, switch_us=bad)
        except ValueError:
            continue
        in_range = False
    report(
        "切换时延限定在 50-200 us",
        in_range,
        "switch_us=49 / 201 均被 MACConfig 拒绝，合法区间为闭区间 [50, 200]",
    )

    print(f"\n  小结：{'全部通过' if ok else '存在未通过项'}\n")
    return ok


# --------------------------------------------------------------------------- #
# 切换时延取值：敏感性扫描
# --------------------------------------------------------------------------- #
def sweep_switch_delay(duration: float, seeds: tuple[int, ...], stations: int = 10) -> list[dict]:
    print("=" * 78)
    print(f"二、切换时延敏感性扫描（N={stations}，{len(seeds)} 个种子，每次 {duration:g} s）")
    print("=" * 78)
    print(f"  {'时延(us)':>8} {'高优先级均值(ms)':>16} {'p99(ms)':>10} "
          f"{'p99.9(ms)':>11} {'非主信道帧数':>12} {'切换次数':>9}")
    rows = []
    for delay in SWEEP_DELAYS_US:
        results = [
            MACSimulator(MACConfig(stations=stations, mode="NPCA", duration_s=duration,
                                   seed=seed, switch_us=float(delay))).run().as_dict()
            for seed in seeds
        ]
        row = {
            "switch_us": delay,
            "high_mean_ms": mean(r["high_mean_ms"] for r in results),
            "high_p99_ms": mean(r["high_p99_ms"] for r in results),
            "high_p999_ms": mean(r["high_p999_ms"] for r in results),
            "secondary_success": mean(r["secondary_success"] for r in results),
            "switch_events": mean(r["switch_events"] for r in results),
        }
        rows.append(row)
        print(f"  {delay:>8} {row['high_mean_ms']:>16.3f} {row['high_p99_ms']:>10.3f} "
              f"{row['high_p999_ms']:>11.3f} {row['secondary_success']:>12.1f} "
              f"{row['switch_events']:>9.1f}")
    print()
    return rows


# --------------------------------------------------------------------------- #
# 方案对比：P-EDCA vs NPCA
# --------------------------------------------------------------------------- #
def compare_schemes(duration: float, seeds: tuple[int, ...]) -> list[dict]:
    print("=" * 78)
    print(f"三、P-EDCA vs NPCA 对比（{len(seeds)} 个种子，每次 {duration:g} s）")
    print("=" * 78)
    print(f"  {'N':>3} {'方案':>8} {'均值(ms)':>9} {'p99(ms)':>9} {'p99.9(ms)':>10} "
          f"{'截止已观测失败率(%)':>10} {'低优先级(Mbps)':>14}")
    rows = []
    for stations in (10, 20, 30):
        for mode in ("P-EDCA", "NPCA"):
            results = [
                MACSimulator(MACConfig(stations=stations, mode=mode, duration_s=duration,
                                       seed=seed)).run().as_dict()
                for seed in seeds
            ]
            observed = sum(r["high_deadline_observed"] for r in results)
            failures = sum(r["high_deadline_observed_failure"] for r in results)
            row = {
                "stations": stations,
                "mode": mode,
                "high_mean_ms": mean(r["high_mean_ms"] for r in results),
                "high_p99_ms": mean(r["high_p99_ms"] for r in results),
                "high_p999_ms": mean(r["high_p999_ms"] for r in results),
                "deadline_observed_failure_pct": 100 * failures / observed if observed else None,
                "low_throughput_mbps": mean(r["low_throughput_mbps"] for r in results),
                "secondary_success": mean(r["secondary_success"] for r in results),
                "switch_events": mean(r["switch_events"] for r in results),
                "high_p999_std": (stdev(r["high_p999_ms"] for r in results)
                                  if len(results) > 1 else 0.0),
            }
            rows.append(row)
            failure_rate = f"{100 * failures / observed:.2f}" if observed else "—"
            print(f"  {stations:>3} {mode:>8} {row['high_mean_ms']:>9.3f} "
                  f"{row['high_p99_ms']:>9.3f} {row['high_p999_ms']:>10.3f} "
                  f"{failure_rate:>10} {row['low_throughput_mbps']:>14.2f}")
    print()

    # 改善幅度
    print("  相对 P-EDCA 的变化：")
    by_key = {(r["stations"], r["mode"]): r for r in rows}
    for stations in (10, 20, 30):
        a, b = by_key[(stations, "P-EDCA")], by_key[(stations, "NPCA")]
        p999_gain = (a["high_p999_ms"] - b["high_p999_ms"]) / a["high_p999_ms"] * 100
        mean_gain = (a["high_mean_ms"] - b["high_mean_ms"]) / a["high_mean_ms"] * 100
        tput_cost = (a["low_throughput_mbps"] - b["low_throughput_mbps"]) / a["low_throughput_mbps"] * 100
        print(f"    N={stations:>2}: p99.9 降低 {p999_gain:6.1f}% | 均值降低 {mean_gain:6.1f}% "
              f"| 低优先级吞吐变化 {-tput_cost:+6.2f}%")
    print()
    return rows


# --------------------------------------------------------------------------- #
def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="题目 26：NPCA 简化模型验证")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--no-compare", action="store_true")
    args = parser.parse_args()

    seeds = tuple(args.seeds)
    passed = check_requirements(args.duration)

    sweep_rows = sweep_switch_delay(args.duration, seeds)
    write_csv(args.out / "npca_switch_sweep.csv", sweep_rows)

    if not args.no_compare:
        compare_rows = compare_schemes(args.duration, seeds)
        write_csv(args.out / "npca_compare.csv", compare_rows)

    print(f"CSV 已写入 {args.out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
