# CACHIP Tool 协议逆向文档 (v1, 静态分析)

来源: `CACHIP_TOOL_4.1.3.exe` 静态逆向(未动态验证,标注 ⚠️ 处需抓包确认)

## 架构

```
PC (本驱动/官方GUI)  <--串口 or USB HID-->  CACHIP Tool 下载器  <--ISP-->  目标 MCU
```

- USB HID: `VID_FFCA PID_0125`,固定报告长度传输(数据不足补零)⚠️ 报告长度待确认(疑 64B)
- 串口: 裸字节流,波特率可选(9600/19200/38400/57600/115200/256000/460800/921600)
- 串口模式下帧边界机制 ⚠️ 待确认(可能固定长度或裸流)

## 帧格式

### 请求(PC → 下载器)

```
[0]  命令 ID (1B)
[1..] payload (命令相关,无长度字段,无校验和)
```

### 响应(下载器 → PC)

```
[0]  命令 ID 回显 (1B)
[1]  错误码 (1B), 0x00 = 成功, 非 0 = 错误
[2..] 数据 (命令相关)
```

错误时 PC 端报 "expected ID_xxx" 表示 ID 回显不匹配。

## 命令 ID 表

| ID | 命令 | 说明 | 帧 payload ⚠️ |
|----|------|------|----------------|
| 0x06 | Info | 读工具信息 | 空? 响应 [2]=状态 |
| 0x08 | Connect | 建立连接 | 4B 参数 + data(参数含义待确认) |
| 0x09 | Disconnect | 断开 | 空 |
| 0x0B | EraseTgtFlash | 擦除目标 Flash | 待确认 |
| 0x0C | WriteTgtFlash | 写目标 Flash | 待确认 |
| 0x0D | VerifyTgtFlash | 校验目标 Flash | 待确认 |
| 0x0F | WriteCache | 写缓存(下载器内) | `offset(4B LE) + data(≤58B)` |
| 0x10 | ScreenStatus | 屏幕状态 | 待确认 |
| 0x11 | TargetPower | 目标供电控制 | 待确认 |
| 0x13 | WriteEvent | 写事件 | 待确认 |
| 0x50 | TD_Connect | 触控: 连接 | 待确认 |
| 0x51 | TD_Disconnect | 触控: 断开 | 空 |
| 0x52 | TD_GetState | 触控: 状态 | 待确认 |
| 0x53 | TD_GetChannelCount | 触控: 通道数 | 待确认 |
| 0x54 | TD_GetRefChData | 触控: 参考通道数据 | 待确认 |
| 0x55 | TD_GetKeysFlagSN | 触控: 按键标志+SN | 待确认 |
| 0x56 | TD_GetBaselineData | 触控: 基准线数据 | 待确认 |
| 0x57 | TD_GetRawData | 触控: 原始数据 | 待确认 |
| 0x58 | TD_GetThresholdData | 触控: 阈值数据 | 待确认 |
| 0x59 | TD_SetThresholdData | 触控: 设置阈值 | 待确认 |
| 0x5A | TD_GetChannelNumber | 触控: 通道号 | 待确认 |
| 0x60 | FW_List | 固件列表 | 待确认 |
| 0x61 | FW_Info | 固件信息 | 待确认 |
| 0x62 | FW_Create | 创建固件槽 | 待确认 |
| 0x65 | FW_Delete | 删除固件槽 | 待确认 |
| 0x66 | FW_SyncCacheToFw | 缓存→固件 | 待确认 |
| 0x67 | FW_SetActive | 激活固件 | 待确认 |
| 0x68 | FW_SetKey | 设置密钥 | 待确认 |
| 0x69 | FW_SetMeta | 设置元数据 | 待确认 |
| 0x6C | FW_SetLimit | 设置次数限制 | 待确认 |
| 0x6D | FW_GetLimit | 读取次数限制 | 待确认 |
| 0x6E | FW_LimitInc | 增加次数 | 待确认 |
| 0xE0 | (升级辅助) | 升级辅助 | 待确认 |
| 0xE1 | UPGRADE_RD_MEM | 升级: 读内存 | 待确认 |
| 0xE2 | UPGRADE_WR_MEM | 升级: 写内存 | 待确认 |
| 0xE3 | UPGRADE_ERASE | 升级: 擦除 | 待确认 |
| 0xE4 | (升级辅助) | 升级辅助 | 待确认 |

## 已知行为细节

