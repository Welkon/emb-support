---
name: cachip
description: CACHIP MCU 烧录器工具链 — 通过 TFT 仿真下载器(STM32F103, VID 0xFFCA/PID 0x0125)烧录 CA51M550S1B 等触摸 MCU、触摸调试(TK3 实时数据/门限)、Writer/软件槽管理、下载器固件升级与定制(版本字符串)、AI 自动调参。Use when the user asks to burn flash a target MCU, touch-channel debugging/calibration (baseline/raw/threshold), firmware slot management, or update/customize the CACHIP downloader firmware.
---

# CACHIP 烧录器工具链

通过 TFT 仿真下载器(USB HID, VID 0xFFCA / PID 0x0125)与目标板交互。设备实体是 STM32F103 高密度 MCU + SPI Flash + OLED/TFT 彩屏;目标板典型为 CA51M550S1B(TK3 触摸,通道号 3)。协议为厂商自定义 HID(64B report,单字节命令)。

**脚本运行环境**:Windows 上需 `hidapi` 的 Python 绑定(`pip install hidapi`);Linux 需 libusb 权限(udev rule,见 LINUX_DEPLOY.md)。所有脚本 `sys.path` 同目录即可互相 import。

## 工具清单(`scripts/`)

| 脚本 | 功能 |
|---|---|
| `cachip_burner.py` | 烧录目标固件(hex): Connect(型号回显+电压检查)→擦除→写→校验;每条命令校验状态字节 |
| `cachip_touch_debug.py` | 触摸调试库: TD_Connect/GetState/GetChannelCount/GetBaselineData/GetRawData/GetThresholdData/SetThresholdData;也可作 CLI |
| `fw_manager.py` | Writer/软件管理: FW_List(0x60)/Info(0x61)/Create(0x62)/Delete(0x63)/SyncCache(0x66)/SetKey(0x67)/GetLimit(0x69) |
| `fw_update.py` | 下载器固件升级/还原(完整时序,见下) |
| `ai_tune.py` | AI 标定: 采集基线(手拿开)→采集触摸(按 3 次)→建议门限→在线写入并验证 |
| `optimize.py` | 门限贝叶斯寻优(权衡曲线 + 离线模拟) |
| `waveform.py` | 波形分析: 快采样 + ASCII 波形 + 轻点/长按/连点/误触分类 |
| `mcu_table.py` | 160+ 目标芯片型号表(hex→型号映射,0x028F=CA51M550S1B) |
| `PROTOCOL.md` | 完整协议文档(命令表/帧格式/时序) |

## 快速使用

```bash
# 烧录(先 Connect 目标板;hex 或 bin 均可)
python cachip_burner.py target.hex --name CA51M550S1B

# 触摸调试(实时数据流)
python cachip_touch_debug.py --count 10 --interval 0.1

# AI 标定(用户配合: 第一步手拿开, 提示后按 TK3 三次, 每次1秒)
python ai_tune.py

# Writer 软件槽列表/删除/创建
python fw_manager.py list

# 下载器固件更新(升级/还原/定制后刷入)
python fw_update.py update CACHIP_TOOL_v1.1.0.8_20260507.bin
```

## 协议要点(实测验证)

- **固件更新帧**: `[cmd]+[00]+[地址4B LE]+[长度1B]+[00]+[数据]`,总长 ≤64(E2 正好 64B;前缀 1B,2B 会截断丢数据)。
- **固件更新时序**: E0(升级开始)→心跳→E4(只发不读)→延时 2s 重连(USB 重枚举,句柄失效!)→E3(2KB 扇区擦除)→E2(写块 56B)→E1(校验 60B 到 0x0802ACB0)→E4 00(清升级标志)→**物理拔插**(软件无法触发 MCU 内部复位)。
- **状态校验**: 心跳(0x00)不查状态;电源(0x11)看电压>2V;其余命令响应 `[1]==0x00` 才算成功。Connect 响应 = 型号回显 `[2:4]`,响应慢(>3s),超时 10s。
- **触摸响应**: `cmd+00+通道+值 2B LE`;TK3 实测 raw ≈ 8100-8300,基线自动跟踪,门限默认 500。
- **Writer 槽地址**: 0x0833E0 起始 + 0xA780 间隔(SPI Flash)。

## 经验教训(每条都曾翻车)

1. **固件字符串替换必须等长**(填充到原长度,再校验固件总长度 assert)——不等长会让固件错位 → **变砖**,需 ST-Link 全片擦除重刷。
2. **长字符串**(>原长度): 挪到空数据区(固件区 0x5804 的 0xFF 空洞)+ 改指针(版本指针在池 0xFAFC)。
3. **deep_reset(51×3)在新固件会导致连接异常** → 默认流程移除,`connect(deep=False)`。
4. **设备半恢复**(CM_Reenumerate 后): 10 00 响应状态 9D/F1/E3/B8 等非 0 → 需物理拔插。
5. **官方工具和脚本不能同时连**(设备独占);Frida/python 残留进程需清理。
6. **升级失败会变砖**(OLED 显示升级模式或黑屏) → ST-Link 救砖: NUCLEO-C031C6 板载 ST-Link(SWDIO/SWCLK/GND/VDD)+ STM32CubeProgrammer 全片擦除 → 下载 bin @0x08000000。
7. 烧录必须检查电压 + 状态字节(不能只看 Connect 成功)。

## 固件定制(已验证)

- 版本字符串 @0x0293BA("VER1.1.0"→"VER1.2.0" 等长替换即可)。
- 开机 LOGO: 上=CACHIP(红)、中=公司名(白)、下=版本;LOGO 图片数据未定位(疑在外置 SPI Flash 出厂区,需拆机确认 W25Q 芯片)。
- 改 bin → `fw_update.py update` 刷入 → 拔插生效(任何定位到的数据都能改)。
- 固件备份: `scripts/CACHIP_TOOL_v1.1.0.8_20260507.bin`(官方原版 175,544B)。

## 目标板触摸标定(标准流程)

1. `python ai_tune.py` 一键标定(基线 σ<5 为优;触摸差值/2 + 噪声裕量 = 建议门限)。
2. 门限写入为**运行时设置**(重启恢复固件默认 500);固化需改固件默认门限表或研究 SPI Flash 保存机制。
3. 验证: 读门限(0x58 00 ch)→按 TK3→看 key flag=1 且差值>门限。
