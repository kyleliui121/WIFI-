# 构建与运行 ns-3 EDCA 对照

场景使用 ns-3 公开的 Wi-Fi API。用带 Wi-Fi、Internet 和 Mobility 模块的 ns-3 源码构建。Windows 可使用 x64 工具环境中的 ClangCL 和 Ninja，Linux 使用 ns-3 支持的 C++ 工具链。 [ns-3 官方安装指南](https://www2.nsnam.org/docs/installation/singlehtml/)

## 构建可执行场景

把 [场景源码](wifi-edca-crosscheck.cc) 复制到 ns-3 源码目录的 `scratch/` 下。在 ns-3 源码目录执行：

```bash
python ns3 configure --build-profile=optimized --enable-modules=wifi,internet,mobility --disable-examples --disable-tests
python ns3 build scratch/wifi-edca-crosscheck
```

Windows 可在 x64 工具环境中先设置 `CC=clang-cl` 和 `CXX=clang-cl`，并给配置命令加 `-G Ninja`。编译完成后，从本仓库根目录运行以下命令，将 `<场景可执行文件>` 替换为 `build/scratch/` 中生成的程序。

```bash
python -m ns3ext.run_crosscheck --exe "<场景可执行文件>" --lib-dir "<ns-3 的 build/lib>" --out results/ext34/ns3_crosscheck.csv --stations 10 --duration 10 --seed 42 --ns3-version 3.49
python -m wifi_sim.ext34 --out results/ext34 --crosscheck-only --crosscheck-stations 10 --duration 10 --seeds 42
python -m tools.compare_ns3 --results results/ext34
```

如需使用 Windows DLL 入口，把本目录的 `CMakeLists.txt` 和场景源码一起复制到 ns-3 的 `scratch/crosscheck-dll/`，重新运行配置，然后执行 `cmake --build cmake-cache --target wifi-edca-crosscheck-dll`。将上例中的 `--exe` 改为 `--dll` 并传入 `build/` 下生成的 `wifi-edca-crosscheck.dll` 的实际路径。可重复传入 `--lib-dir` 来声明额外库目录。

## 验收规则

- 默认 EDCA 中 VO、VI、BE、BK 分别配置 ToS `0xC0`、`0x80`、`0x00`、`0x20`。 [ns-3 的 DS 字段与 TID 映射](https://github.com/nsnam/ns-3-dev-git/blob/ns-3.46/src/wifi/model/qos-utils.cc#L214-L235)
- 场景检查测量窗内发出的带应用时间戳的数据帧。EDCA 每个 AC 都必须发出数据，且每次发送的 QoS TID 都映射到预期 AC。CSV 写入每个 AC 的数据尝试数、匹配数和 TID 位掩码。
- 对比脚本按站点数、时长、种子、方案和 AC 对齐两套数据。只比较干净信道的同配置实验。SimPy 时延计到 ACK 完成，ns-3 计到 AP 收到应用帧。
