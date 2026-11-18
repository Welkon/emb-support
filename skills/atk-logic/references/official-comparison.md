# 我们的技能 vs 官方（手册 / GUI / 官方源码）

对比基准：`docs/ATK CLI AI manual.md`、`docs/ATK CLI User manual.md`、
GUI 手册（ATK-Logic 用户手册 PDF）、官方源码 `alientek-openedv/atk-logic`（GPL-3.0，只读参考）。

## 1. 能力矩阵

| 能力 | 官方 CLI | 官方 GUI | 本技能 |
|---|---|---|---|
| 一次性采集 | ✅ | ✅ | ✅（包装 CLI，`capture`） |
| 滚动采集 / 循环采集 | ❌（手册 §9 明示首版不支持） | ✅ | ❌ 待原生实现 |
| 多级 / 串行触发 | ❌ | ✅ | 协议层已就绪（`0x13/0x14`），真机未验 |
| PWM 输出 | ❌ | ✅ | 报文构造器已有（`0x17`） |
| 毛刺过滤 | ❌ | ✅ | 后处理未实现 |
| 协议解码 | ❌ | ✅（内置 sigrok 解码器，209 个） | ✅ **原地加载 GUI 自带解码器**，不复制代码 |
| 波形导出 | CSV/VCD 由本技能生成 | PNG/工程文件 | CSV/VCD，`.atkdl` 只读 |
| 工程文件读写 | 读 | 读/写 | 只读（`atkdl.py`） |

## 2. 采集实现方式对比

| | 官方 GUI | 本技能（原生通路） |
|---|---|---|
| USB 库 | libusb（CyUSB3 驱动） | pyusb，失败时退回 `/dev/bus/usb` ioctl（无需 libusb） |
| 会话序列 | hello → 参数 → 触发 → 读流 | 相同，实测 `0x81 → 0x87 1 → 0x11 → 0x12 → 读 → 0x15` |
| 采样块布局 | 2048 B = 4×512 B 平面 → 16 位字 | 同（`usb.convert_to_pc`，按官方 `usb_base.cpp` 语义实现） |
| 真实采集模式 | `0x12` collectType=2 | 实测 ct=2 才输出真实通道数据；ct=0/3 输出内部图样 |
| 吞吐 | 1 MSa/s 连续（多 URB 并发） | 当前单 URB 轮询，实测仅约 15 kword/次 → **待优化** |

## 3. 协议解码方式对比（本次核心结论）

- **官方 GUI**：内置 209 个 sigrok 解码器（`decoders/`，`api_version = 3`），由 GUI 进程加载执行。
- **官方 CLI**：不做解码（手册 §9 明确“首版不支持协议解码”）。
- **本技能**：`pdhost.py` 用一个最小 `sigrokdecode` 模块**原地加载**GUI 的同一批解码器，
  因此 IR / UART / I²C / SPI / CAN / SWD 等能力与 GUI **同源同版本**，且支持堆叠
  （`--protocol uart+modbus`）、`--option` 传参、GUI 形状的 CSV 输出。
- 许可证边界：解码器是 GPL，**从未复制进本仓库**，运行时只按路径加载；本仓库仍为 Apache-2.0。

## 4. 结论

1. **解码层不需要自研**：复用 GUI 自带解码器的方案在真机样例上已通过（UART `ALIENTEK`、
   I²C EEPROM `0x50`、SPI `TM32 SPI TEST`、PWM 100 ns/30 %、NEC IR `0x00/0x45`）。
2. **采集层官方 CLI 有硬缺口**（滚动、多级/串行触发、PWM、毛刺过滤），
   这些只能走 GUI 或原生 USB；本技能已把原生协议的握手、参数、触发、停止、采样块解码跑通。
3. **当前差距**：原生读流的吞吐（多 URB 并发）和窗口深度控制，尚未达到 GUI 的 1 MSa/s 连续采集；
   这也是与官方 CLI 交叉比对只能做到“同量级”而非“逐样本一致”的原因。

## 5. GitHub 开源实现调研（按 star 数）

查询时间 2026-11，`gh api repos/<name>`：

| 项目 | ⭐ | 定位 | 与本技能的关系 |
|---|---|---|---|
| gusmanb/logicanalyzer | 5076 | 24 通道 100 Msps 分析仪（硬件 + .NET 上位机 + 自研解码器框架） | 参考其解码器接口设计；**不移植**（.NET） |
| DreamSourceLab/DSView | 1454 | Qt 多仪器软件，sigrok 派生 | 同类，可参考采集端实现 |
| sigrokproject/pulseview | 821 | sigrok 官方 GUI | 本机 GUI 即 sigrok 派生，同源 |
| wuxx/nanoDLA | 818 | 廉价 fx2lafw 分析仪硬件 | 与解码无关 |
| sigrokproject/libsigrok | 452 | 核心库 | 解码器由 libsigrokdecode 执行 |
| sigrokproject/libsigrokdecode | 148 | Python 协议解码器集合 | **本技能策略的来源**：GUI 自带的 209 个解码器即此集合 |
| saleae/AnalyzerSDK | 95 | 商业软件插件 SDK（C++ ABI） | 不采用，闭源运行环境 |

### 结论

1. 开源解码器分两派：**Python PD（sigrok）** 与 **自研框架（gusmanb C#、Saleae C++ SDK）**。
   本技能选 Python PD，因为它是唯一"现成、纯 Python、可原地加载"的一派。
2. GUI 自带的 209 个解码器即 `libsigrokdecode` 的厂商分支；必要时可用 `--decoders`
   指向上游 `libsigrokdecode` 目录做版本升级，不需要改代码。
3. 不移植 gusmanb/Saleae：语言与 ABI 成本高，而覆盖范围（UART/I²C/SPI/CAN/IR/SWD…）
   已被 sigrok 集合覆盖。
4. 硬件侧参考价值有限：本项目只对接 ATK-Logic，不涉及其他采集卡。
