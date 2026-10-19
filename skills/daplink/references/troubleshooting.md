# 排错手册

按症状查。每条先给"最快验证"，再给"根因"。

## 探针不可见

`doctor` 的 `probes` 为空，或 `pyocd list` 输出 "No available debug probes are connected"。

1. **先确认是物理层还是软件层**
   ```bash
   lsusb | grep -i -E "dap|mbed|0d28|1209"
   ```
   没有设备 → 线、供电、USB 口问题。DAPLink 通常会被目标板供电或 USB 自供电，两种都要试。
2. **WSL**（`doctor` 里 `wsl: true`）
   USB 不会自动进 WSL。skill 会自动调用 Windows 侧的 `usbipd.exe` 探测设备：
   ```bash
   dap.py wsl status                 # Windows 侧设备 + 已知探针 + busid/状态
   dap.py wsl attach --busid 2-3     # 挂到 WSL（未 shared 会提示先 bind）
   dap.py doctor --attach            # 自动挂载第一个未挂载的已知探针
   ```
   首次或换口时需要管理员 PowerShell 执行一次 `usbipd bind --busid 2-3`；
   每次重新插拔/重启后都要重新 `attach`。`usbipd attach` 成功后 WSL 里才有 `/dev/bus/usb/...`。
   常见探针 VID：`0d28` DAPLink、`0483` ST-Link、`1366` J-Link、`1209` pid.codes。
3. **Linux 权限**
   ```bash
   ls -l /dev/bus/usb/*/* | head
   ```
   报 `LIBUSB_ERROR_ACCESS` / Permission denied → 装 udev 规则（见下），然后**拔插**探针。
4. **被别的进程占用**
   ```bash
   pgrep -a -f "pyocd|openocd|JLinkGDBServer|gdb"
   ```
   同一探针不能同时被两个 gdbserver 持有。先关掉旧的 `dap.py gdb --detach` 进程。

### udev 规则（Linux）

