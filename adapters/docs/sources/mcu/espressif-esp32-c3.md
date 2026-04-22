# Espressif ESP32-C3

ID: `mcu/espressif-esp32-c3`

## 用途

这个摘要用于支撑 `ESP32-C3` 的 family / device / chip profile 完整建模，优先沉淀芯片真值层，再在其上逐步补 executable tool binding。

## 共享结论

- 内核定位：`32-bit RISC-V` 单核 SoC，最高 `160 MHz`
- 存储边界：`384 KB ROM`，支持外接 SPI Flash；片上数据存储为 `400 KB SRAM + 8 KB RTC fast SRAM`
- IO 规模：常见型号可用 `GPIO` 最多约 `22` 个，具体引脚数随封装/型号变化
- 定时资源：至少包含 `2 x 54-bit` 通用定时器与 `1 x 52-bit` systimer
- PWM 资源：带 `LEDC PWM`，可提供 `6` 个输出通道
- 通信资源：带 `UART`、`SPI`、`I2C`、`I2S`、`TWAI`、`RMT`、`USB Serial/JTAG`
- 模拟资源：带 `12-bit SAR ADC` 与片上温度传感器
- 系统资源：带 `watchdog`、`GDMA`、`GPIO matrix`、`IO MUX`
- 电源相关：带 `PMU`、`brownout detector`、`RTC` 保活与多类唤醒源
- 无线资源：带 `Wi-Fi` 与 `BLE`
- 安全资源：带 `AES`、`SHA`、`RSA`、`HMAC`、`RNG`、`eFuse`、Flash encryption
- 能力缺口：无独立硬件 `comparator`，无内置 `charger`

## 外设分组

### 通信

- `UART`：2 个控制器
- `SPI`：含 Flash 相关 SPI 与 1 个通用 GP-SPI
- `I2C`：1 个控制器
- `I2S`：1 个控制器
- `TWAI`：兼容 CAN 2.0
- `RMT`：2 发 2 收
- `USB Serial/JTAG`：全速 USB 2.0 调试/下载路径

### 系统

- `LEDC`：6 路 PWM
- `TIMG`：2 个 54-bit 通用定时器
- `SYSTIMER`：1 个 52-bit 系统计时器
- `Watchdog`：多类数字/模拟/XTAL32K watchdog
- `GDMA`：共享给 SPI2、I2S、AES、SHA、ADC 等外设
- `GPIO Matrix`：外设信号与物理引脚高度可重映射

### 模拟

- `ADC`：2 个 12-bit SAR ADC，常用以 `ADC1` 为主
- `Temperature Sensor`：片上温度传感器
- `Brownout`：供电跌落检测与中断/复位保护

### 电源与低功耗

- 睡眠模式：`Active`、`Modem-sleep`、`Light-sleep`、`Deep-sleep`
- 主要时钟：`XTAL`、`PLL`、`RC_FAST`、`RC_SLOW`、`XTAL32K`
- `RTC fast SRAM`：Deep-sleep 下可保持，用于 wake stub / 快速唤醒
- 唤醒源：GPIO、RTC timer、32k 晶振相关源；Light-sleep 还可由 Wi-Fi / BLE / UART 唤醒

### 安全

- `AES`、`SHA`、`RSA`、`HMAC`
- `RNG`
- `eFuse`
- `Flash Encryption`
- `Assist Debug`

## 当前已落地到仓库的关键信息

- 已新增 `ESP32-C3` 的 chip profile
- 已新增带完整 `QFN32` 主封装引脚表的 chip profile
- 已新增主要 `GPIO0-GPIO21` 逻辑引脚摘要
- 已新增 `Espressif ESP32-C3` family / device 占位 profile
- 当前已落地 `timer-calc`、`pwm-calc`、`adc-scale` 三条基础 executable binding
- 当前 executable 重点覆盖 `GPTimer`、`LEDC`、`SAR ADC` 的一阶可执行计算，不代表芯片全部外设都已适配完成
- 对 emb 现有其余 route 面，当前已明确收口：
  - `comparator-threshold`：`ESP32-C3` 无独立模拟 comparator
  - `charger-config`：无片上 charger / 充电管理模块
  - `lvdc-threshold`：brownout 仅保留能力事实，不具备可直接计算的用户离散阈值表
  - `lpwmg-calc`：无独立 LPWMG 外设，低功耗 PWM 场景仍归 `LEDC`
- 当前知识摘要来自 notebook 对 `esp32-c3_datasheet_cn.pdf` 与 `esp32-c3_technical_reference_manual_cn.pdf` 的提炼

## 维护边界

- 这里只保留可跨 profile 复用的提炼事实
- `related_tools` 不代表芯片能力全集，只代表 emb 当前值得优先推荐的工具入口
- 若继续深化 `LEDC`、`GPTimer`、`SAR ADC` 适配，应补更细的寄存器级摘要、校准参数与 SDK/寄存器双视图说明
- 如果后续扩 emb 工具面，应优先考虑 `uart`、`spi`、`i2c`、`rmt`、`twai`、`gpio-matrix`、`power/clock`
- brownout 目前只作为芯片能力记录，不等于已经适配 `lvdc-threshold`