- **WriteCache 分块**: 数据按 ≤58B(0x3A)分块,每块单独一帧
  帧 = `0x0F + offset(4B LE) + chunk`,offset 为绝对偏移,连续递增
  每块发完即收响应(100ms 超时),响应 [2] 与期望值比较
- **超时**: Connect=5000ms, Disconnect=1000ms, 其余=100ms
- **HID 写**: 数据 < 报告长度时用 0x00 补齐后 WriteFile
- **HID 读**: 清空缓冲 → FlushFileBuffers → ReadFile(报告长度),错误 ERROR_OPERATION_ABORTED(0x3E5)时重试
- 传输层是 vtable 抽象(Serial / HidApiUSB 两实现),协议层无感知差异

## 动态验证结果 (2025, 完整烧录成功! OLED 显示"烧录成功 100%")

### 完整通信协议 (最终版)

**传输**: WriteFile 中断端点, 65 字节 = [0x00 report id] + [64B TEA 密文]
**加密**: TEA (密钥 13 5A 64 30 5A 5A 17 66 B0 50 0F 66 4D 0A 07 5F),
         明文填充到 64 字节, 8 块 ECB 加密

**烧录序列**:
1. 心跳 00 04
2. 10 00, 10 01+Checksum(4B), 10 02 01, 10 04 01
3. Connect: 08 + 型号ID(2B) + "5M" + 型号名+5x00 + 型号名+5x00
4. TargetPower 11 03, WriteEvent 13 01, 10 02 04, 进度0 (10 03 00)
5. Erase: 0B 02 000000
6. 写循环 ×109: 0F(写缓存: 0F+4B=0+0x20+32B数据) → 0C(写Flash: 0C+地址+0+0x20 0x00) → 进度 (10 03 N)
7. 进度100 → 10 02 07(校验中) → 进度0
8. 校验循环 ×109: 0D(校验: 0D+地址+0x20+期望数据) → 进度
9. 进度100 → Disconnect 09 → 10 02 05 → TargetPower off 11 00
   → OLED 显示"烧录成功 100%"

**固件处理**: Intel HEX 解析, 固件内空洞填 0x00, 尾部(最后一块不足32B)填 0xFF,
             再加一块全 0xFF (写入/校验 109 块覆盖到 0xD80)

### 状态码语义 (命令特有成功标志, 非 0x00=成功)

| 命令 | 成功状态码 | 实测 |
|------|-----------|------|
| Info (0x06) | 0xC0 | ✅ |
| Connect (0x08) | 0x41 | ✅ (目标板接入时) |
| EraseTgtFlash (0x0B) | 0x01 | ✅ |
| WriteCache (0x0F) | 0x00 | ✅ |
| WriteTgtFlash (0x0C) | 0x40 | ✅ |
| VerifyTgtFlash (0x0D) | 0x81 | ✅ |
| Disconnect (0x09) | 0x80 | ✅ |
| TargetPower (0x11) | 0x80 | ✅ |
| TD_GetChannelCount (0x53) | 0x00 | ✅ |

**完整烧录流程已验证**: 3434 字节固件通过驱动烧录后,
官方工具校验通过 ("The verification was successful.")!

流程: Connect → Erase → WriteCache(分块≤58B) → WriteTgtFlash → Verify

## 待动态验证清单

1. ⚠️ HID 报告长度(疑 64B)
2. ⚠️ 串口帧边界(固定长度? 长度字段?)
3. ⚠️ Connect 帧 payload 含义(4B 参数 + data)
4. ⚠️ 各命令 payload 布局(擦除/写Flash/校验/触控等)
5. ⚠️ 错误码语义(非 0 值的含义)
6. ⚠️ TD_* 通道数据长度(0x1E=30? 通道缓冲)
7. ⚠️ 加密固件格式(FW_SetKey 相关)

## 静态分析关键位置(供后续参考)

- 协议核心: `0x464590`(Connect), `0x4649f0`(Disconnect), `0x465200`(WriteCache)
- 命令函数区: `0x464000-0x471000`
- HID 传输: `0x472200`(write), `0x4722c0`(read)
- 串口库: `0x433000-0x434500`(win.cc 编译产物)
- CACHIPTool vtable: `0x5e55a0`

## 触摸调试协议 (Touch Debug, 2025 实测)

**通道**: 中断端点 WriteFile/ReadFile (hidapi 通用), 请求-响应 1:1, TEA 加密同烧录

