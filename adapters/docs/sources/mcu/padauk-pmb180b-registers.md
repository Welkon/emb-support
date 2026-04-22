# Padauk PMB180(B) Tool Registers

ID: `mcu/padauk-pmb180b-registers`

## 用途

这个摘要只覆盖 `emb-agent-adapters` 当前已实现工具实际会用到的 `PMB180(B)` 寄存器/宏。

它不是完整寄存器手册，也不是原始 datasheet 替代品。

## 覆盖范围

- `timer-calc`
- `pwm-calc`
- `lpwmg-calc`
- `lvdc-threshold`
- `charger-config`
- `comparator-threshold`

## Timer16

### `T16M`

- 用途：`Timer16` 模式/时钟来源/预分频/中断位配置宏
- 当前工具使用点：
  - 时钟源：`SYSCLK` / `IHRC` / `ILRC` / `PA0` / `PA4`
  - 预分频：`/1` / `/4` / `/16` / `/64`
  - 中断位：`BIT8 ~ BIT15`
- 当前工具输出：
  - `$ T16M <clock>,/<prescaler>,bit<interrupt-bit>;`

## TM2 PWM

### `TM2C`

- 用途：TM2 模式、时钟来源、输出脚、极性
- 当前工具使用点：
  - 时钟源：`SYSCLK` / `IHRC` / `ILRC` / `NILRC` / `COMPARATOR` / `PA0_R/F` / `PA4_R/F`
  - 输出脚：`PA3` / `PA4`
- 当前工具输出：
  - `$ TM2C <clock>,<pin>,PWM[,Inverse];`

### `TM2S`

- 用途：TM2 分辨率、预分频、后级分频
- 当前工具使用点：
  - 分辨率：`8BIT` / `7BIT` / `6BIT`
  - 预分频：`/1` / `/4` / `/16` / `/64`
  - 后级分频：`/1 ~ /32`
- 当前工具输出：
  - `$ TM2S <resolution>,/<prescaler>,/<divider>;`

### `TM2CT`

- 用途：计数寄存器
- 当前工具使用点：
  - 当前 route 固定输出 `TM2CT = 0;`

### `TM2B`

- 用途：周期/占空比相关上界寄存器
- 当前工具使用点：
  - route 输出候选周期寄存器值
- 注意：
  - 当前工具按现有 `padauk-tm2-pwm` 模型工作，后续若手册区分 PWM 模式和 fixed-period 模式更细，需要再补模式差异

## LPWMG

### `LPWMGCLK`

- 用途：LPWMG 总使能、共享时钟源、共享预分频
- 当前工具使用点：
  - 时钟源：`SYSCLK` / `IHRC`
  - 预分频：`/1` / `/2` / `/4` / `/8` / `/16` / `/32` / `/64` / `/128`
- 当前工具输出：
  - `$ LPWMGCLK Enable,/<prescaler>,<clock>;`
- 注意：
  - `IHRC*2` 目前在工具里通过传入实际 `clock-hz` 处理，不在宏名层单独分裂

### `LPWMGCUBH` / `LPWMGCUBL`

- 用途：三个 `LPWMG0/1/2` 共享的周期上限寄存器
- 当前工具使用点：
  - `LPWMGCUBH` 对应 `CB10_1[10:3]`
  - `LPWMGCUBL[7:6]` 对应 `CB10_1[2:1]`
- 当前工具输出：
  - `LPWMGCUBL = 0x..;`
  - `LPWMGCUBH = 0x..;`
- 坑点：
  - 三个通道共用周期寄存器，不能把每个通道当成独立 PWM block 来算

### `LPWMG0C` / `LPWMG1C` / `LPWMG2C`

- 用途：各通道输出选择、输出脚、极性
- 当前工具使用点：
  - `LPWMG0`: `PA0` / `PA1` / `PA5`
  - `LPWMG1`: `PA4` / `PA6`
  - `LPWMG2`: `PA3` / `PA5`
- 当前工具输出：
  - `$ LPWMGxC LPWMGx,<pin>;`
- 注意：
  - 反相输出当前只做提示，不强行生成固定参数顺序

