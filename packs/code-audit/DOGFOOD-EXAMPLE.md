# Dogfood Example — Auditing `src/garage_os/runtime/`

本文档记录 Slice D 完成时使用 `code-audit` pack 端到端审查本仓库 `src/garage_os/runtime/` 模块的结果。作为下游用户和未来贡献者的 reference example。

## 运行参数

- **target**: `src/garage_os/runtime/`
- **run_id**: `audit-runtime-dogfood`
- **modules scanned**: 1 (runtime)
- **files scanned**: 6 (`__init__.py` / `session_manager.py` / `error_handler.py` / `state_machine.py` / `skill_executor.py` / `artifact_board_sync.py`)
- **total LoC**: 2224

## 双 Agent 串行结果

| 阶段 | Agent | 输出 | 关键数据 |
|---|---|---|---|
| 一审 | `code-audit-reviewer-agent` → `audit-planner` + `audit-reviewer` | 8 个 finding 草稿，落到 `findings/runtime.json` | 8 drafts (4 medium / 3 high / 1 low) |
| 二审 | `code-audit-verifier-agent` → `audit-verifier` （**fresh context**） | 8 verifier 判决，落到 `verifications/runtime.json` | 7 confirmed / 0 rejected / 1 downgrade (high → medium) |
| 报告 | `code-audit-verifier-agent` → `audit-reporter` | `reports/report.html` (47 KB) + `reports/report.xlsx` (15 KB) | 1 high / 6 medium / 1 low after verifier 调档 |

### 一审 → 二审 调档证据

二审 fresh-context agent 对 8 条 finding 中的 1 条（`F-005` "`sync-log.json` truncates earlier entries"）从 `high` 下调为 `medium`，理由：

> "_log_sync opens sync-log.json with open(..., 'w') and writes a single json.dump dict each call (artifact_board_sync.py 337-351). sync invokes _log_sync inside its per-artifact loop and again for untracked files (81-176), so the file only retains the last write; however in-memory SyncResult aggregates are still populated correctly — the defect is persisted log truncation, not wrong sync categorization, so high severity is too strong."

这正是双 agent 设计要达成的效果：reviewer 凭直觉给 high，verifier 在独立 context 里重读源码 + 评估实际 blast radius，把严重度收敛到更合理水平。

## 8 条 finding 概览

| id | file | line | severity (final) | category | confidence | verifier |
|---|---|---|---|---|---|---|
| F-001 | `error_handler.py` | 66-91 | medium | correctness | high | confirmed |
| F-002 | `state_machine.py` | 119-169 | medium | concurrency | high | confirmed |
| F-003 | `state_machine.py` | 90-117 | medium | concurrency | high | confirmed |
| F-004 | `session_manager.py` | 576-591 | medium | correctness | high | confirmed |
| F-005 | `artifact_board_sync.py` | 337-353 | **medium** ← high | correctness | high | **downgrade** |
| F-006 | `artifact_board_sync.py` | 103-116 | high | security | high | confirmed |
| F-007 | `artifact_board_sync.py` | 203-214 | medium | correctness | high | confirmed |
| F-008 | `skill_executor.py` | 207-229 | low | correctness | high | confirmed |

**所有 8 条都附完整证据**：`code_snippet`（源代码原样）+ `reasoning`（≥ 2 句话 + 跨文件引用）+ `trigger_conditions` + `expected_vs_actual` + `related_files` + `suggested_fix`。

## 复现这个 audit run

清理本地 cached run 后从头跑一次（手动剧本，因为 agent runtime 编排还没接 CLI）：

```bash
# 1. 一审 agent in IDE (Claude Code / OpenCode): 唤起 code-audit-reviewer-agent
#    用户输入: "审查 src/garage_os/runtime/ 模块的 bug"
#    → 写出 .garage/code-audit/runs/<run-id>/plan.json + findings/runtime.json

# 2. 二审 agent in 新会话: 唤起 code-audit-verifier-agent
#    用户输入: "复核 run <run-id>"
#    → 写出 verifications/runtime.json + confirmed.json

# 3. 渲染报告（脚本入口）
cd /path/to/garage-agent
uv run python packs/code-audit/skills/audit-reporter/scripts/render_html.py \
  --workspace . --run-id <run-id>
uv run python packs/code-audit/skills/audit-reporter/scripts/render_xlsx.py \
  --workspace . --run-id <run-id>

# 4. 打开报告
open .garage/code-audit/runs/<run-id>/reports/report.html
```

## 工件位置（Slice D 产出）

| 工件 | 路径（artifacts） | 来源（仓库内） |
|---|---|---|
| 实际渲染的 HTML 报告 | `/opt/cursor/artifacts/audit_runtime_real_report.html` | `.garage/code-audit/runs/audit-runtime-dogfood/reports/report.html` (gitignored) |
| 实际渲染的 Excel 报告 | `/opt/cursor/artifacts/audit_runtime_real_report.xlsx` | `.garage/code-audit/runs/audit-runtime-dogfood/reports/report.xlsx` (gitignored) |
| 端到端走查视频 | `/opt/cursor/artifacts/audit_runtime_real_walkthrough.mp4` | （仅 artifacts） |

`.garage/code-audit/runs/*/` 在 `.gitignore` 中（与 `.garage/sessions/` 同策略），不入 git 追踪。

## 与 hf-code-review / code-review-agent 的对比

本次 run 出的 8 条 finding 都是**真实代码问题**，全部需要静态扫描才能发现，不需要 PR diff context。这正是 `code-audit` pack 相对 `hf-code-review` 的差异化场景：

- `hf-code-review` 输入是 PR diff → 输出 `verdict + findings`，单 agent
- `code-audit` pack 输入是存量目录 → 输出 双 agent 确认过的 HTML/Excel 报告，按模块切分可断点续跑
