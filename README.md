# 面向车载低时延业务的 Wi-Fi 优先信道接入仿真

**通信网课程设计（A 班）**：比较 DCF、EDCA、EDCA+P-EDCA 和 EDCA+P-EDCA+NPCA 四类简化信道接入方案，评估高优先级远程泊车控制的尾时延、超时率及低优先级吞吐量。

- [题目四：完整原文整理](docs/题目四-原文整理.md)（原题不简化）
- [建模假设、参数、统计口径与局限性](docs/methodology.md)
- [课程论文初稿](docs/课程论文初稿.md)（SimPy 4.1.2 已复核，仍需人工审稿）
- [官方实验 CSV 摘要](data/official_summary.csv) · [Bianchi 对照](data/official_bianchi.csv) · [实验元信息](data/official_metadata.json)
- [GitHub Actions 正式验证与图表下载](https://github.com/kyleliui121/WIFI-/actions/runs/43408103434)（Python 3.11 / SimPy 4.1.2，全部步骤成功）

## 模块结构

```text
wifi_sim/
  dcf.py          饱和 DCF 基线与最简命令行
  theory.py       Bianchi 经典模型 / 有限重传校正
  priority.py     DCF、EDCA、P-EDCA、NPCA 共用 SimPy 事件仿真
  experiments.py  A 班仿真矩阵、随机种子、CSV 输出
  plotting.py     四种必交图表生成（PNG / PDF）
  __main__.py     单次 DCF 运行入口
tests/            关键退避与事件行为回归测试
```

**实现范围**：全部必做模块（DCF、Bianchi 校验、EDCA、P-EDCA、NPCA、三档 N × 四方案 × 三种子 × 10 秒、指标与四类图表）。选做的隐藏终端、AC_VI/BK、误码与 ns-3 交叉校验暂不包含。

## 运行环境

Python 3.10+，安装 `simpy`、`scipy`、`numpy`、`matplotlib`：

```bash
python -m venv .venv
# Windows 激活虚拟环境：.venv\Scripts\activate
# macOS/Linux：source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

### 单次 DCF 快速检查

```bash
python -m wifi_sim --stations 10 --duration 10 --seed 42 --output results/dcf_n10.json
```

### 一次性生成 A 班全部实验结果和图表

```bash
python -m wifi_sim.experiments --out results --duration 10 --seeds 42 43 44 --bianchi-step 5
```

生成文件：

| 文件 | 用途 |
|---|---|
| `results/bianchi.csv` | DCF 饱和 N=5,10,…,50：经典 Bianchi、有限重传理论与仿真均值/标准差 |
| `results/summary.csv` | 36 次对比仿真（3 档 N × 4 种方案 × 3 个种子），每次 >=10 秒 |
| `results/high_delays.csv` | 每个成功的高优先级数据帧的接入时延，用于 CCDF |
| `results/metadata.json` | 实验时长、随机种子、运行矩阵 |
| `results/01_*.png/.pdf` 至 `results/04_*.png/.pdf` | 四类必交图 |

为了更密集地验证 Bianchi，可以用 `--bianchi-step 1` 扫描 N=5 到 50 每一个整数。测试时可临时设置 `--duration 0.1`，但这**不满足课程正式实验至少 10 秒**的要求，不能将短时实验当作正式结果。

## A 班指定参数

- N=10、20、30，两个高优先级站点；高优先级 100 B/10 ms，截止 10 ms；低优先级 1500 B 饱和。
- 主信道邻网外部忙期平均 2 ms、长期目标外部占用率 30%。
- AIFSN/CW 高优先级 = 2/(3,7)，低优先级 = 3/(15,1023)，重传上限 7。
- P-EDCA 自定义紧急门限：5ms 或重传次数>=2，使用 AIFSN=1、CW=(1,3)。
- NPCA 仅允许高优先级在主信道受邻网占用时切换到独立辅助信道，切换时延 100 μs。

本项目使用**明确标注的课程简化假设**，不是 IEEE 802.11bn 的标准级 PHY/MAC 仿真或真实系统预测。尤其是 NPCA 外部占用日历采用离线生成并保证帧不跨越外部忙起点，会高估外部占用可预知性，审查论文时请特别注意。

## 复核结果（2026-11-13）

GitHub Actions 在真实 `simpy==4.1.2` 下执行了 12 项单元测试以及 30 次 Bianchi 校验和 36 次 A 班方案仿真，均通过；官方 CSV 汇总与本地先前预验证完全一致。**图表和论文仍基于课程的理想化 P-EDCA/NPCA 模型，不能视为 IEEE 802.11bn 设备测量。**
