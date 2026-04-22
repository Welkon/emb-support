# Sources

`docs/sources/` 用来放可复用的“提炼后知识”，不是原始资料归档区。

这里适合放：

- MCU 手册提炼摘要
- 封装/引脚/外设限制摘要
- 常用外围器件约束摘要
- 具体型号元器件的高复用摘要
- 生成 chip-support/profile 时需要反复引用的共享结论

这里不适合放：

- 原始 PDF
- 大体积扫描件
- 项目私有调试记录
- 只能服务单一项目的一次性草稿

## 引用方式

建议在 `extensions/**/*.json` 里使用：

- `source_refs`
- `component_refs`

这两个字段只放 ID，不内联长文本。

例如：

```json
{
  "source_refs": ["mcu/scmcu-sc8f072"],
  "component_refs": ["components/<part-number>"]
}
```

对应文件路径形式：

- `docs/sources/mcu/scmcu-sc8f072.md`
- `docs/sources/components/<part-number>.md`
- `docs/sources/components/tq322.md`

## components 目录建议

`docs/sources/components/` 只放具体型号摘要：

- `<part-number>.md`
  放某个高频、跨项目复用的具体型号摘要，例如 `vs1838b`、`hx1838`、`hc-sr501`

推荐原则是：

1. 只有具体型号在多个项目反复出现时，才补进这个 catalog
2. 如果只有“这类器件通常如此”的泛化结论，不要写成共享真值
3. 如果某型号只是单项目一次性出现，不要急着进这个 catalog

具体型号文档适合记录：

- 明确的引脚名/极性
- 电源电压范围
- 输出类型
- 时序或保持时间
- 与 MCU 选型/引脚/定时器/唤醒能力直接相关的约束

不建议新增：

- 类别级摘要文件
- 只表达“大多数器件如此”的泛化结论

不建议记录：

- 大段 datasheet 摘抄
- 单个项目私有焊接经验
- 不会影响 agent 判断和 tool 选择的低信息量参数

## 设计目标

- 让 chip-support/profile 有轻量可追溯来源
- 避免每次生成都重新通读整份手册
- 不把 chip-support catalog 膨胀成资料仓库
- 让维护者能审核“结论”而不是审核整份 PDF
