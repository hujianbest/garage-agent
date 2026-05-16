"""Tests for packs/code-audit/skills/audit-reporter/scripts/render_html.py.

Slice B of the code-audit pack. The script renders confirmed.json (+ plan.json
+ optional findings/<module>.json) into a single-file HTML report. These tests
verify:

- Smoke: minimal valid input produces a non-empty HTML file
- Schema validation catches bad input (missing fields, bad enum values, etc.)
- Rendered HTML contains all confirmed findings + their file:line + evidence
- file_sha256 drift detection adds a warning banner
- rejected/needs_more_evidence findings surface in the bottom audit-trail
- All CSS/JS is inline (no external CDN references)
- Single-finding details correctly escape HTML entities (XSS-safe)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import render_html  # noqa: E402 — sys.path patched in conftest
from render_html import (
    FilesystemSha256Resolver,
    RenderResult,
    ReportError,
    render_report,
)


def _baseline_plan(run_id: str = "audit-test-001", target: str = "src/") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "target": target,
        "created_at": "2026-05-16T04:35:00Z",
        "budgets": {"module_budget_tokens": 30000, "module_budget_files": 20},
        "modules": [
            {
                "name": "runtime",
                "path": "src/runtime/",
                "priority": "high",
                "file_count": 3,
                "loc_estimate": 240,
                "languages": ["python"],
                "status": "done",
            }
        ],
        "total_files": 3,
        "total_loc": 240,
    }


def _baseline_finding(
    *,
    fid: str = "F-audit-test-001-001",
    severity: str = "high",
    category: str = "error-handling",
    confidence: str = "high",
    module: str = "runtime",
    file: str = "src/runtime/session_manager.py",
    line_start: int = 142,
    line_end: int = 148,
    file_sha256: str = "a" * 64,
    verifier_status: str = "confirmed",
) -> dict[str, Any]:
    return {
        "id": fid,
        "run_id": "audit-test-001",
        "module": module,
        "file": file,
        "line_start": line_start,
        "line_end": line_end,
        "file_sha256": file_sha256,
        "title": "KeyError 未被捕获",
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "description": "self.sessions[session_id] 无防护，并发场景下抛 KeyError。",
        "evidence": {
            "code_snippet": "def _trigger():\n    meta = self.sessions[session_id]",
            "reasoning": "第 143 行直接索引 dict。并发 archive 路径会触发 KeyError。",
            "trigger_conditions": "并发 archive",
            "expected_vs_actual": "expected early-return on None; actual: KeyError",
            "related_files": ["src/runtime/session_manager.py:88"],
        },
        "suggested_fix": "改用 self.sessions.get(session_id) + early-return None.",
        "reviewer": {
            "agent": "code-audit-reviewer-agent",
            "ts": "2026-05-16T04:35:12Z",
        },
        "verifier": {
            "status": verifier_status,
            "reason": "已读源文件 L142-148。Snippet 与原文件一致。证据成立。",
            "evidence_check": "Read session_manager.py L88-148, grepped self.sessions[",
            "agent": "code-audit-verifier-agent",
            "ts": "2026-05-16T04:42:55Z",
        },
    }


def _write_run(
    tmp_path: Path,
    *,
    run_id: str = "audit-test-001",
    confirmed: list[dict[str, Any]] | None = None,
    rejected_findings: list[dict[str, Any]] | None = None,
    plan: dict[str, Any] | None = None,
) -> Path:
    """Lay out .garage/code-audit/runs/<run_id>/ in tmp_path. Returns run_dir."""
    run_dir = tmp_path / ".garage" / "code-audit" / "runs" / run_id
    (run_dir / "findings").mkdir(parents=True)
    (run_dir / "reports").mkdir()
    if plan is None:
        plan = _baseline_plan(run_id=run_id)
    (run_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    if confirmed is None:
        confirmed = [_baseline_finding()]
    (run_dir / "confirmed.json").write_text(
        json.dumps(confirmed, indent=2), encoding="utf-8"
    )
    if rejected_findings:
        # Write to findings/<module>.json so _collect_rejected picks them up.
        # Group by module.
        by_module: dict[str, list[dict[str, Any]]] = {}
        for f in rejected_findings:
            by_module.setdefault(f["module"], []).append(f)
        for module, items in by_module.items():
            (run_dir / "findings" / f"{module}.json").write_text(
                json.dumps(items, indent=2), encoding="utf-8"
            )
    return run_dir


class TestSmoke:
    """Basic happy path: minimal valid input produces a non-empty HTML."""

    def test_render_produces_html_file(self, tmp_path: Path) -> None:
        _write_run(tmp_path)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        assert isinstance(result, RenderResult)
        out = result.output_path
        assert out.is_file()
        text = out.read_text(encoding="utf-8")
        assert text.startswith("<!DOCTYPE html>")
        assert "</html>" in text
        assert len(text) > 1000  # not a trivial stub

    def test_render_returns_correct_counts(self, tmp_path: Path) -> None:
        findings = [
            _baseline_finding(fid="F-1", severity="critical"),
            _baseline_finding(fid="F-2", severity="high"),
            _baseline_finding(fid="F-3", severity="high"),
            _baseline_finding(fid="F-4", severity="medium", module="adapter"),
        ]
        _write_run(tmp_path, confirmed=findings)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        assert result.finding_count == 4
        assert result.by_severity == {"critical": 1, "high": 2, "medium": 1}
        assert result.by_module == {"runtime": 3, "adapter": 1}
        assert result.rejected_count == 0


class TestHtmlContent:
    """Verify the rendered HTML actually contains finding data."""

    def test_finding_title_and_location_in_html(self, tmp_path: Path) -> None:
        _write_run(tmp_path)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        assert "KeyError 未被捕获" in text
        assert "src/runtime/session_manager.py:142-148" in text
        assert "code-audit-reviewer-agent" in text
        assert "code-audit-verifier-agent" in text

    def test_finding_evidence_fields_rendered(self, tmp_path: Path) -> None:
        _write_run(tmp_path)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        # All evidence fields must appear in the HTML.
        assert "self.sessions[session_id]" in text
        assert "Reasoning" in text
        assert "Trigger" in text
        assert "Expected vs Actual" in text
        assert "Related" in text
        assert "Suggested fix" in text

    def test_severity_badge_classes_present(self, tmp_path: Path) -> None:
        findings = [
            _baseline_finding(fid=f"F-{i}", severity=sev)
            for i, sev in enumerate(["critical", "high", "medium", "low", "info"], start=1)
        ]
        _write_run(tmp_path, confirmed=findings)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        for sev in ["critical", "high", "medium", "low", "info"]:
            assert f'data-severity="{sev}"' in text
            assert f"badge-severity-{sev}" in text

    def test_summary_donut_uses_all_severities(self, tmp_path: Path) -> None:
        findings = [_baseline_finding(fid=f"F-{i}", severity=sev)
                    for i, sev in enumerate(["critical", "high"], start=1)]
        _write_run(tmp_path, confirmed=findings)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        assert "<svg" in text
        assert "severity-donut" in text

    def test_by_module_table_lists_all_modules(self, tmp_path: Path) -> None:
        findings = [
            _baseline_finding(fid="F-1", module="runtime"),
            _baseline_finding(fid="F-2", module="adapter"),
            _baseline_finding(fid="F-3", module="adapter"),
        ]
        _write_run(tmp_path, confirmed=findings)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        assert "by-module-table" in text
        assert ">runtime<" in text or "runtime<" in text
        assert ">adapter<" in text or "adapter<" in text


class TestSchemaValidation:
    """Schema validation catches bad input."""

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        bad = _baseline_finding()
        del bad["evidence"]
        _write_run(tmp_path, confirmed=[bad])
        with pytest.raises(ReportError, match="missing field 'evidence'"):
            render_report(workspace_root=tmp_path, run_id="audit-test-001")

    def test_invalid_severity_raises(self, tmp_path: Path) -> None:
        bad = _baseline_finding()
        bad["severity"] = "URGENT"  # not in VALID_SEVERITIES
        _write_run(tmp_path, confirmed=[bad])
        with pytest.raises(ReportError, match="invalid severity"):
            render_report(workspace_root=tmp_path, run_id="audit-test-001")

    def test_invalid_category_raises(self, tmp_path: Path) -> None:
        bad = _baseline_finding()
        bad["category"] = "style"  # not a recognized bug category
        _write_run(tmp_path, confirmed=[bad])
        with pytest.raises(ReportError, match="invalid category"):
            render_report(workspace_root=tmp_path, run_id="audit-test-001")

    def test_invalid_verifier_status_raises(self, tmp_path: Path) -> None:
        bad = _baseline_finding()
        bad["verifier"]["status"] = "approved"  # not in VALID_VERIFIER_STATUSES
        _write_run(tmp_path, confirmed=[bad])
        with pytest.raises(ReportError, match="verifier.status"):
            render_report(workspace_root=tmp_path, run_id="audit-test-001")

    def test_line_start_greater_than_line_end_raises(self, tmp_path: Path) -> None:
        bad = _baseline_finding(line_start=200, line_end=100)
        _write_run(tmp_path, confirmed=[bad])
        with pytest.raises(ReportError, match="line_start=200 > line_end=100"):
            render_report(workspace_root=tmp_path, run_id="audit-test-001")

    def test_evidence_missing_field_raises(self, tmp_path: Path) -> None:
        bad = _baseline_finding()
        del bad["evidence"]["reasoning"]
        _write_run(tmp_path, confirmed=[bad])
        with pytest.raises(ReportError, match="evidence missing field 'reasoning'"):
            render_report(workspace_root=tmp_path, run_id="audit-test-001")

    def test_missing_confirmed_json_raises(self, tmp_path: Path) -> None:
        run_dir = tmp_path / ".garage" / "code-audit" / "runs" / "audit-x"
        run_dir.mkdir(parents=True)
        (run_dir / "plan.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ReportError, match="Missing required file"):
            render_report(workspace_root=tmp_path, run_id="audit-x")

    def test_confirmed_json_not_array_raises(self, tmp_path: Path) -> None:
        run_dir = tmp_path / ".garage" / "code-audit" / "runs" / "audit-x"
        (run_dir / "findings").mkdir(parents=True)
        (run_dir / "reports").mkdir()
        (run_dir / "plan.json").write_text("{}", encoding="utf-8")
        (run_dir / "confirmed.json").write_text('{"not": "an array"}', encoding="utf-8")
        with pytest.raises(ReportError, match="must contain a JSON array"):
            render_report(workspace_root=tmp_path, run_id="audit-x")


class TestFileShaDrift:
    """File sha256 drift detection."""

    def _make_resolver(self, sha_map: dict[str, str | None]) -> render_html.Sha256Resolver:
        class FakeResolver(render_html.Sha256Resolver):
            def resolve(self_inner, rel_path: str) -> str | None:
                return sha_map.get(rel_path)
        return FakeResolver()

    def test_drift_banner_when_sha_mismatches(self, tmp_path: Path) -> None:
        finding = _baseline_finding(file_sha256="a" * 64)
        _write_run(tmp_path, confirmed=[finding])
        resolver = self._make_resolver(
            {"src/runtime/session_manager.py": "b" * 64}
        )
        result = render_report(
            workspace_root=tmp_path,
            run_id="audit-test-001",
            sha_resolver=resolver,
        )
        text = result.output_path.read_text(encoding="utf-8")
        assert "file changed since audit" in text

    def test_no_drift_banner_when_sha_matches(self, tmp_path: Path) -> None:
        finding = _baseline_finding(file_sha256="a" * 64)
        _write_run(tmp_path, confirmed=[finding])
        resolver = self._make_resolver({"src/runtime/session_manager.py": "a" * 64})
        result = render_report(
            workspace_root=tmp_path,
            run_id="audit-test-001",
            sha_resolver=resolver,
        )
        text = result.output_path.read_text(encoding="utf-8")
        assert "file changed since audit" not in text

    def test_drift_banner_when_file_missing(self, tmp_path: Path) -> None:
        finding = _baseline_finding(file_sha256="a" * 64)
        _write_run(tmp_path, confirmed=[finding])
        resolver = self._make_resolver({"src/runtime/session_manager.py": None})
        result = render_report(
            workspace_root=tmp_path,
            run_id="audit-test-001",
            sha_resolver=resolver,
        )
        text = result.output_path.read_text(encoding="utf-8")
        assert "file no longer exists" in text

    def test_filesystem_resolver_real_file(self, tmp_path: Path) -> None:
        src_file = tmp_path / "demo.py"
        src_file.write_text("print('hi')\n", encoding="utf-8")
        expected = hashlib.sha256(src_file.read_bytes()).hexdigest()
        resolver = FilesystemSha256Resolver(workspace_root=tmp_path)
        assert resolver.resolve("demo.py") == expected
        assert resolver.resolve("missing.py") is None


class TestRejectedSection:
    """Rejected and needs_more_evidence findings surface in the bottom section."""

    def test_rejected_finding_appears_in_audit_trail(self, tmp_path: Path) -> None:
        confirmed = [_baseline_finding(fid="F-1")]
        rejected = [
            _baseline_finding(
                fid="F-2",
                verifier_status="rejected",
            ),
            _baseline_finding(
                fid="F-3",
                verifier_status="needs_more_evidence",
            ),
        ]
        _write_run(tmp_path, confirmed=confirmed, rejected_findings=rejected)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        assert result.rejected_count == 2
        text = result.output_path.read_text(encoding="utf-8")
        assert "Rejected &amp; needs_more_evidence" in text
        assert "F-2" in text
        assert "F-3" in text
        assert "status-rejected" in text
        assert "status-needs_more_evidence" in text


class TestNoExternalDependencies:
    """Spec requirement: no external CDN, no remote stylesheets/scripts."""

    def test_html_has_no_external_resources(self, tmp_path: Path) -> None:
        _write_run(tmp_path)
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        # No <link rel="stylesheet" href="...">
        assert '<link rel="stylesheet"' not in text
        # No <script src="http..."> or src="//..."
        assert 'script src="http' not in text
        assert "script src=\"//" not in text
        # CSS + JS must be inline in <style> and <script> blocks.
        assert "<style>" in text
        assert "<script>" in text


class TestEmptyAndEdgeCases:
    """Edge cases: no findings, only rejected, weird unicode."""

    def test_empty_confirmed_still_renders(self, tmp_path: Path) -> None:
        _write_run(tmp_path, confirmed=[])
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        assert "No confirmed findings" in text
        assert result.finding_count == 0
        assert result.by_severity == {}

    def test_html_escapes_dangerous_content(self, tmp_path: Path) -> None:
        finding = _baseline_finding()
        finding["title"] = "Bug: <script>alert(1)</script>"
        finding["description"] = "<img src=x onerror=alert(1)>"
        finding["evidence"]["code_snippet"] = "x = '<\\\"injection\\\">'"
        _write_run(tmp_path, confirmed=[finding])
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        # Raw <script> from finding title must NOT appear unescaped in body.
        # (The legitimate inline <script>...</script> for filter JS is fine.)
        assert "Bug: <script>alert(1)</script>" not in text
        # Should be HTML-escaped.
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
        assert "&lt;img src=x onerror=alert(1)&gt;" in text


class TestExplicitPaths:
    """CLI alternative entry: explicit file paths instead of workspace+run_id."""

    def test_render_with_explicit_paths(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path)
        out = tmp_path / "custom-report.html"
        result = render_report(
            confirmed_path=run_dir / "confirmed.json",
            plan_path=run_dir / "plan.json",
            findings_dir=run_dir / "findings",
            output_path=out,
        )
        assert out.is_file()
        assert result.output_path == out

    def test_render_without_run_id_or_paths_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ReportError, match="Either"):
            render_report(workspace_root=tmp_path)


class TestVerifierSeverityChange:
    """When verifier upgrades/downgrades severity, the report shows the change."""

    def test_severity_upgrade_displayed(self, tmp_path: Path) -> None:
        finding = _baseline_finding(severity="high")
        finding["severity_before"] = "medium"
        finding["verifier"]["status"] = "upgrade"
        finding["verifier"]["severity_after"] = "high"
        _write_run(tmp_path, confirmed=[finding])
        result = render_report(workspace_root=tmp_path, run_id="audit-test-001")
        text = result.output_path.read_text(encoding="utf-8")
        assert "Severity adjusted" in text
        assert "medium → high" in text


class TestCliEntry:
    """Smoke test for the __main__ argparse path via _cli()."""

    def test_cli_renders(self, tmp_path: Path) -> None:
        _write_run(tmp_path)
        rc = render_html._cli([
            "--workspace", str(tmp_path),
            "--run-id", "audit-test-001",
        ])
        assert rc == 0
        out_path = (
            tmp_path / ".garage" / "code-audit" / "runs"
            / "audit-test-001" / "reports" / "report.html"
        )
        assert out_path.is_file()

    def test_cli_invalid_data_returns_2(self, tmp_path: Path) -> None:
        run_dir = tmp_path / ".garage" / "code-audit" / "runs" / "audit-x"
        run_dir.mkdir(parents=True)
        (run_dir / "plan.json").write_text("{}", encoding="utf-8")
        (run_dir / "confirmed.json").write_text(
            json.dumps([{"id": "bad"}]), encoding="utf-8"
        )
        rc = render_html._cli([
            "--workspace", str(tmp_path),
            "--run-id", "audit-x",
        ])
        assert rc == 2
