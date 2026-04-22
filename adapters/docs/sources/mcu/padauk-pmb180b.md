# Padauk PMB180(B)

ID: `mcu/padauk-pmb180b`

## 用途

这个摘要用于支撑 `PMB180B` 的 chip-support / profile 落地，并为后续 `PMB180` 旧版差异化适配保留事实边界。

## 共享结论

- 内核定位：带充电管理的 `8-bit OTP MCU`
- 资源边界：`1.25KW OTP + 64B RAM`
- 时钟：内置 `IHRC 16MHz` 与 `ILRC 100KHz`
- 封装：`ESOP8`、`ESSOP10`
- IO：逻辑上 7 个 IO，`ESOP8` 只引出 `PA6/PA5/PA3/PA4/PA0`
- 定时资源：带 `Timer16`
- PWM 资源：带 `Timer2 PWM`，并额外带 `11-bit LPWMG0/1/2`
- 模拟资源：带 `GPC comparator`、`1.20V bandgap`、`LVDC`
- 能力缺口：当前手册未体现 ADC

## 当前已落地到仓库的关键信息

- `timer-calc` 已绑定 `Timer16`
- `pwm-calc` 当前只绑定 `Timer2 PWM`
- `lpwmg-calc` 已绑定 `LPWMG0/1/2` 共享频率与单通道占空比搜索
- `lvdc-threshold` 已绑定 `LVDC` 阈值档位与状态位解读
- `charger-config` 已绑定充电电流档位与 `CHG_CTRL/CHG_TEMP` 状态解码
- `comparator-threshold` 已绑定 `GPC` 的内部参考档位搜索
- `LVDC` 与充电能力现在已进入 tool device binding，可直接被工具调用
- 已额外补 `mcu/padauk-pmb180b-registers`，用于集中沉淀当前工具相关寄存器摘要

## 现已固化的坑点

- `5V` 输入判定不能只看 `CHG_TEMP.4`，必须同时满足 `CHG_TEMP.4 && CHG_TEMP.3`
- `PMB180` 老版本判满不能只看 `CHG_CTRL.0`
- 老版本快速判满至少需要 `CHG_CTRL.0 && V400_FG` 持续大于 `1s`
- 老版本也可按“4V以上继续充电时间”判满，当前工具按 `500mAh -> 1h` 的下限规则换算
- `PMB180B` 额外可用 `CHG_TEMP.1` 判满，但语义按实测修正为：高电平 `= 充电中`，低电平 `= 充电完成`
- `LVDC` 在充电中使用内部 `1.20V bandgap` 参考时，内部检测值通常比实际电池电压高约 `0.15V`
- `PMB180B` 的比较器在充电中也应考虑同类 `0.15V` 量级偏移风险

## PMB180 与 PMB180B 差异

- 两者共用同一份手册，封装与引脚排列一致
- `PMB180B` 新增充电完成状态位
- `PMB180B` 修正了旧版 `PMB180` 的 `VCC_Pin` 浮空微漏电问题

## 维护边界

- 这里只保留能跨 profile 复用的提炼事实
- 具体计算参数仍以 `extensions/tools/devices/pmb180b.json` 为准
- 如果后续补 `PMB180` 非 B 版本，不要直接复用 `VCC_Pin` 相关电气说明