**连接序列**:
```
51           TD_Disconnect      (清残留)
11 02        TargetPower 2      (关)
50           TD_Connect
11 03        TargetPower 3      → 响应: [11][电压2B LE]  (0x0149 = 3.29V)
10 04 03     调试模式           (烧录用 10 04 01)
52           TD_GetState        → [52][00][01] 已连接
53           TD_GetChannelCount → [53][00][通道数]  (1 = 1 个触摸键)
5A 01        TD_GetChannelNumber → [5A][00][01][通道号]  (03 = TK3)
58 00 CH     TD_GetThresholdData → [58][00][CH][门限 2B LE]  (500)
```

**轮询循环** (每轮 6 帧):
```
11 03        电源保持 → 电压
55           TD_GetKeysFlagSN   → [55][00][按键标志...]  (0=未按 1=按下)
58 00 CH     TD_GetThresholdData
56 00 CH     TD_GetBaselineData → [56][00][CH][基准值 2B LE]
57 00 CH     TD_GetRawData      → [57][00][CH][当前值 2B LE]
54           TD_GetRefChData    (参考通道)
```

**触摸判定** (实测): 差值 = 基准值 - 当前值; 触摸时 raw 暴跌 (~8100→177),
差值 (7881) ≫ 门限 (500) → 按键标志 = 1; 松开恢复 (~±50 内, key=0)

**响应格式**: 64B 明文 = [16B 数据] + [8B×6 重复填充];
数据 = [cmd][00][通道][值 2B LE][随机/序号...]

**TD_* 命令表**:
| 命令 | ID | 说明 |
|---|---|---|
| TD_Connect | 0x50 | 连接调试板 |
| TD_Disconnect | 0x51 | 断开 |
| TD_GetState | 0x52 | 状态 (01=已连接) |
| TD_GetChannelCount | 0x53 | 通道数 |
| TD_GetRefChData | 0x54 | 参考通道数据 |
| TD_GetKeysFlagSN | 0x55 | 按键标志 |
| TD_GetBaselineData | 0x56 | 基准值 |
| TD_GetRawData | 0x57 | 当前值 |
| TD_GetThresholdData | 0x58 | 门限值 |
| TD_SetThresholdData | 0x59 | 设置门限 (未抓包, 推测) |
| TD_GetChannelNumber | 0x5A | 通道号 |

**Linux 使用**: `python3 cachip_touch_debug.py --count 100 --interval 0.1`

## AI 自动调参 (ai_tune.py, 2025 实测成功)

**流程** (约 10 秒):
1. 连接 → 采集 5 秒未触摸数据 (σ 自动检测环境干净度)
2. 提示用户触摸 TK 键 3 次 (边沿检测, 自动记录按下时差值)
3. 计算最优门限 = (未触摸最大差值 + 触摸差值中位) / 2 (下限 100)
4. 在线写入 0x59 → 读回验证 → 可恢复原值

**实测数据** (TK3):
- 未触摸: 均值=8231, σ=9.1, 最大差值=17 (环境干净)
- 触摸: 差值 1685~1940 (触发清晰)
- 建议门限: 100 (原 500) → 写入验证 ✅

**要点**:
- 设备"残留锁死"只能靠重新插拔 USB 清除 (软件深清无效)
- 轮询间隔 ≥0.1s/帧 (过快会响应错位)
- 官方工具与自定义脚本不可同时连接 (抢设备)

## 门限贝叶斯寻优 (optimize.py, 实测)
- 一次采集 (未触摸 8s + 触摸 6 次) → 离线模拟所有门限 → 权衡曲线
- 输出: 门限 vs 误触率/触发率表 → 自动选优 → 0x59 在线写入
- 实测: 环境干净 (σ=7.6), 门限 23~1500 均 0% 误触 + >93% 触发
- 环境模式: dry/normal/wet (噪声余量 ×2/×3/×5)

## 触摸波形分析 (waveform.py, 实测)
- 快采样 (~30ms/帧): 只发 11 03 + 55 + 57 三命令
- 记录: 按下前 10 帧 + 按下期间 (时间戳) + 释放后分析
- 特征: 深度/达50%时间/持续时间/振荡率
- 分类: 轻点(<0.5s) / 长按(>1s) / 标准按 / 疑似误触(振荡>0.3 或缓按)
- 实测: 捕获 0.03s 轻点; 数据写入 wave_features.csv 可训练 ML
- 关键: 轮询间隔 ≥20ms; ring 持续滚动支持快速连点

