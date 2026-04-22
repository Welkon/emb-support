# Repo Contract

这个仓库必须满足当前 `emb-agent support sync` 的 source 合同。

## 三层分类

仓库只保留三层主分类：

- `chip-support/`
  可执行能力
- `extensions/`
  芯片与工具定义
- `docs/sources/`
  轻量知识摘要

如果这三层之外再长出新的“主分类”，通常说明分类又散了。

## 会被同步的内容

会被同步到目标项目或 runtime 的只有这些：

- `chip-support/**/*.cjs`
- `extensions/tools/specs/*.json`
- `extensions/tools/families/*.json`
- `extensions/tools/devices/*.json`
- `extensions/chips/profiles/*.json`
- `extensions/chips/devices/*.json`
- `docs/sources/**/*.md`

## 不会被同步的内容

这些内容只用于仓库维护，不会进入目标项目：

- `README.md`
- `docs/ADDING-ADAPTERS.md`
- `docs/REPO-CONTRACT.md`
- `package.json`
- `scripts/`
- `tests/`
- 任何不在上面同步名单里的自定义文件

## 目录布局要求

仓库根目录必须至少命中以下任意一项：

- `chip-support/`
- `extensions/tools/`
- `extensions/chips/`

否则 `support sync` 会判定 source layout 无效。

## 命名约束

- route 文件名必须等于工具名，例如 `chip-support/routes/timer-calc.cjs`
- family/device/chip 文件名建议直接用 slug
- route 负责绑定 `tool -> binding -> algorithm`
- algorithm 文件不要求与 tool 同名，可以按外设模型命名
- 不要把 route 当成“每颗芯片一份”的入口；route 应尽量稳定，芯片差异优先下沉到 `bindings/params`

## 分类职责

- `chip-support/core/`
  放共享解析、profile 读取、通用工具函数
- `chip-support/algorithms/`
  放可以被多颗芯片复用的算法
- `chip-support/routes/`
  放真正被 runtime 按 `toolName` 加载的入口
- `extensions/tools/*`
  放 family/device/tool 绑定与约束
- `extensions/chips/profiles/*`
  放 chip 级封装、引脚、mux、相关工具与轻量引用
- `docs/sources/*`
  放被 `source_refs` / `component_refs` 引用的结论型知识

## 当前限制

- `extensions/tools/specs|families|devices` 与 `extensions/chips/profiles` 是当前推荐布局；runtime 仍兼容旧的 `extensions/chips/devices`
- 如果只是参数不同，不要复制一份算法；优先把差异放进 profile 的 `bindings/params`
- `chip profile` 里的 `packages / pins` 属于推荐真值层，不参与 route 选择，但会被上层 agent 用来做引脚、封装和 mux 推理
- `extensions/**/*.json` 可以使用 `source_refs` / `component_refs`，指向 `docs/sources/` 下的提炼摘要
- 当前仓库允许通过 `npm run generate` 直接把 AI 生成结果写回仓库根目录；生成后的内容仍必须通过 `npm run validate` 再提交
