# `packs/code-audit/` — Existing-Code Bug Audit Pack

本 pack 用于**存量代码 bug 审查**：拿到一个仓库（可能很大），按模块切分、双 agent 串行确认、输出 HTML / Excel 报告。

## Pack 概况

| 字段 | 值 |
|---|---|
| `pack_id` | `code-audit` |
| `version` | `0.1.0` |
| `schema_version` | `1` |
| `skills` | 4 |
| `agents` | 2 |

## 与其它 review 相关 skill 的边界

| 相关 | 场景 | 与本 pack 区别 |
|---|---|---|
| `packs/coding/skills/hf-code-review/` | PR / commit diff 评审（HF workflow 一环） | 输入是 diff、单 agent、不出报告 |
| `packs/garage/agents/code-review-agent.md` | PR 审查 + 对齐用户 style | 同上，单 agent |
| `packs/coding/skills/hf-bug-patterns/` | 把重复 bug 提炼为长期可复用模式 | 是"沉淀"不是"审查执行" |

本 pack 的差异化关键词：**存量全量代码、模块切分、双 agent 确认、HTML/Excel 报告、可重复执行（每次一个 run-id）**。

## 双 Agent 确认流程

```
用户请求审查 → [code-audit-reviewer-agent]
                  1. audit-planner   切模块 → plan.json
                  2. audit-reviewer  逐模块出 finding 草稿（draft）
                  ↓
              [code-audit-verifier-agent]   (独立上下文，看不到一审推理过程)
                  3. audit-verifier  对每条 finding 独立复核 → confirmed / rejected / upgrade / downgrade / needs_more_evidence
                  4. audit-reporter  汇总并渲染 HTML（+ 可选 Excel）
                  ↓
              用户拿到 reports/report.html
```

**为什么两个 agent 而不是同一 agent 两轮**：

- 避免推理污染：verifier 启动时只看 finding 的 `description + evidence + 原代码`，看不到一审内部推理草稿
- 角色分离：reviewer 鼓励"广撒网"；verifier 鼓励"严格、敢于反驳"
- 可追溯：record 清楚记录"谁判了、判了啥、为什么"

## Skills

| id | 文件 | 用途 |
|---|---|---|
| `audit-planner` | [`skills/audit-planner/SKILL.md`](skills/audit-planner/SKILL.md) | 切模块清单、定优先级、输出 `plan.json` |
| `audit-reviewer` | [`skills/audit-reviewer/SKILL.md`](skills/audit-reviewer/SKILL.md) | 一审：逐模块扫描代码，出 finding 草稿（带证据） |
| `audit-verifier` | [`skills/audit-verifier/SKILL.md`](skills/audit-verifier/SKILL.md) | 二审：对每条 finding 独立复核 + 必填 `evidence_check` |
| `audit-reporter` | [`skills/audit-reporter/SKILL.md`](skills/audit-reporter/SKILL.md) | 汇总 confirmed findings，渲染 HTML（必需）+ Excel（可选） |

## Agents

| id | 文件 | 用途 |
|---|---|---|
| `code-audit-reviewer-agent` | [`agents/code-audit-reviewer-agent.md`](agents/code-audit-reviewer-agent.md) | 编排 audit-planner + audit-reviewer（一审角色） |
| `code-audit-verifier-agent` | [`agents/code-audit-verifier-agent.md`](agents/code-audit-verifier-agent.md) | 编排 audit-verifier + audit-reporter（二审 + 报告角色） |

## Finding 数据契约（核心）

每条 finding 必须包含：

