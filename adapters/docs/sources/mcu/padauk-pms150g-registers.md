# Padauk PMS150G Tool Registers

ID: `mcu/padauk-pms150g-registers`

## 用途

这个摘要只覆盖 `emb-agent-adapters` 当前已实现工具实际会用到的 `PMS150G` 寄存器和宏。

它不是完整寄存器手册。

## 覆盖范围

- `timer-calc`
- `pwm-calc`
- `comparator-threshold`

## Timer16

### `T16M`

- 用途：`Timer16` 模式、时钟源、预分频、中断位
- 当前工具使用点：
  - 时钟源：`SYSCLK` / `IHRC` / `ILRC` / `PA0` / `PA4`
  - 预分频：`/1` / `/4` / `/16` / `/64`
  - 中断位：`BIT8 ~ BIT15`
- 当前工具输出：
  - `$ T16M <clock>,/<prescaler>,BIT<interrupt-bit>;`

### `INTEGS`

- 用途：边沿触发方向
- 当前工具使用点：
  - `BIT_R`
  - `BIT_F`
- 当前工具输出：
  - `$ INTEGS BIT_R;`
  - `$ INTEGS BIT_F;`

### `stt16`

- 用途：向 `Timer16` 写入重装值
- 当前工具输出：
  - `stt16 <reload>;`
- 注意：
  - 当前工具按 ISR 中重装载的实际用法搜索，不是一次性 free-running 模型

## TM2 PWM

### `TM2C`

- 用途：TM2 时钟源、输出脚、PWM 模式、极性
- 当前工具使用点：
  - 时钟源：`SYSCLK` / `IHRC` / `ILRC` / `COMPARATOR` / `PA0_RISE/FALL` / `PA4_RISE/FALL`
  - 输出脚：`PA3` / `PA4`
- 当前工具输出：
  - `$ TM2C <clock>,<pin>,PWM[,Inverse];`

### `TM2S`

- 用途：TM2 分辨率、预分频、后分频
- 当前工具使用点：
  - 分辨率：`8BIT` / `6BIT`
  - 预分频：`/1` / `/4` / `/16` / `/64`
  - 后分频：`/1 ~ /32`
- 当前工具输出：
  - `$ TM2S <resolution>,/<prescaler>,/<divider>;`

### `TM2CT`

- 用途：TM2 计数寄存器
- 当前工具使用点：
  - 当前 route 固定输出 `TM2CT = 0;`

### `TM2B`

- 用途：TM2 周期/占空比相关寄存器
- 当前工具使用点：
  - route 输出候选上界值
- 注意：
  - 当前工具按现有 `TM2 PWM` 参数模型工作，未扩展到更复杂的 fixed-period 语义差异

## Comparator

### `GPCC`

- 用途：比较器使能、正负输入、同步/极性
- 当前工具使用点：
  - 正端：`P_R` / `P_PA4`
  - 负端：`N_PA3` / `N_PA4` / `BANDGAP` / `N_R` / `N_PA6` / `N_PA7`
- 当前工具输出：
  - `$ GPCC Enable[,Sync_TM2][,Inverse],<negative>,<positive>;`

### `GPCS`

- 用途：内部参考档位与可选输出
- 当前工具使用点：
  - 4 组内部参考公式
- 当前工具输出：
  - `$ GPCS [Output,]VDD*<numerator>/<denominator>;`

### `BANDGAP`

- 当前工具模型：
  - `1.20V`
- 坑点：
  - `bandgap` 不适用于比较器唤醒

## 维护边界

- 这里只保留“当前工具会碰到的寄存器摘要”
- 具体公式、宏名和候选值仍以 `extensions/tools/devices/pms150g.json` 与 `chip-support/algorithms/*.cjs` 为准
- 如果后续补更多 `PMS15x` 工具，再按同样方式增量补摘要
