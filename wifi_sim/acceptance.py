"""Audit a complete final experiment archive without modifying its CSVs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from math import isclose
from pathlib import Path

from .dcf import DCFConfig, percentile
from .priority import MACConfig, MODES


def rows(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def audit(folder: Path) -> str:
    m = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
    assert m['schema_version'] == 3 and not m['source_dirty']
    assert m['duration_s'] >= 10 and len(set(m['seeds'])) >= 3
    assert len(m['seeds']) == len(set(m['seeds']))
    for name, digest in m['sha256'].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
    for name, digest in m['source_files_sha256'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
    expected = {(n, mode, seed) for n in (10, 20, 30)
                for mode in MODES for seed in m['seeds']}
    summary = rows(folder / 'summary.csv')
    key = lambda r: (int(r['stations']), r['mode'], int(r['seed']))
    assert Counter(map(key, summary)) == Counter({k: 1 for k in expected})
    assert len(m['mac_configs']) == len(expected) == m['experiment_runs']
    assert {key(c) for c in m['mac_configs']} == expected
    for c in m['mac_configs']:
        assert c == asdict(MACConfig(stations=c['stations'], mode=c['mode'],
                                   seed=c['seed'], duration_s=m['duration_s']))
    packets = rows(folder / 'high_packets.csv')
    delays = rows(folder / 'high_delays.csv')
    assert set(map(key, packets)) <= expected and set(map(key, delays)) <= expected
    for r in summary:
        k = key(r)
        ps = [p for p in packets if key(p) == k]
        assert len({(p['station_id'], p['created_us']) for p in ps}) == len(ps)
        counts = Counter(p['outcome'] for p in ps)
        assert set(counts) <= {'success', 'dropped', 'unfinished'}
        assert int(r['high_generated']) == len(ps) == 2 * int(m['duration_s'] * 100)
        for outcome, col in [('success', 'high_success'), ('dropped', 'high_dropped'),
                             ('unfinished', 'high_unfinished')]:
            assert counts[outcome] == int(r[col]), (k, col)
        successful_delays, late, observed, failed, overdue = [], 0, 0, 0, 0
        for p in ps:
            created = float(p['created_us'])
            deadline = float(p['deadline_us'])
            assert deadline == created + float(r['deadline_us'])
            complete = float(p['completed_us']) if p['completed_us'] else None
            assert (complete is None) == (p['outcome'] == 'unfinished')
            if complete is not None:
                assert created <= complete <= m['duration_s'] * 1e6
            on_time = p['outcome'] == 'success' and complete <= deadline
            mature = deadline <= m['duration_s'] * 1e6
            assert (p['on_time_success'] == 'True') == on_time
            assert (p['deadline_observed'] == 'True') == mature
            observed += mature
            failed += mature and not on_time
            overdue += mature and p['outcome'] == 'unfinished'
            if p['outcome'] == 'success':
                successful_delays.append(complete - created)
                late += not on_time
        assert late == int(r['high_success_late'])
        assert observed == int(r['high_deadline_observed'])
        assert failed == int(r['high_deadline_observed_failure'])
        assert overdue == int(r['high_unfinished_overdue'])
        resolved = counts['success'] + counts['dropped']
        failures = late + counts['dropped']
        assert resolved == int(r['high_resolved'])
        assert failures == int(r['high_deadline_failure'])
        for col, num, den in [
            ('high_success_late_pct', late, counts['success']),
            ('high_drop_pct', counts['dropped'], resolved),
            ('deadline_failure_pct', failures, resolved),
            ('high_unfinished_pct', counts['unfinished'], len(ps)),
            ('deadline_observed_failure_pct', failed, observed)]:
            assert isclose(float(r[col]), 100 * num / den) if den else r[col] == '', (k, col)
        ds = [float(d['delay_ms']) for d in delays if key(d) == k]
        assert len(ds) == len(successful_delays)
        assert all(isclose(a, b / 1000) for a, b in zip(sorted(ds), sorted(successful_delays)))
        for col, q in [('high_p99_ms', .99), ('high_p999_ms', .999)]:
            value = percentile(successful_delays, q)
            assert isclose(float(r[col]), value) if value is not None else r[col] == ''
        assert float(r['duration_s']) == m['duration_s']
    dcf = rows(folder / 'dcf_runs.csv')
    assert len(dcf) == len(m['dcf_configs']) == m['dcf_validation_runs'] == 30
    assert {(int(json.loads(r['config'])['stations']), int(json.loads(r['config'])['seed']))
            for r in dcf} == {(n, s) for n in range(5, 51, 5) for s in m['seeds']}
    for c in m['dcf_configs']:
        assert c == asdict(DCFConfig(stations=c['stations'], seed=c['seed'], duration_s=m['duration_s']))
    for prefix in ('01_dcf_bianchi', '02_high_delay_ccdf', '03_high_p999_vs_n', '04_low_throughput_vs_n'):
        for ext in ('pdf', 'png'):
            assert (folder / f'{prefix}.{ext}').stat().st_size > 2000
    text = ['# 最终实验验收报告', '', f"代码提交：`{m['source_commit']}`；统计版本：3。",
            '', '参数已由用户确认与 README 的 A 班指定参数一致（2026-11-16）。',
            f"每次 {m['duration_s']} 秒，种子 {m['seeds']}；36 次 MAC 和 30 次饱和 DCF 校验。",
            '逐帧记录重算指标、帧数守恒、完整配置覆盖、时延分位数和文件 SHA-256 均通过。',
            '', '下表在各模式的全部 N 和种子上合并计数后计算比例，非逐次百分比的均值。', '',
            '| 模式 | 生成 | 成功 | 成功超时 | 丢弃 | 未完成 | 截止已观测 | 已观测失败 | 已观测失败率 % |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for mode in MODES:
        selected = [r for r in summary if r['mode'] == mode]
        totals = [sum(int(r[c]) for r in selected) for c in
                  ('high_generated', 'high_success', 'high_success_late', 'high_dropped',
                   'high_unfinished', 'high_deadline_observed', 'high_deadline_observed_failure')]
        text.append('| ' + ' | '.join([mode] + list(map(str, totals)) + [f'{100 * totals[-1] / totals[-2]:.6f}']) + ' |')
    text += ['', '已确定结果的综合失败率仍使用成功超时与丢弃之和 / 成功与丢弃之和；',
             '截止已观测失败率使用截止时刻不晚于观测终点的帧，纳入逾期未完成帧，排除截止尚未到达的帧。',
             '图表由同一目录 CSV 自动生成；本报告由验收程序生成，未手改 CSV。', '']
    return '\n'.join(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--write-report', action='store_true')
    args = parser.parse_args()
    report = audit(args.folder)
    if args.write_report:
        (args.folder / 'acceptance.md').write_text(report, encoding='utf-8')
    print(report)


if __name__ == '__main__':
    main()
