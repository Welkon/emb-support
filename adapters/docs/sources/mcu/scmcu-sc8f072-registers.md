# SCMCU SC8F072 Tool Registers

ID: `mcu/scmcu-sc8f072-registers`

## 用途

这个摘要只覆盖 `emb-agent-adapters` 当前已实现工具实际会用到的 `SC8F072` 寄存器和配置字段。

它不是完整寄存器手册。

## 覆盖范围

- `timer-calc`
- `pwm-calc`
- `comparator-threshold`
- `adc-scale`

## TMR0

### `TMR0`

- 用途：8-bit 溢出计时器计数寄存器
- 当前工具使用点：
  - 软件重装载值搜索
- 当前工具输出：
  - `TMR0 = <reload>;`
- 注意：
  - 当前工具按“中断里回写 TMR0”模型计算
  - 未自动补偿写回 `TMR0` 带来的额外 2 个指令周期误差

### `OPTION_REG`

- 用途：`TMR0` 时钟源、边沿、预分频分配
- 当前工具使用点：
  - `T0LSE_EN`
  - `T0CS`
  - `T0SE`
  - `PSA`
  - `PS`
- 当前工具输出：
  - `OPTION_REG: T0LSE_EN=..., T0CS=..., T0SE=..., PSA=..., PS=...`

### `T0IF` / `T0IE`

- 用途：`TMR0` 中断标志与使能
- 当前工具输出：
  - `T0IF = 0; T0IE = 1;`

## TMR2

### `PR2`

- 用途：`TMR2` 周期寄存器
- 当前工具使用点：
  - 周期搜索结果直接写入 `PR2`
- 当前工具输出：
  - `PR2 = <period>;`

### `T2CON`

- 用途：`TMR2` 时钟源、预分频、后分频、使能
- 当前工具使用点：
  - `CLK_SEL`
  - `T2CKPS`
  - `TOUTPS`
  - `TMR2ON`
- 当前工具输出：
  - `T2CON: CLK_SEL=..., TOUTPS=..., TMR2ON=1, T2CKPS=...`
- 注意：
  - 当前结果按“中断输出周期”计算，不是仅基础计数周期

### `TMR2IF` / `TMR2IE`

- 用途：`TMR2` 中断标志与使能
- 当前工具输出：
  - `TMR2IF = 0; TMR2IE = 1;`

## PWM 10-bit

### `PWMCON0`

- 用途：PWM 时钟分频与各通道使能
- 当前工具使用点：
  - `CLKDIV`
  - `PWM0EN..PWM4EN`
- 当前工具输出：
  - `PWMCON0: CLKDIV=..., PWMxEN=1`

### `PWMCON1`

- 用途：PWM 输出脚组选择
- 当前工具使用点：
  - `PWMIO_SEL`
- 当前工具输出：
  - `PWMCON1: PWMIO_SEL=<group_bits>`

### `PWMTL` / `PWMTH`

- 用途：`PWM0~PWM3` 共用周期寄存器
- 当前工具使用点：
  - `PWMTL`
  - `PWMTH<1:0>`
- 当前工具输出：
  - `PWMTL = <low>;`
  - `PWMTH<1:0> = <high>;`

### `PWMT4L` / `PWMTH<3:2>`

- 用途：`PWM4` 独立周期寄存器
- 当前工具使用点：
  - `PWMT4L`
  - `PWMTH<3:2>`

### `PWMD0L..PWMD4L` / `PWMD01H` / `PWMD23H` / `PWMTH`

- 用途：各通道占空比寄存器
- 当前工具使用点：
  - `PWM0`: `PWMD0L + PWMD01H<1:0>`
  - `PWM1`: `PWMD1L + PWMD01H<5:4>`
  - `PWM2`: `PWMD2L + PWMD23H<1:0>`
  - `PWM3`: `PWMD3L + PWMD23H<5:4>`
  - `PWM4`: `PWMD4L + PWMTH<5:4>` 或 profile 定义的对应高位
- 坑点：
  - `PWM0~PWM3` 共用周期寄存器，`PWM4` 独立
  - 目标占空比为 `0%` 时，仅保持 `PWMEN` 可能仍出现最小脉宽；需要纯低电平时应关闭对应通道

## Comparator

### `CMPCON0`

- 用途：比较器正负输入、极性、输出使能、总使能
- 当前工具使用点：
  - `CMPPS`
  - `CMPNS`
  - `CMPNV`
  - `CMPOEN`
  - `CMPEN`
- 当前工具输出：
  - `CMPCON0: CMPPS=..., CMPNS=..., CMPNV=..., CMPOEN=..., CMPEN=1`

### `CMPCON1`

- 用途：模拟使能、内部 VR 偏置与档位
- 当前工具使用点：
  - `AN_EN`
  - `RBIAS_H`
  - `RBIAS_L`
  - `LVDS<3:0>`
- 当前工具输出：
  - `CMPCON1: AN_EN=1, RBIAS_H=..., RBIAS_L=..., LVDS=...`
- 坑点：
  - 内部参考不是单一寄存器值，而是 `RBIAS_H/RBIAS_L + LVDS` 联合决定
  - 当前 route 要求正端或负端之一必须使用内部 `VR`

## ADC

### 参考源

- 当前工具使用点：
  - `vdd`
  - `fvr2v`
  - `fvr1v`
- 当前工具输出：
  - 参考源建议与电压换算结果

### 通道

- 当前工具使用点：
  - `AN0~AN7` 及 profile 已列出的别名
- 当前工具输出：
  - 通道名、换算电压、目标码值
- 注意：
  - 当前摘要只覆盖工具用到的参考源/通道抽象，不展开完整 ADC 控制寄存器位表

## 维护边界

- 这里只保留“当前工具会碰到的寄存器摘要”
- 具体字段、别名和候选值仍以 `extensions/tools/devices/sc8f072.json` 与 `chip-support/algorithms/*.cjs` 为准
- 如果后续补更多 `SC8F0xx` 工具，再增量补摘要，不要复制整本手册