| 字段 | 必需 | 说明 |
|---|---|---|
| `id` | ✅ | `F-<run-id>-<seq>` 全局唯一 |
| `run_id` | ✅ | 本次审查的 run id |
| `module` | ✅ | 被审模块路径（如 `src/garage_os/runtime/`） |
| `file` | ✅ | 出问题的文件相对路径 |
| `line_start` / `line_end` | ✅ | 行号区间（1-indexed，闭区间） |
| `file_sha256` | ✅ | 审查时文件 sha256（行号漂移告警依据） |
| `title` | ✅ | 一句话标题 |
| `category` | ✅ | 见下面 11 类 bug 分类 |
| `severity` | ✅ | `critical` / `high` / `medium` / `low` / `info` |
| `confidence` | ✅ | `high` / `medium` / `low` |
| `description` | ✅ | 自然语言说明：为什么这是 bug |
| `evidence` | ✅ | `code_snippet`（实际代码）+ `reasoning`（为什么有问题）+ `trigger_conditions`（什么时候触发）+ `expected_vs_actual`（预期 vs 实际）+ `related_files`（旁证） |
| `suggested_fix` | ✅ | 建议如何修 |
| `reviewer` | ✅ | 一审 agent id + 时间戳 |
| `verifier` | ✅ | 二审 status（`confirmed` / `rejected` / `upgrade` / `downgrade` / `needs_more_evidence`）+ `reason` + `evidence_check` |

完整 JSON schema 见 `skills/audit-reviewer/references/finding-schema.md`。

## Bug 分类（11 类）

| category | 说明 |
|---|---|
| `correctness` | 逻辑错误、off-by-one、边界遗漏 |
| `error-handling` | 异常未捕获、错误吞没、错误码丢失 |
| `concurrency` | 竞态、死锁、共享状态未保护 |
| `resource-leak` | 文件句柄、连接、锁未释放 |
| `security` | 注入、路径穿越、敏感信息泄露、弱加密 |
| `api-misuse` | 第三方 API 用错、弃用 API |
| `typing` | 类型不一致、Optional 未守护 |
| `performance` | 明显的 O(n²)、不必要的 IO、死循环风险 |
| `dead-code` | 不可达分支、未使用函数 |
| `contract-violation` | 违反项目内既有接口契约 / schema |
| `i18n-or-encoding` | 编码、locale 处理错误 |

详见 `skills/audit-reviewer/references/bug-taxonomy.md`。

## 运行数据落盘位置

```
.garage/code-audit/runs/<run-id>/
├── plan.json                       # audit-planner 输出
├── findings/<module>.json          # 一审 finding 草稿
├── verifications/<module>.json     # 二审复核结果
├── confirmed.json                  # 经二审收敛的 finding 全集
├── reports/
│   ├── report.html                 # 必需
│   └── report.xlsx                 # 可选
└── audit-log.jsonl                 # 全程审计流水
```

## 触发方式

```bash
# 一审 + 二审 + 报告（推荐）
garage run code-audit-reviewer-agent --target src/
garage run code-audit-verifier-agent  --run-id <id> --formats html,xlsx

# 也可以在 IDE 内对话式触发：
# "请审查 src/runtime/ 模块的 bug"
```

第一版不引入 `garage audit` 一等公民 CLI（避开既有 contract surface），全部走 `garage run <agent>` 既有路径。

## 边界与不变量

- pack 内容物（SKILL.md / agent.md）保持宿主中立（NFR-701）
- `.garage/code-audit/runs/<run-id>/` 是工件目录，不进 memory 子系统（`knowledge/` / `experience/`），不被 F013-A skill mining 当 ExperienceRecord 挖掘
- finding 行号漂移：每条 finding 落盘时记 `file_sha256`，HTML 渲染时若当前文件 sha 已变则在卡片顶部加 "⚠ file changed since audit, line numbers may have shifted" 提示

## 实施切片（cycle 计划）

| Slice | 内容 | 状态 |
|---|---|---|
| A | pack 骨架（4 skill + 2 agent + pack.json + README）+ dogfood 物化验证 | ✅ |
| B | `audit-reporter/scripts/render_html.py` + 模板 + 单测 | ✅ |
| C | `render_xlsx.py` + `openpyxl` 依赖 + 单测 | ✅ |
| D | 端到端 dogfood：审 `src/garage_os/runtime/` + walkthrough；详见 `DOGFOOD-EXAMPLE.md` | ✅ |

## Dogfood 参考结果

见 [`DOGFOOD-EXAMPLE.md`](DOGFOOD-EXAMPLE.md)：用本 pack 实际审了 `src/garage_os/runtime/` 模块（2224 LoC），一审出 8 条 finding 草稿、二审独立复核（7 confirmed + 1 downgrade）、产 HTML + Excel 报告。run files 在 `.gitignore` 中（与 `.garage/sessions/` 同策略），不入 git；artifact 在 PR walkthrough 中。