## 手势识别 (waveform.py 进阶, 实测)
- 连点检测: 事件释放间隔 <0.6s = 连点 ⚡; <0.35s = 快速连点 ⚡⚡
- 实测: 单点(间隔 0.79s/1.33s)与连点(间隔 0.14s)完美区分
- 一个物理键 = 多功能: 轻点/连点/长按/标准按 + 误触排除(缓按/振荡)
- 特征 CSV 可训练 ML 分类器 (wave_features.csv)

## Writer / 软件管理 (固件管理器, 实测成功!)

**命令** (TEA 加密, 请求-响应 1:1):
```
FW_List:       60 [索引] → 60 00 [名1] 00 [名2]... (响应 = 从索引起的列表!)
FW_Info:       61 [名长][名] → 61 00 [大小4B][型号2B][槽地址4B]
FW_Create:     62 [名长][名][00×4][型号2B]["5M"][槽地址4B]
                槽地址: 0x0833E0 起始, 每个槽 +0xA780 (官方: 0x0833E0/0x08DB60)
FW_Delete:     63 [名长][名]  (必须先 SetActive! 状态 18 = 成功)
FW_SetActive:  65 [名长][名][00×16]
FW_SyncCache:  66 [名长][名][00×5][段偏移/256 2B][末段长度 2B(0=满段)][长度/256 2B][00×7]
FW_SetKey:     67 [名长][名]
FW_GetLimit:   69 [类型3/4/7][名长][名]
写缓存:        0F [地址4B][长度1B][数据]  (58B/帧, 512B/段 = 9帧)
```

**添加固件流程** (实测 3434B 固件成功!):
```
Create → [0F×9 缓存 + Sync(偏移 0,2,4...12)] × 7 → 完成
末段必须填 0xFF 到 512B (精确长度 >255 设备无响应!)
Info 大小 = 段数×512 (3584 = 含填充, 烧录无害)
```

**删除固件流程**: SetActive(65) → Delete(0x63) → 状态 18 = 成功!

**要点**:
- 槽地址自动分配 (0x0833E0 + N×0xA780), 每个固件唯一!
- 槽表满时 Create 状态 1 (需先删除!)
- 型号无关 (协议通用, Create 帧带型号即可)

## 烧录状态检查 (2025 实测, 修复"假成功"bug)
- 每个命令读响应, 状态字节 [1] == 0x00 = 成功!
- 心跳 (00): 响应 [1]=07 + 版本 "1.1.x" (不检查状态!)
- 电源 (11): 响应 [1:3] = 电压 2B LE (3.28V; <2V = 目标异常!)
- Connect (08): 响应 [2:4] = 型号回显 (必须匹配!)
- 擦除 (0B): 状态 00 = 成功!
- 0F/0C/0D: 状态 00 = 每块成功!
- deep_reset (51×3) 在新固件 v1.1.0.8 会导致连接异常, 默认流程已移除!

## 固件更新成功流程 (fw_update.py, 2025 实测通过!)
- 帧格式: [cmd] + [00] + [地址 4B LE] + [长度 1B] + [00] + [数据] (总长 ≤64!)
- E0(升级开始) → 心跳(00 07) → E4(只发不读!) → **延时2秒 + 重连设备(关键!)** → E3擦除 → E2写 → E1校验
- E4 后设备 USB 重枚举, 句柄失效必须重连!
- 更新成功后需拔插 USB 完全重启!
- 实测: 74扇区擦除 + 2733块写 + 2551块校验 ✅
- **完成命令: E4 00 = 退出升级模式 + 设备自动重启!** (校验后必须发!)
- 自动重启验证: 重连后发 10 00(正常模式命令!)确认!
- 完成后: E4 00 清升级标志 → 设备需物理拔插才完全重启 (USB禁用/启用不触发内部复位!)
- **设备重启机制**: E4 触发设备重启(OLED黑→LOGO, USB重枚举, 需重连!); E4 00 退出升级后设备也重启
- 官方自动重启 = USB 级复位; 软件禁用/启用不触发内部复位 → 完成后提示物理拔插!
- E1 校验范围 = 0x08005800-0x0802ACB0 (代码末尾, 尾部配置区不校验!)
- 重启方案测试: 禁用/启用/CM_Reenumerate 均不触发设备内部复位 (HID 无 USB 接口, IOCTL_USB_RESET 不可达)
- 最终: 完成后物理拔插 (官方 = 驱动级 USB 复位)
