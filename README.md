# 面向车载低时延业务的 Wi-Fi 优先信道接入仿真

课程设计选题四：DCF、EDCA 与 802.11bn P-EDCA/NPCA 简化模型（A 班）。

## 课程设计要求

[题目四完整原文整理](docs/题目四-原文整理.md)（场景假设、A/B 班参数、必做内容、选做拓展、评价指标、必交图表与参考资料）。

> 任务要求单独放在 `docs/` 中。按照课程题目图片转录，仅做 Markdown 排版，不缩减要求。

## 当前实现：第一阶段 DCF 基线

`wifi_sim/dcf.py`：基于 SimPy 的单信道饱和 DCF 仿真器。包含独立站点退避计数、DIFS、9 μs 时隙、二进制指数退避、同时发送碰撞、冻结/恢复退避、最多 7 次重传、超限丢帧、ACK 时间及随机种子。时钟单位为 **μs**，按下次竞争事件跳转；即使跳过了空闲时隙，退避计数仍以整数时隙递减。

当前阶段使用 **全部站点均为 1500 B 饱和流量**，为下一步 `N=5…50` 的 Bianchi DCF 理论校验建立基线。尚未加入 A 班的高/低优先级业务、EDCA、P-EDCA、NPCA，也未绘制课程要求的对比图。

### 安装与运行

Python 3.10+：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m wifi_sim --stations 10 --duration 10 --seed 42 --output results/dcf_n10.json
python -m unittest discover -s tests -v
```

主要命令行参数：`--stations` 站点数、`--duration` 秒、`--frame-bytes` 数据帧字节数、`--seed` 随机种子、`--output` JSON 输出路径。默认分别为 `10、10、1500、42`。

JSON 包含发送尝试数、碰撞尝试数、碰撞概率、成功帧、丢弃帧、吞吐量，以及成功帧平均/p99/p99.9 接入时延。**碰撞概率分母是发送尝试次数而不是竞争轮数**；双站点同时碰撞会计入 2 次失败尝试。时延从待发送帧就绪开始计算到成功收到 ACK 为止。

### 简化假设与边界

- 1 个共享信道，所有站点互相可听，无隐藏终端、物理误码与传播时延；每个站点始终有一帧待发送（饱和）。
- 默认 `slot=9 μs`、`SIFS=16 μs`、`DIFS=SIFS+2slot=34 μs`、前导 `20 μs`、速率 `54 Mbit/s`、ACK `14 B`，帧长按 `20 + 8×字节数/54` μs 计算。
- CW 初始 15、最大 1023；发生第 `r` 次失败后的竞争窗口为 `min((15+1)×2^r−1,1023)`，均匀抽取 `0…CW`。`retry_limit=7` 指初传之外最多再重传 7 次。
- 成功占用时间简化为 `DATA + SIFS + ACK`；碰撞没有 ACK，站点按等长 `SIFS + ACK` 时间等待作为 **ACK 超时近似**，之后统一等待 DIFS。该处理不是精确 802.11 PHY ACK timeout/EIFS，需在报告中说明，并与 Bianchi 理论对比时分析潜在差异。
- 统计窗口只计入在仿真截止前已完成成功或失败等待过程的尝试；吞吐量按设定观察时长计算。

## 下一步

对饱和 DCF 扫描 `N=5…50`，用 Bianchi 固定点方程求理论碰撞概率，对比模拟曲线并解释差异。通过该验证后再扩展 EDCA、P-EDCA 与 NPCA。
