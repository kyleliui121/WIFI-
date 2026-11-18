# 面向车载低时延业务的 Wi-Fi 优先信道接入仿真

**通信网课程设计（A 班）**：比较 DCF、EDCA、EDCA+P-EDCA 和 EDCA+P-EDCA+NPCA 四类简化信道接入方案，评估高优先级远程泊车控制的尾时延、成功帧超时率、丢帧率、综合截止失败率、未完成占比及低优先级吞吐量。

`summary.csv` 分别输出 `high_success_late`、`high_dropped`、`high_unfinished` 及对应比例。旧 `deadline_miss_pct` 已更名为 `deadline_failure_pct`，保留“成功超时或丢弃”的综合含义；各指标分子、分母和空值规则见 [统计口径](docs/methodology.md#5-统计口径务必保持一致)。

- [题目四：完整原文整理](docs/题目四-原文整理.md)（原题不简化）
- [建模假设、参数、统计口径与局限性](docs/methodology.md)
- [第 28 条的时延改善与吞吐代价](docs/分析-28.md) · [交接说明](docs/交接说明.md) · [接手指南](docs/接手指南-ONBOARDING.md)
- [选做拓展 1、2 的模型与结果](docs/拓展-12-说明.md) · [拓展接入记录](docs/拓展-12-接入记录.md)
- [官方实验 CSV 摘要](data/official_summary.csv) · [Bianchi 对照](data/official_bianchi.csv) · [实验元信息](data/official_metadata.json)
- [新版完整运行归档（逐帧/逐次 CSV、图表、配置与报告）](data/official_run.zip) · [验收报告](data/official_acceptance.md) · [运行入口和文件校验值](data/official_manifest.json)
- [四类正式图表（PNG / PDF）](data/official_figures) · [逐次饱和 DCF 结果](data/official_dcf_runs.csv)
- [旧结果及来源版本](data/legacy/4b3498f/provenance.json)（原始文件未改列名；旧 Actions 运行仅作为历史来源）

## 模块结构

```text
wifi_sim/
  dcf.py          饱和 DCF 基线与最简命令行
  theory.py       Bianchi 经典模型 / 有限重传校正
  priority.py     DCF、EDCA、P-EDCA、NPCA 共用 SimPy 事件仿真
  experiments.py  A 班仿真矩阵、随机种子、CSV 输出
  extensions.py   帧错误率与隐藏终端的配对实验
  plotting.py     四种必交图表生成（PNG / PDF）
  __main__.py     单次 DCF 运行入口
tests/            关键退避与事件行为回归测试
tools/            NPCA 专项验证、时延与吞吐分析、独立复核脚本
```

**实现范围**涵盖全部必做模块及选做第 1、2 项。AC_VI/BK 与 ns-3 交叉校验属于后续拓展。

## 运行环境

Python 3.10+，安装 `simpy`、`scipy`、`numpy`、`matplotlib`：

```bash
python -m venv .venv
# Windows 激活虚拟环境：.venv\Scripts\activate
# macOS/Linux：source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

### Windows 一键运行

安装依赖后，可在项目根目录双击以下脚本，或在 VS Code 的「运行和调试」里选择对应的 F5 配置。

| 文件 | 内容 | 输出 |
|---|---|---|
| `run_experiments.bat` | 第 27 条的 36 次对比实验、Bianchi 校验和图 01–04 | `results/matrix/` |
| `run_npca_demo.bat` | 第 26 条的 NPCA 专项检查、切换时延扫描和方案对比 | `results/npca/` |
| `run_analysis.bat` | 读取第 27 条的结果，计算改善幅度与吞吐变化并生成图 05–06 | `results/analysis28/` |
| `run_extensions.bat` | 独立帧错误、隐藏终端及配对基线，生成图 07–10 与汇总表 | `results/extensions/` |

`wifi_sim/` 中的模块使用包内相对导入，请从项目根目录用 `python -m wifi_sim.experiments` 运行实验。

### 单次 DCF 快速检查

```bash
python -m wifi_sim --stations 10 --duration 10 --seed 42 --output results/dcf_n10.json
```

### 一次性生成 A 班全部实验结果和图表

```bash
python -m wifi_sim.experiments --out results --duration 10 --seeds 42 43 44 --bianchi-step 5
python -m wifi_sim.acceptance results --write-report
```

生成文件：

| 文件 | 用途 |
|---|---|
| `results/bianchi.csv` | DCF 饱和 N=5,10,…,50：经典 Bianchi、有限重传理论与仿真均值/标准差 |
| `results/summary.csv` | 36 次对比仿真（3 档 N × 4 种方案 × 3 个种子），每次 >=10 秒 |
| `results/high_delays.csv` | 每个成功的高优先级数据帧的接入时延，用于 CCDF |
| `results/metadata.json` | 代码提交号、完整逐次配置、依赖版本、运行矩阵与文件校验值 |
| `results/high_packets.csv` | 每个高优先级帧的入队、截止、完成时刻及最终状态，用于独立重算 |
| `results/dcf_runs.csv` | 30 次饱和 DCF 校验的逐次结果与完整配置 |
| `results/acceptance.md` | 自动生成的配置、守恒与指标一致性验收报告 |
| `results/01_*.png/.pdf` 至 `results/04_*.png/.pdf` | 四类必交图 |

为了更密集地验证 Bianchi，可以用 `--bianchi-step 1` 扫描 N=5 到 50 每一个整数。测试时可临时设置 `--duration 0.1`，但这**不满足课程正式实验至少 10 秒**的要求，不能将短时实验当作正式结果。

### 选做拓展 1、2

```bash
python -m wifi_sim.extensions --out results/extensions --duration 10 --seeds 42 43 44
python -m tools.analyze_extensions --results results/extensions
```

每次运行都会生成匹配时长和种子的对照数据。帧错误率默认为 1%、2.5%、5%，可通过 `--rates` 传入 0 至 1 之间的概率。 [本次完整拓展结果](data/extensions/12/ext_tables.md)

## A 班指定参数

- N=10、20、30，两个高优先级站点；高优先级 100 B/10 ms，截止 10 ms；低优先级 1500 B 饱和。
- 主信道邻网外部忙期平均 2 ms、长期目标外部占用率 30%。
- AIFSN/CW 高优先级 = 2/(3,7)，低优先级 = 3/(15,1023)，重传上限 7。
- P-EDCA 自定义紧急门限：5ms 或重传次数>=2，使用 AIFSN=1、CW=(1,3)。
- NPCA 仅允许高优先级在主信道受邻网占用时切换到独立辅助信道，默认切换时延 100 μs，见[取值说明与敏感性扫描](docs/methodology.md#41-切换时延取值)。

本项目使用**明确标注的课程简化假设**，不是 IEEE 802.11bn 的标准级 PHY/MAC 仿真或真实系统预测。尤其是 NPCA 外部占用日历采用离线生成并保证帧不跨越外部忙起点，会高估外部占用可预知性，分析结果时请特别注意。

## 最终交付验收（2026-11-16）

教师参数已由用户确认与上述 A 班指定参数一致。统计版本 3 补齐截止已观测失败率：分母为截止时刻已落在观测窗口内的帧，分子为其中未按时成功交付的帧，包含逾期未完成帧；与已确定结果的综合失败率分别报告。

正式运行使用代码 [`da495c023c55abd22ffd8b3adac454e359170aa8`](https://github.com/kyleliui121/WIFI-/commit/da495c023c55abd22ffd8b3adac454e359170aa8)，在干净代码工作区重新运行全部实验，未沿用 `210058f` 的结果。种子 42、43、44，每次 10 秒；36 次 MAC 对比和 30 次饱和 DCF 校验。20 项单元测试通过；逐帧重算新指标、帧数守恒、完整配置覆盖、分位数与文件哈希校验通过。数值见自动生成的正式验收报告，图表全部来自同一次运行的 CSV。

完整结果包解压到 `results/official` 后，可运行 `python -m wifi_sim.acceptance results/official` 复核。验收会核对产物，并按归档记录的代码提交核对源文件哈希。复核早期归档需要本地 Git 历史可访问该提交。更新正式数据时应重新运行完整实验并验收。

本次正式运行是本地 Python 3.12.10 / SimPy 4.1.2，未声称来自旧 Actions 运行。持续集成使用相同完整实验命令和验收程序。**结果基于课程的理想化 P-EDCA/NPCA 模型，不能视为 IEEE 802.11bn 设备测量。**