### `LPWMG0DTL/H` / `LPWMG1DTL/H` / `LPWMG2DTL/H`

- 用途：各通道占空比寄存器
- 当前工具使用点：
  - `DTH` 对应 `DB10_1[10:3]`
  - `DTL[7:6]` 对应 `DB10_1[2:1]`
  - `DTL.5` 对应 `DB0`
- 当前工具模型：
  - 占空比分子按 `DB10_1 + DB0*0.5 + 0.5`
- 坑点：
  - 这是 half-step duty，不是普通整数 duty register

## LVDC

### `LVDC`

- 用途：低压检测阈值配置与检测结果读取
- 当前工具使用点：
  - `LVDC[7:2]`：阈值编码
  - `LVDC.0`：检测结果
- 当前工具模型：
  - 范围：`1.85V ~ 5.0V`
  - 步进：`0.05V`
  - 编码：`code << 2`
- 当前工具输出：
  - `LVDC = 0x..;`
- 状态解释：
  - `LVDC.0 = 1`：低于设定阈值
  - `LVDC.0 = 0`：高于设定阈值
- 坑点：
  - `LVDC` 不支持中断，也不支持唤醒
  - 充电中使用内部 `1.20V bandgap` 参考时，内部检测通常比实际电池电压高约 `0.15V`
  - 因此工具在 `--charging` 模式下会自动做 `+0.15V` 补偿搜索

## Charger

### `CHG_CTRL`

- 用途：充电电流档位配置；`bit0` 还可作为工作状态候选
- 当前工具使用点：
  - 电流档：`50 / 100 / 200 / 250 / 300 / 350 / 400 / 500mA`
  - `CHG_CTRL.0`
- 当前工具输出：
  - `$ CHG_CTRL <current>mA;`
- 坑点：
  - `CHG_CTRL.0` 不能单独用于判定充满
  - 老版本 `PMB180` 至少要结合 `V400_FG` 和持续时间

### `CHG_TEMP`

- 用途：充电状态相关只读位
- 当前工具使用点：
  - `CHG_TEMP.4`：`VCC > VBAT`
  - `CHG_TEMP.3`：`VCC` 电压正常
  - `CHG_TEMP.1`：`PMB180B` 充电完成指示
- 当前工具判定：
  - `5V` 输入存在：必须 `CHG_TEMP.4 && CHG_TEMP.3`
  - `PMB180B` 充满：`CHG_TEMP.1 = 0`
- 坑点：
  - 应广资料对 `CHG_TEMP.1` 的高低电平语义有写反的情况
  - 当前仓库按你的实测固化为：高电平 `= 充电中`，低电平 `= 充满`

### `V400_FG`

- 用途：4V 以上标志位
- 当前工具使用点：
  - 老版本 `PMB180` 判满辅助条件
- 当前工具判定：
  - 快速规则：`CHG_CTRL.0 && V400_FG && 持续时间 > 1s`
  - 时间规则：`4V` 以上继续充电一段时间；当前先按 `500mAh -> 1h` 的下限规则换算

## Comparator

### `GPCC`

- 用途：比较器使能、正负输入、同步/极性
- 当前工具使用点：
  - 正端：`P_R` / `P_PA4`
  - 负端：`N_PA3` / `N_PA4` / `N_PA6` / `N_PA7` / `BANDGAP` / `N_R`
- 当前工具输出：
  - `$ GPCC Enable[,Sync_TM2][,Inverse],<negative>,<positive>;`

### `GPCS`

- 用途：内部参考档位选择、可选输出
- 当前工具使用点：
  - 4 组内部参考公式
- 当前工具输出：
  - `$ GPCS [Output,]VDD*<numerator>/<denominator>;`
- 坑点：
  - 充电中内部参考检测也应考虑约 `0.15V` 量级偏移风险

## 维护边界

- 这里只保留“当前工具会碰到的寄存器摘要”
- 具体算法参数仍以 `extensions/tools/devices/pmb180b.json` 与 `chip-support/algorithms/*.cjs` 为准
- 如果后续新增未覆盖外设，再按同样方式增量补摘要，不要直接复制整本寄存器手册