```bash
sudo tee /etc/udev/rules.d/60-daplink.rules >/dev/null <<'EOF'
# DAPLink / mbed CMSIS-DAP (HID + v2 bulk)
ATTRS{idVendor}=="0d28", ATTRS{idProduct}=="0204", MODE="0666", GROUP="plugdev"
# pid.codes 分配的开源探针
ATTRS{idVendor}=="1209", ATTRS{idProduct}=="c0de", MODE="0666", GROUP="plugdev"
# ST-Link (很多板子把它当 CMSIS-DAP 用)
ATTRS{idVendor}=="0483", ATTRS{idProduct}=="3748", MODE="0666", GROUP="plugdev"
ATTRS{idVendor}=="0483", ATTRS{idProduct}=="374b", MODE="0666", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

然后拔插探针，并确认用户在 `plugdev` 组（`groups`）。

## target not found

`-t stm32f103rc` 报 `TARGET_NOT_FOUND` / "target type not found"。

1. 名字必须和 `dap.py targets` 完全一致（大小写、后缀 `xE`/`xG`、`_XXAA` 风格因芯片而异）：
   ```bash
   dap.py targets --search gd32
   ```
2. 没装器件包：
   ```bash
   dap.py pack search <part>     # 例如 GD32F303CC、HC32F460KETA
   dap.py pack install <part>
   ```
   CMSIS-Pack 名和芯片型号不总是同名，`pack search` 支持模糊匹配。
3. pack 装上了但仍不认 → 用 `--pack /path/to/vendor.pack` 直接指定，绕过包索引。
4. 厂商完全没提供 pack（部分国产小厂）→ 换 OpenOCD 的 `target/*.cfg`，见 `engines.md#没有-pack-的芯片`。

## 烧录失败

典型输出：`Failed to erase/program`、`flash programming failed`、`Timeout while waiting for flash operation`。

按代价从低到高试：

1. **降频**：`--frequency 1000000`（默认可能 4–12 MHz，杜邦线长时不稳）。仍失败试 `500000`。
2. **换复位/连接方式**：`mem`/`regs` 支持 `--connect under-reset`；flash 场景先 `reset --halt` 再烧。
3. **先擦全片**：`erase --chip-erase`（会丢 bootloader，先确认用户接受）。
4. **读保护**：芯片被 RDP 锁住时，pyOCD 会报擦除失败或连不上。STM32 需要先解除 RDP（会全片擦除），这一步建议让用户用 STM32CubeProgrammer 或明确授权后再动 option bytes。
5. **低功耗/看门狗**：目标一上电就睡或反复复位，用 `--connect under-reset`，必要时在复位状态下烧录。
6. **SWD 引脚被固件复用**：固件把 PA13/PA14 改成 GPIO 后，普通 attach 连不上，只能用 `under-reset`。

## SWD 通信不稳

`WAIT`/`FAULT` 响应、随机 `transfer error`、烧录到一半断。

- 共地：探针 GND 必须和目标板 GND 直连，不要只靠 USB 地。
- 线长：SWDIO/SWCLK 超过 10 cm 就降频到 1 MHz 以下。
- 上拉：部分板子 SWDIO 需要 10k 上拉。
- 目标电压：确认探针 IO 电平和目标一致（1.8V 目标接 3.3V 探针会不稳）。
- 多探针时用 `-u <序列号>` 明确指定，避免连错板子。

## RTT 抓不到

`dap.py rtt` 无输出或报 "RTT control block not found"。

1. **固件必须包含 SEGGER RTT**（`SEGGER_RTT.c` + `SEGGER_RTT_printf`，且 `_SEGGER_RTT` 没被链接器裁掉）。纯 `printf` 重定向到 UART 的固件没有 RTT 控制块。
2. 控制块通常在 RAM 起始处，扫描需要时间：加大 `--duration`，或用 `-a 0x20000000` 指定起始地址。
3. 芯片刚复位时控制块还没初始化：先 `--duration 20`，或 `-M attach`（不重新扫描，直接附加到已有控制块）。
4. 低功耗模式下 RTT 会停：确认固件在跑，且没进 STOP/STANDBY。
5. RTT 缓冲区太小会丢日志：检查 `BUFFER_SIZE_UP`。

RTT 是"目标写、探针读"，不需要 UART；但如果固件同时用了 SWO/ITM，两者不要抢同一个 pin。

## GDB 连不上

- 端口占用：`ss -ltnp | grep 3333`，换 `-p 3334`。
- `--detach` 后进程已退出：看 `~/.local/share/daplink/gdbserver.log`。
- GDB 侧必须加载带符号的 ELF：`arm-none-eabi-gdb build/fw.elf -ex 'target extended-remote :3333'`。只连地址没有符号，断点只能按地址下。
- 复位后断点丢失：pyOCD 的 gdbserver 会重下软件断点；如果用了 `--persist` 仍异常，改用硬件断点。

## 常见错误串对照

| 错误串 | 含义 | 先做什么 |
|---|---|---|
| `No available debug probes are connected` | 探针不可见 | `lsusb` / `usbipd attach` / udev |
| `LIBUSB_ERROR_ACCESS` | 权限 | udev 规则 + 拔插 |
| `TARGET_NOT_FOUND` | target 名不对 | `targets --search` / `pack install` |
| `no memory region` | 地址不在映射内 | 检查链接脚本 / `--base` |
| `Failed to erase` | 读保护 / 低功耗 / 频率 | 降频 → `--connect under-reset` → 解锁 |
| `transfer error` / `WAIT` | SWD 信号质量 | 共地、短线、降频 |
| `RTT control block not found` | 固件没启用 RTT | 查 `SEGGER_RTT.c` / 指定 `-a` |
| `Address already in use` | gdbserver 端口冲突 | 换端口 / 杀旧进程 |
