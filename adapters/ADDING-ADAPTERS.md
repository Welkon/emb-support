# Adding Chip Support

## 推荐顺序

1. 定义 family
2. 定义 device
3. 定义 chip
4. 在 chip profile 里补 `packages / pins`
5. 在 device/family profile 里声明 `bindings`
6. 只有现有算法不够时才新增算法文件
7. 优先复用已有 route；只有工具入口分发模型不兼容时才修改 route

## 推荐贡献流程

1. 先同步或确认你本地的 `emb-agent` 引擎可用
2. 在当前仓库根目录执行 `npm run generate -- --from-project --project /abs/path/to/project`
3. 检查生成的 `extensions/**` 和 `chip-support/routes/**` diff
4. 必要时手工补算法参数、证据、`notes`、`source_refs`、`component_refs`
5. 执行 `npm run validate`
6. 提交 PR，等待维护者审核

如果不是从项目真值生成，也可以改用：

```bash
npm run generate -- --from-doc <doc-id> --project /abs/path/to/project --vendor Padauk
```

生成入口本身不实现推断逻辑，只是调用 `emb-agent` 的 `adapter generate` 引擎。

## 需要补哪些文件

例如新增某个 `vendor-family`：

```text
extensions/tools/families/vendor-family.json
extensions/tools/devices/vendor-device.json
extensions/chips/profiles/vendor-chip.json
chip-support/routes/timer-calc.cjs
chip-support/routes/pwm-calc.cjs
chip-support/routes/lpwmg-calc.cjs
chip-support/routes/lvdc-threshold.cjs
chip-support/routes/charger-config.cjs
chip-support/routes/comparator-threshold.cjs
chip-support/routes/adc-scale.cjs
```

上面的 route 文件是“该工具在 catalog 中的固定入口位”，不是“新增一颗芯片就要复制一套”。

不是所有工具都必须实现。只实现该芯片真正相关的工具即可。

如果只是参数不同，通常既不需要新增 route，也不需要新增算法文件，只需要在 profile 的 `bindings` 里给现有算法喂参数。

`chip profile` 建议额外维护两层真值：

- `packages`
  封装级物理引脚表，例如 SOP8/QFN16 各自 Pin1..PinN 对应什么信号
- `pins`
  逻辑 pad 能力表，例如 `ra0` 支持哪些复用、在哪些 package 上落到几号脚、是否带外部中断

另外建议补两类轻量引用：

- `source_refs`
  指向 `docs/sources/mcu/*.md` 这类 MCU/手册提炼摘要
- `component_refs`
  指向 `docs/sources/components/*.md` 这类具体外围器件型号摘要

这两个字段只放 ID，不放长说明文本。

`component_refs` 只引用具体型号摘要，例如 `components/<part-number>`。

只有当某个具体器件在多个项目里重复出现，而且它的极性、时序、输出形式、保持时间或供电约束会直接影响 agent 判断时，才值得补进 `docs/sources/components/`。

如果你只有“这类器件通常如此”的经验结论，不要写成共享真值；这类内容更适合留在项目侧事实或 agent 推理里，而不是沉淀到共享 catalog。

## chip-support 返回约定

建议至少返回：

- `tool`
- `status`
- `implementation`
- `chip_support_path`
- `route`
- `inputs`
- `notes`

如果已经算出结果，再补：

- `outputs`
- `candidates`
- `warnings`
- `register_hints`

## 失败时不要做什么

- 不要编造寄存器值
- 不要假装支持某个 family/device
- 不要因为缺少路由就返回 `ok`

缺少实现时，明确返回 `route-required` 或更具体的错误更安全。
