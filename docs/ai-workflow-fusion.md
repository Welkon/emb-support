# emb-agent × AI Hero Skills 融合方案

> 状态：已评审 · 作者：emb 团队 · 日期：2026-08-03 · 更新：2026-08-03（评审结论入档）
> 范围：嵌入式固件开发中，emb-agent（项目记忆/硬件上下文运行时）与 Matt Pocock「AI Hero Skills」流程技能集的组合方式。
> 原则：**不改 emb-agent 源码、不融入核心、以扩展方式组合。**

---

## 1. 背景

嵌入式固件开发中 AI 的两个短板：

1. **记不住板子** —— MCU、引脚、外设占用、原理图约束、需求边界，每个会话都要重讲。→ 由 **emb-agent** 解决（`.emb-agent/` 项目记忆、任务状态机、硬件验证、8 个固件子代理）。
2. **缺乏工程纪律** —— spec → tickets → TDD → review 的流程方法。→ 由 **Matt Pocock AI Hero Skills**（`mattpocock/skills`，26 个精选技能）解决。

两者分层不同、没有替代关系，因此是**组合（composition）**而非**替换（replacement）**。

## 2. 核心决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | **不改 emb-agent 源码** | emb-agent 是版本化、自更新的托管运行时（update/repair/rollback 快照、降级保护、managed-files 哈希校验）。改源码 = 放弃整条升级管线。 |
| D2 | **不把技能融入 emb-agent 核心/emb-support** | Pocock 技能是通用流程层，周更、第三方拥有。融入 = fork 不属于自己的代码，两个更新系统互相纠缠。 |
| D3 | **作为宿主层扩展，用 AGENTS.md 路由胶水连接** | 融合点不在 Rust runtime，而在宿主 agent 层：宿主同时加载 emb-agent（项目级）和流程技能（全局），AGENTS.md 路由表决定何时调用谁。 |
| D4 | **融合段措辞宿主无关** | 团队任何一个宿主都可能用（pi / Codex / Claude Code / Cursor）。融合段只写技能名 + 触发场景，不出现任何宿主命令语法；各宿主以自身原生机制调用（pi: `/skill:名称`；Codex: `$名称`；Claude Code: `/名称`；Cursor: 命令文件）。 |
| D5 | **技能全局安装到四个宿主** | 26 个精选技能已装到 `~/.agents/skills`（共享根，pi/Codex/Cursor 读）+ `~/.claude/skills`（镜像）。单一来源，`npx skills update -g` 一次更新全部。废弃/试验/个人技能（15 个）不装。 |
| D6 | **tracker = GitHub，不建本地 backlog** | 团队 2 人，issue 已在 GitHub 管理。`docs/backlog/` 本地文件 tracker 取消——三套任务系统必漂移。 |
| D7 | **接缝规则：task 管执行，issue 管承诺，人关 issue** | 认领 issue 才建 task（ID 写 PRD 头部）；`/emb-finish-work` 只归档 task 不动 GitHub；"完成"判定 = verify（硬件）+ code-review（代码）+ 人确认（唯一权威）。 |
| D8 | **反悔条款写死**（见第 9 节） | 给未来的自己留明确的退出路径，反而让"不改"更坚定。 |
| D9 | **QP 试点两周再铺开** | 融合段的正确性是跑出来的。QP 是活跃项目，试点成本最低；稳定后再铺 QYY/SGT/SZZ/ZX。 |

### 分层模型

```
┌─────────────────────────────────────────────┐
│ 宿主 agent（pi / Codex / Claude / Cursor）     │
│  · 全局技能：Pocock 26 个（流程层，周更）        │
│  · 项目集成：emb-agent 原生集成 + prompts       │
│  · 路由胶水：AGENTS.md 管理块外融合段（宿主无关）  │
├─────────────────────────────────────────────┤
│ emb-agent（项目记忆/硬件上下文，版本化托管）      │
│  · .emb-agent/ 事实 + 任务状态机 + 验证        │
│  · 8 个子代理（hw-scout/researcher/fw-doer…）  │
│  · specs（嵌入式领域规则）+ emb-support skills  │
└─────────────────────────────────────────────┘
```

## 3. 路由融合（AGENTS.md 融合段）

在 `<!-- EMB-AGENT:START -->` 管理块**之外**（文件尾部，emb-agent update 不会覆盖）追加「流程技能层」段，措辞宿主无关：

| emb-agent 阶段 | 先调用（流程技能层） | 再进入 |
|---|---|---|
| 需求模糊 / 方案未定 | grill-me（拷问）→ to-spec（出 PRD） | emb-agent plan / task |
| 跨会话大工程 | wayfinder（决策票）→ to-tickets（落 GitHub issues） | 认领后建 task |
| scan → plan → do | tdd / implement 纪律 | 但 `evidence readiness` gate 优先，不绕过 |
| review | code-review（软件双轴）→ arch-reviewer（ROM/RAM/ISR/电源）→ sys-reviewer | emb-agent verify（硬件验证） |
| bug | 寄存器级 → bug-hunter；逻辑/性能 → diagnosing-bugs | 均先 reproduce-first |
| 交接 | handoff + session 搜索 | 新会话 `/emb-start` |

依据：emb-agent 路由表已有 hook 行「External toolchain or lab workflow → Read the selected skill before matching work」，流程技能即此类外部技能。

