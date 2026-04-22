# SCMCU SC8F072

ID: `mcu/scmcu-sc8f072`

## 用途

这个摘要用于支撑 `SC8F072` 相关 family / device / chip profile，以及后续同系列派生适配。

## 共享结论

- 内核定位：8-bit Flash MCU，适合小型裸机控制与低成本家电/照明/通用控制场景
- 定时资源：至少包含 `TMR0` 与 `TMR2`
- PWM 资源：带独立 `10-bit PWM`
- 模拟资源：带 `comparator` 与 `12-bit ADC`
- 低功耗：支持 `sleep-wakeup`

## 当前已落地到仓库的关键信息

- `timer-calc` 已覆盖 `TMR0` 与 `TMR2`
- `pwm-calc` 已覆盖独立 `10-bit PWM`
- `comparator-threshold` 已覆盖内部参考阈值搜索
- `adc-scale` 已覆盖 `12-bit ADC` 基础换算
- `chip profile` 已收录多种封装，包括 `sot23-6`、`sop8`、`msop10`、`sop14`、`sop16`、`qfn16`
- 已额外补 `mcu/scmcu-sc8f072-registers`，用于集中沉淀当前工具相关寄存器摘要

## 维护边界

- 这里只保留提炼后的共享事实
- 具体寄存器位、route 选择和算法参数仍以 `extensions/**/*.json` 与 `chip-support/**/*.cjs` 为准
- 如果后续补同系列器件，优先复用本摘要，再按芯片差异补充新的 source 文档
