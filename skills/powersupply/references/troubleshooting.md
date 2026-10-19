# 排错

## 找不到仪器

1. **LAN**：`ping <ip>`；端口默认 5025；确认电源已启用 LAN/SCPI；防火墙放行。
   ```bash
   scripts/psu.py scpi --host <ip> "*IDN?" --query
   ```
2. **USB**：`lsusb`、`ls /dev/usbtmc*`；Linux 权限跑 `scripts/install_udev.sh`；WSL 先 `usbipd attach --wsl`。
3. **串口（Korad）**：确认 `/dev/ttyUSB0` 或 `COM3`，波特率 9600；有些克隆芯片需要 `--baud 9600` 且关闭流控。
4. **VISA 资源**：`scripts/psu.py discover`；多个仪器时用 `--resource` 指定。

## DP100 在 Linux / WSL 上

- 确认设备：`lsusb | grep 2e3c`，正常是 `2e3c:af01`。
- 确认节点：`ls -l /dev/hidraw*`；没有节点说明内核没绑定 HID 或设备没插好。
- 权限：运行 `scripts/install_udev.sh`（含 DP100 的 hidraw 规则），然后拔插。
- Python 依赖：`psu.py setup` 会装 `hidapi`；源码安装失败时先装
  `sudo apt install libhidapi-dev libusb-1.0-0-dev`。
- WSL：先 `usbipd attach --wsl --busid X`；如果 HID 设备无法 attach，改用原生 Linux。
- 独占：官方 ATK-DP100 上位机运行时可能占用 HID，先关闭再跑本 skill。
- 若一直“无响应”，驱动会返回 HID timeout 错误（不会挂住）；检查线缆/权限/占用。

## 能连上但读数为 0

- 输出未开：`output on --yes`。
- 通道错误：多输出型号先 `channels`，再 `--ch`。
- 远端 sense / 本地 sense 接错：读数会偏低或为 0。
- Korad 克隆固件对大小写敏感，确认命令为 `VOUT1?` 而不是 `VOUT1 ?`。

## set 成功但实际电压不对

- 电源处于 remote sense，线损补偿导致端子电压与显示不同。
- 电流限值设得太低，电源进入 CC 模式，电压被拉低。
- `--verify` 会回读设定值；如果回读不一致，检查型号方言（`--family`）是否正确。
- 某些型号设定后需要 `:OUTPut ON` 才真正加载。

## 输出打不开

- OVP/OCP 已触发：先清除保护（`scpi` 发送型号对应命令或断电重启）。
- 过温/过载保护。
- 通道被 tracking/并联模式占用。
- Keysight 多输出型号必须先 `:INSTrument:NSELect`；本 skill 已自动处理。

## 斜坡/序列中断

- 触发上限会立即停止；查看 JSON 错误。
- 异常时 `safe_off`（默认开）会关闭输出。
- 想保留输出：`config set safe_off false`（不推荐）。

## 读数噪声/跳变

- 缩短采样间隔会增加噪声；`log --interval` 建议 ≥0.2 s。
- 电子负载/脉冲负载下，电源显示值与万用表可能差很多，优先看 `measure` 的原始读数。
- 需要更精确时用 `scpi` 直接读型号的高分辨率测量命令。

## 安全

- 先设电压/电流，再开输出；关闭时先 `output off` 再断开负载。
- 带电池/大电容时，关输出后端子仍带电。
- OVP/OCP 是软件层，不能替代硬件限流、保险丝和正确的线径。
- 无人值守的 ramp/sequence 不要超过电源和负载的额定值。
