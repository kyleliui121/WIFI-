# 接手指南（ONBOARDING）

## 1. 代码地图

| 位置 | 职责 |
|---|---|
| `wifi_sim/priority.py` | DCF、EDCA、P-EDCA、NPCA 共用的 SimPy 事件仿真 |
| `wifi_sim/dcf.py`、`wifi_sim/theory.py` | 饱和 DCF 仿真、时延分位数和 Bianchi 固定点 |
| `wifi_sim/experiments.py`、`wifi_sim/plotting.py` | 运行实验矩阵，写入逐次和逐帧 CSV，生成图 01–04 |
| `wifi_sim/acceptance.py` | 校验实验覆盖、文件哈希、帧数守恒及由逐帧数据重算的指标 |
| `tools/demo_npca.py`、`tools/analyze_28.py` | 第 26 条专项检查和第 28 条改善幅度分析 |
| `wifi_sim/extensions.py`、`tools/analyze_extensions.py` | 帧错误率、隐藏终端的配对实验和汇总 |
| `tests/`、`.github/workflows/reproduce.yml` | 回归测试和持续集成 |

实验的每组结果在 `summary.csv` 中占一行。`high_packets.csv` 记录每个高优先级帧的截止时刻和最终状态，`high_delays.csv` 提供每个成功帧的时延。退避、发帧结束、外部忙闲切换、到达及信道切换完成都是仿真推进的事件。各方案使用同一组种子生成外部占用日历。

## 2. 环境与验证

从仓库根目录运行以下命令。Windows 的运行入口见 [README](../README.md#windows-一键运行)。

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m tools.verify_bianchi
python -m tools.verify_repro
python -m zipfile -e data/official_run.zip results/official
python -m wifi_sim.acceptance results/official
```

Bianchi 验证使用二分法独立复算经典和有限重传固定点。复现脚本对照当前正式汇总，重跑 N=10、种子 42 的四种方案并比对关键指标。完整归档包含 36 次方案实验和 30 次饱和 DCF 校验。

## 3. 写报告时查哪里

- 题目、参数、统计口径见[题目原文](题目四-原文整理.md)和[仿真方法](methodology.md)。
- 第 27 条从[正式汇总](../data/official_summary.csv)、[正式图表](../data/official_figures)及[验收报告](../data/official_acceptance.md)取数。
- 第 28 条的各分位改善幅度、吞吐变化和建模局限见[分析文档](分析-28.md)。
- 选做第 1、2 项见[帧错误率与隐藏终端](拓展-12-说明.md)。
- 正式实验每组至少 10 秒。短时运行适用于冒烟测试。重新生成的数据写到 `results/`，正式产物和来源记录在 `data/`。
