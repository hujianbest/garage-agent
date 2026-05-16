"""F008 ADR-D8-9 守门: NFR-801 文件级豁免清单 sentinel.

Two-layer enforcement (per design ADR-D8-9):

(a) STRICT: any SKILL.md / agents/*.md under packs/ MUST have ZERO
    host-specific blacklist hits.
(b) META EXEMPTION: any non-SKILL.md / non-agent.md file under packs/
    that contains blacklist hits MUST appear in the EXEMPTION_LIST below.
    Unlisted hits are RED.

EXEMPTION_LIST is manually synced with design ADR-D8-9 enum (4 fixed +
1 conditional). Adding a new entry requires amending design ADR-D8-9
+ spec NFR-801 详细说明 first, then this file.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKS_ROOT = REPO_ROOT / "packs"

HOST_BLACKLIST_PATTERN = re.compile(
    r"\.claude/|\.cursor/|\.opencode/|claude-code", re.IGNORECASE
)

# F008 ADR-D8-9 EXEMPTION_LIST (4 fixed + 1 conditional).
# Format: relative path from REPO_ROOT (POSIX).
EXEMPTION_LIST: frozenset[str] = frozenset(
    {
        # 4 fixed exemptions (per ADR-D8-9 candidate "分类" 选定):
        "packs/writing/skills/humanizer-zh/README.md",
        "packs/garage/skills/writing-skills/anthropic-best-practices.md",
        "packs/garage/skills/writing-skills/examples/CLAUDE_MD_TESTING.md",
        # 1 conditional exemption (T2 decision: migrated packs/writing/README.md;
        # contains 3 host-path lines as install command examples):
        "packs/writing/README.md",
        # T1b/T3/F007 carry-forward: pack-level README files all contain
        # `garage init --hosts claude` / `.claude/skills/` etc. as install
        # 样板, which is by design (READMEs explain how downstream users
        # interact with hosts; they're documentation, not runtime SKILL.md).
        # Adding to exemption per same精神 as ADR-D8-9 选定 (meta/教学 文件
        # vs. SKILL.md/agent.md 强约束).
        "packs/README.md",
        "packs/garage/README.md",
        "packs/coding/README.md",
        # code-audit pack README is necessarily host-aware: its "How to Use"
        # section walks downstream users through OpenCode / Claude Code /
        # Cursor invocation patterns (the pack's core value prop is two-agent
        # confirmation orchestrated through native host agent surfaces), so it
        # references `.opencode/agent/`, `.claude/agents/`, `.cursor/skills/`
        # as install paths and host-specific invocation examples. Same精神 as
        # the existing pack-level README entries above.
        "packs/code-audit/README.md",
    }
)


def _iter_packs_md_files() -> list[Path]:
    """All .md files under packs/ (used to enumerate hits)."""
    if not PACKS_ROOT.exists():
        return []
    return list(PACKS_ROOT.rglob("*.md"))


def _is_skill_or_agent_file(path: Path) -> bool:
    """SKILL.md (under skills/<id>/) or agent .md (under agents/) → strict scope."""
    if path.name == "SKILL.md":
        return True
    if path.parent.name == "agents":
        return True
    return False


class TestNeutralityExemptionList:
    """ADR-D8-9 layered NFR-801 守门."""

    def test_skill_md_strict_neutrality(self) -> None:
        """ADR-D8-9 layer (a): SKILL.md/agent.md MUST have zero blacklist hits."""
        violations = []
        for md in _iter_packs_md_files():
            if not _is_skill_or_agent_file(md):
                continue
            text = md.read_text(encoding="utf-8")
            match = HOST_BLACKLIST_PATTERN.search(text)
            if match is not None:
                violations.append((md.relative_to(REPO_ROOT), match.group(0)))
        assert not violations, (
            f"NFR-801 strict violation: SKILL.md/agent.md contain host-specific "
            f"terms: {violations}"
        )

    def test_meta_files_in_exemption_list(self) -> None:
        """ADR-D8-9 layer (b): any non-SKILL.md/non-agent.md hit MUST appear
        in EXEMPTION_LIST."""
        unauthorized_hits: list[tuple[str, str]] = []
        for md in _iter_packs_md_files():
            if _is_skill_or_agent_file(md):
                continue  # strict layer (a) handled separately
            text = md.read_text(encoding="utf-8")
            match = HOST_BLACKLIST_PATTERN.search(text)
            if match is None:
                continue
            rel = md.relative_to(REPO_ROOT).as_posix()
            if rel not in EXEMPTION_LIST:
                unauthorized_hits.append((rel, match.group(0)))
        assert not unauthorized_hits, (
            "NFR-801 layer (b) violated: meta files contain host-specific terms "
            f"but are not in EXEMPTION_LIST: {unauthorized_hits}\n"
            "Either (a) refactor the file to remove the host term, or (b) amend "
            "design ADR-D8-9 + spec NFR-801 详细说明 EXEMPTION_LIST + this test's "
            "EXEMPTION_LIST constant."
        )

    def test_exemption_list_entries_actually_exist(self) -> None:
        """Sanity: every EXEMPTION_LIST entry MUST point to a real file. Otherwise
        the exemption is dead code and should be removed from ADR-D8-9 + this file."""
        missing = []
        for rel in EXEMPTION_LIST:
            target = REPO_ROOT / rel
            if not target.is_file():
                missing.append(rel)
        # Note: packs/writing/README.md is the conditional 1; it must exist after
        # T2 decision to migrate, which we did. So all 5 entries should exist.
        assert not missing, (
            f"EXEMPTION_LIST contains {missing} but file(s) missing on disk; "
            "either restore the file or shrink the exemption list."
        )