## 4. 任务接缝（GitHub issue × emb-agent task）

```
GitHub issue（人管）                        emb-agent task（runtime 管）
──────────────────────────────            ─────────────────────────────
承诺："这个活算数、归谁"                     执行："证据、验证、journal"
In progress ← 认领时                       创建于认领时（PRD 写 Issue: #ID）
Closed ← 人手动关                          归档 ← /emb-finish-work
```

规则：

1. **认领即建**：在 GitHub 上把 issue 标为 In progress 时，才创建对应 task；task PRD 头部写 `Issue: #ID`；
2. **task 永不自动关 issue**：`/emb-finish-work` 只归档 task + journal，不动 GitHub；
3. **完成判定是人**：`verify`（emb-agent）证明"硬件上对"，`code-review` 证明"代码上对"，但"这事算完了"只有人说了算（2 人团队，人工闭环成本低）；
4. wayfinder 决策票 / to-tickets 产出的票直接落 GitHub issues，不建 `docs/backlog/`。

## 5. 子代理路由

| 场景 | 用 | 不用 |
|---|---|---|
| datasheet / 原理图 / 供应商 SDK | emb-agent `hw-scout` / `researcher` | Pocock research |
| 通用 web 调研 | Pocock `research` | — |
| 固件 bug（寄存器级） | emb-agent `bug-hunter` | diagnosing-bugs |
| 逻辑/性能 bug | Pocock `diagnosing-bugs` | bug-hunter |
| PR 代码质量 + spec 符合度 | Pocock `code-review` | arch-reviewer |
| ROM/RAM / ISR 延迟 / 电源域 | emb-agent `arch-reviewer` | code-review |
| 固件 + 原理图 + 需求系统评审 | emb-agent `sys-reviewer` | — |

## 6. 会话流程示例

```
/emb-start                    ← 硬件上下文 + gate
→ 需求模糊？ grill-me → to-spec 出 PRD
→ 工程大？   wayfinder 出票 → to-tickets 落 GitHub issues
→ 开工：     /emb-next → evidence readiness 通过
             → tdd 红绿循环 / implement（或派 fw-doer）
→ 完成：     code-review → arch-reviewer → emb-agent verify → 人关 issue
/emb-finish-work              ← journal + 归档 task（不动 GitHub）
```

## 7. 红线

1. 不把 `.emb-agent/tasks/` 状态机交给 to-tickets 管理；
2. 不绕过 `evidence readiness` gate 用流程技能直接写固件；
3. 硬件事实只信 `.emb-agent/hw.yaml`（truth-first），任何流程技能不改它；
4. 不动 `<!-- EMB-AGENT:START -->` 管理块内容，融合段只放块外。

## 8. 落地清单（零代码）

| 文件 | 动作 | 状态 |
|---|---|---|
| `emb-support/docs/ai-workflow-fusion.md` | 本文件（共享设计记录） | ✅ 已评审 |
| 技能全局安装（四宿主） | `npx skills add mattpocock/skills -g -a <host>`，精选 26 个 | ✅ 已完成 |
| `QP/.../AGENTS.md` 管理块外 | 追加第 3 节融合段（宿主无关措辞） | ⏳ 试点中 |
| 每项目 `setup-matt-pocock-skills` | 选择 **GitHub** tracker，配 triage labels | 试点时执行 |
| QYY/SGT/SZZ/ZX 的 AGENTS.md | 试点稳定后铺开 | 待定（2 周后） |

更新方式：全局 `npx skills update -g`；项目 `npx emb-agent update --target pi --local`，互不干扰。

## 9. 演进策略与反悔条款

**值得写进 emb-support**：嵌入式专属、跨项目复用的流程缺口（例：SCMCU 固件 TDD 模式、低 ROM 约束测试策略）→ 按既有 `xc8-build` 模式新增 skill bundle。

**才考虑改 emb-agent 源码**（反悔条款，2026-08-03 评审写入）：

```
触发条件（满足任一才讨论改源码）：
1. runtime 数据模型装不下融合需求 —— 例：task 无法引用 GitHub issue ID、
   gate 无法感知 spec/ticket 来源（当前都能绕过，不触发）；
2. 同一需求出现 3 次"绕过 workaround" —— 例：第三次在 AGENTS.md 里
   手写"把 issue 状态同步进 task PRD"之类的胶水；
3. emb-agent 大版本升级后，融合段修复成本超过重写成本。

流程：先试 emb-support（specs/skills/adapters）→ 再试项目级配置 →
最后才碰源码。每次升级 emb-agent 时花 15 分钟过 changelog 核对本条款。
```

**需要避免**：把通用流程技能（tdd/grill-me…）塞进 emb-support —— 违背 `workflow-layering.md` 的分层规则（core 小、领域规则进 specs、通用流程留在宿主层）。

## 10. 风险与开放问题

1. ~~AGENTS.md 融合段依赖 agent 遵循纯文本约定~~ → 已接受：红线写入融合段，靠审查兜底；
2. ~~跨项目复制会漂移~~ → 已定：QP 试点两周，措辞稳定后统一铺开；
3. 流程技能集周更，路由映射可能需随上游 changelog 微调（低频，由第 9 节升级核对覆盖）；
4. 开放：triage 的 labels 约定尚未定（试点时随 `setup-matt-pocock-skills` 一起定）。
