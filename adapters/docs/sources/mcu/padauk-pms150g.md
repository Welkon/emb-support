# Padauk PMS150G

ID: `mcu/padauk-pms150g`

## 用途

这个摘要用于支撑 `PMS150G` 相关 family / device / chip profile，以及后续 `PMS15B/PMS150G` 低端族适配。

## 共享结论

- 内核定位：超低成本 `8-bit OTP MCU`
- 资源边界：ROM/RAM 很紧，适配必须坚持 ROM-first
- 定时资源：带 `Timer16`
- PWM 资源：带 `TM2 PWM`
- 模拟资源：带 `comparator`
- 能力缺口：不提供 ADC

## 当前已落地到仓库的关键信息

- `timer-calc` 已覆盖 `Timer16`
- `pwm-calc` 已覆盖 `TM2 PWM`
- `comparator-threshold` 已覆盖内部参考档位搜索
- `adc-scale` 明确返回 `unsupported`
- `chip profile` 已收录 `sop8`、`dip8`、`sot23-6`、`sot23-8`
- 已额外补 `mcu/padauk-pms150g-registers`，用于集中沉淀当前工具相关寄存器摘要

## 维护边界

- 这里只保留能跨 profile 复用的提炼事实
- 具体计算参数仍以 `extensions/tools/devices/pms150g.json` 为准
- 如果后续加入 `PMS152`、`PMS154` 等相近器件，应单独确认差异，不要直接照搬
