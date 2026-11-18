# 原生 USB 通路（无厂商 CLI）

`atkla.py usb` 直接驱动分析仪：`info`（只读握手）、`capture`（采集 + 解码 + 统计）、
`config`（只发配置，用于排查）、`frame`（离线打印将要发送的字节）。

## 传输

- pyusb 优先；没有 libusb 时自动退回 `/dev/bus/usb/BBB/DDD` 的 `USBDEVFS_BULK` ioctl
  （端点由 sysfs 发现，`in=0x81 / out=0x01`）。
- udev 规则：`scripts/install_udev.sh`（`04b4:6a6a`、`1a86:6a6b`、`1a86:ffcc`）。
- WSL 里需要 `usbipd bind --busid <id>` + `attach --wsl`；交回 Windows 时必须
  `usbipd unbind` **并拔插一次**，否则厂商驱动握手报 `state 2`。

## 会话序列（缺一步都不出数据）

```
0x81 hello → 0x87 1 (唤醒 FPGA) → 0x11 参数 → 30 ms → 0x12 触发 → 读流 → 0x15 停止
```

`0x11` 无应答（正常），`0x12` 回 `0a 04 04 …` 状态包后开始出流。

## 0x12 触发负载（厂商布局，17 字节）

每个通道对 1 字节：偶数通道高半字节、奇数通道低半字节，
`0x8|code` 使能（`1` 上升、`2` 下降、`4` 高电平、`0` 低电平），`0x7` 表示不关心/不采集；
最后一字节 = 1 表示**立即采集**（没有触发条件时）。少了这个字节，设备只回心跳包。

## 采样流布局（实测）

```
0a | type | len(2 LE) | 10 B 元数据 | 通道(2 LE) | 样本(len-2 字节) | 00 0b
实际总长 = len + 16，type 1 为通道数据
每字节 8 个采样，LSB 最早
```

## 实测校准（示波器校准源，仅 ch2 接线）

| 采样率 | 样本数 | 占空比 | 频率 | 说明 |
|---|---|---|---|---|
| 2 MHz | 200 064 | 49.97 % | — | 样本数 = 采样率 × 时长 |
| 10 MHz | 1 000 064 | 50.07 % | 994.8 Hz | 与厂商 CLI（50.07 %、990 Hz）一致 |

- 频率必须用**边沿间隔的中位数**，不能用 `边沿数/2/时长`。同一份 10 MHz 原始数据
  （1 000 064 采样，ch2，上升沿 124 个）的四种口径：

  | 口径 | 结果 |
  |---|---|
  | 边沿数 / 2 / 时长 | 1234.9 Hz（受 23 个 2-sample 毛刺污染） |
  | 上升沿间隔中位数 | **994.7 Hz** |
  | 下降沿间隔中位数 | 994.7 Hz |
  | 过零点（半周期）中位数 ×2 | 998.0 Hz |

  厂商 CLI 同信号为 990 Hz，差距 0.5 %，属源/时基误差范围；`usb capture` 输出里的
  `glitches` 字段就是被排除的短间隔个数（本次 23）。
- 通道映射是 0 基（协议通道 2 = 面板 CH2）；只接一路时只有那一路有数据。

## 吞吐：瓶颈在设备，不在传输

同一根 ch2 线、10 MHz / 100 ms 配置下，两种传输拿到的字节数完全相同：

| 传输 | 数据量 | 速率 |
|---|---|---|
| usbfs `USBDEVFS_BULK`（64 KB 读） | 131 728 B / 1.39 s | 0.09 MB/s |
| libusb（pyusb，256 KB 读） | 131 772 B / 2 s | 0.07 MB/s |
| usbfs 4 线程并发 | 131 728 B / 2 s | 0.07 MB/s（其余线程饿死） |

结论：`USBDEVFS_BULK` 一次 ioctl 只完成一个 URB，但换 libusb、加线程、加读块都没有
提升——数据量由设备出数节奏决定。多 URB 流水线不是当前瓶颈。

## 没有系统 libusb 时怎么用 pyusb

不需要 sudo，用代理下载 deb 并解压到用户目录：

```bash
cd /tmp && mkdir -p libusb && cd libusb
apt-get -o Acquire::http::Proxy=http://127.0.0.1:7890 \
          -o Acquire::https::Proxy=http://127.0.0.1:7890 download libusb-1.0-0
dpkg-deb -x libusb-1.0-0_*.deb root
export ATK_LOGIC_LIBUSB=/tmp/libusb/root/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0
```

`ATK_LOGIC_LIBUSB` 会让 `atkla.py usb ...` 通过该库加载 pyusb 后端；不设时行为不变
（系统 libusb 优先，缺失则退回 usbfs ioctl）。
