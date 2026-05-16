"""Render confirmed.json (+ plan.json) into a single-file HTML report.

Slice B of the code-audit pack. Pure Python stdlib — no Jinja, no Bootstrap,
no external CDN. CSS + JS are read from sibling ``assets/`` files and inlined
into the output ``report.html``.

Inputs (all under ``<workspace>/.garage/code-audit/runs/<run_id>/``):

- ``plan.json``         — produced by ``audit-planner`` (used for run meta)
- ``confirmed.json``    — produced by ``audit-verifier`` (confirmed findings)
- ``findings/<m>.json`` — produced by ``audit-reviewer`` (optional, used to
                          surface rejected + needs_more_evidence findings in
                          the bottom "Rejected" collapsible section)

Output:

- ``reports/report.html`` — single-file HTML, self-contained, offline-readable

CLI usage::

    python -m render_html --run-id audit-2026-05-16-0435
    python -m render_html --confirmed-path .../confirmed.json \\
                          --plan-path     .../plan.json \\
                          --output        .../reports/report.html

Library usage::

    from render_html import render_report
    out_path = render_report(workspace_root=Path("."), run_id="audit-...")

See ``packs/code-audit/skills/audit-reporter/references/report-schema.md`` for
the full HTML contract and ``finding-schema.md`` for input shape.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import html
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PACK_VERSION = "0.1.0"

VALID_SEVERITIES = ("critical", "high", "medium", "low", "info")
VALID_CONFIDENCES = ("high", "medium", "low")
VALID_CATEGORIES = (
    "correctness",
    "error-handling",
    "concurrency",
    "resource-leak",
    "security",
    "api-misuse",
    "typing",
    "performance",
    "dead-code",
    "contract-violation",
    "i18n-or-encoding",
)
VALID_VERIFIER_STATUSES = (
    "confirmed",
    "rejected",
    "upgrade",
    "downgrade",
    "needs_more_evidence",
)


class ReportError(ValueError):
    """Raised when input JSON is missing required fields or has invalid enum values."""


@dataclasses.dataclass(frozen=True)
class RenderResult:
    output_path: Path
    finding_count: int
    by_severity: dict[str, int]
    by_module: dict[str, int]
    rejected_count: int


def render_report(
    *,
    workspace_root: Path | None = None,
    run_id: str | None = None,
    confirmed_path: Path | None = None,
    plan_path: Path | None = None,
    findings_dir: Path | None = None,
    output_path: Path | None = None,
    assets_dir: Path | None = None,
    sha_resolver: "Sha256Resolver | None" = None,
) -> RenderResult:
    """Render an HTML report.

    Either pass (workspace_root + run_id) — paths are derived per
    ``.garage/code-audit/runs/<run_id>/`` layout — or pass explicit paths.
    """
    confirmed_path, plan_path, findings_dir, output_path = _resolve_paths(
        workspace_root=workspace_root,
        run_id=run_id,
        confirmed_path=confirmed_path,
        plan_path=plan_path,
        findings_dir=findings_dir,
        output_path=output_path,
    )
    if assets_dir is None:
        assets_dir = Path(__file__).resolve().parent.parent / "assets"

    plan = _load_json(plan_path) if plan_path.is_file() else {}
    confirmed = _load_json(confirmed_path) or []
    if not isinstance(confirmed, list):
        raise ReportError(f"{confirmed_path} must contain a JSON array of findings")

    _validate_findings(confirmed)
    rejected_records = _collect_rejected(findings_dir) if findings_dir and findings_dir.is_dir() else []

    if sha_resolver is None:
        sha_resolver = FilesystemSha256Resolver(
            workspace_root=workspace_root or (plan_path.parent.parent.parent.parent if plan_path else Path("."))
        )

    css = (assets_dir / "report-style.css.txt").read_text(encoding="utf-8")
    js = (assets_dir / "report-script.js.txt").read_text(encoding="utf-8")

    html_text = _build_html(
        plan=plan,
        confirmed=confirmed,
        rejected=rejected_records,
        css=css,
        js=js,
        sha_resolver=sha_resolver,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")

    by_severity = Counter(f["severity"] for f in confirmed)
    by_module = Counter(f["module"] for f in confirmed)

    return RenderResult(
        output_path=output_path,
        finding_count=len(confirmed),
        by_severity=dict(by_severity),
        by_module=dict(by_module),
        rejected_count=len(rejected_records),
    )


def _resolve_paths(
    *,
    workspace_root: Path | None,
    run_id: str | None,
    confirmed_path: Path | None,
    plan_path: Path | None,
    findings_dir: Path | None,
    output_path: Path | None,
) -> tuple[Path, Path, Path | None, Path]:
    if confirmed_path and output_path:
        return (
            confirmed_path,
            plan_path or (confirmed_path.parent / "plan.json"),
            findings_dir or (confirmed_path.parent / "findings"),
            output_path,
        )
    if workspace_root is None or run_id is None:
        raise ReportError(
            "Either (confirmed_path + output_path) or (workspace_root + run_id) must be provided"
        )
    run_dir = workspace_root / ".garage" / "code-audit" / "runs" / run_id
    return (
        run_dir / "confirmed.json",
        run_dir / "plan.json",
        run_dir / "findings",
        run_dir / "reports" / "report.html",
    )


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise ReportError(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportError(f"Invalid JSON in {path}: {exc}") from exc


REQUIRED_FINDING_FIELDS = (
    "id",
    "module",
    "file",
    "line_start",
    "line_end",
    "file_sha256",
    "title",
    "category",
    "severity",
    "confidence",
    "description",
    "evidence",
    "suggested_fix",
    "reviewer",
    "verifier",
)
REQUIRED_EVIDENCE_FIELDS = (
    "code_snippet",
    "reasoning",
    "trigger_conditions",
    "expected_vs_actual",
)
REQUIRED_REVIEWER_FIELDS = ("agent", "ts")
REQUIRED_VERIFIER_FIELDS = ("status", "reason", "evidence_check", "agent", "ts")


def _validate_findings(findings: list[Any]) -> None:
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            raise ReportError(f"finding #{i} must be an object, got {type(f).__name__}")
        for k in REQUIRED_FINDING_FIELDS:
            if k not in f:
                raise ReportError(f"finding #{i} ({f.get('id', '<no-id>')}) missing field '{k}'")
        if f["category"] not in VALID_CATEGORIES:
            raise ReportError(
                f"finding {f['id']} has invalid category {f['category']!r}; "
                f"must be one of {VALID_CATEGORIES}"
            )
        if f["severity"] not in VALID_SEVERITIES:
            raise ReportError(
                f"finding {f['id']} has invalid severity {f['severity']!r}; "
                f"must be one of {VALID_SEVERITIES}"
            )
        if f["confidence"] not in VALID_CONFIDENCES:
            raise ReportError(
                f"finding {f['id']} has invalid confidence {f['confidence']!r}; "
                f"must be one of {VALID_CONFIDENCES}"
            )
        if not isinstance(f["line_start"], int) or not isinstance(f["line_end"], int):
            raise ReportError(f"finding {f['id']} line_start/line_end must be integers")
        if f["line_start"] > f["line_end"]:
            raise ReportError(
                f"finding {f['id']} line_start={f['line_start']} > line_end={f['line_end']}"
            )
        ev = f["evidence"]
        if not isinstance(ev, dict):
            raise ReportError(f"finding {f['id']} evidence must be an object")
        for k in REQUIRED_EVIDENCE_FIELDS:
            if k not in ev:
                raise ReportError(f"finding {f['id']} evidence missing field '{k}'")
        rv = f["reviewer"]
        if not isinstance(rv, dict):
            raise ReportError(f"finding {f['id']} reviewer must be an object")
        for k in REQUIRED_REVIEWER_FIELDS:
            if k not in rv:
                raise ReportError(f"finding {f['id']} reviewer missing field '{k}'")
        vr = f["verifier"]
        if not isinstance(vr, dict):
            raise ReportError(f"finding {f['id']} verifier must be an object")
        for k in REQUIRED_VERIFIER_FIELDS:
            if k not in vr:
                raise ReportError(f"finding {f['id']} verifier missing field '{k}'")
        if vr["status"] not in VALID_VERIFIER_STATUSES:
            raise ReportError(
                f"finding {f['id']} verifier.status {vr['status']!r} invalid; "
                f"must be one of {VALID_VERIFIER_STATUSES}"
            )


def _collect_rejected(findings_dir: Path) -> list[dict[str, Any]]:
    """Walk findings/<module>.json and return findings whose verifier.status is
    rejected or needs_more_evidence (kept in the bottom audit-trail section)."""
    out: list[dict[str, Any]] = []
    for p in sorted(findings_dir.glob("*.json")):
        try:
            arr = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(arr, list):
            continue
        for f in arr:
            if not isinstance(f, dict):
                continue
            vr = f.get("verifier") or {}
            if vr.get("status") in ("rejected", "needs_more_evidence"):
                out.append(f)
    return out


class Sha256Resolver:
    def resolve(self, rel_path: str) -> str | None:  # pragma: no cover - protocol
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class FilesystemSha256Resolver(Sha256Resolver):
    workspace_root: Path

    def resolve(self, rel_path: str) -> str | None:
        p = self.workspace_root / rel_path
        if not p.is_file():
            return None
        return hashlib.sha256(p.read_bytes()).hexdigest()


def _build_html(
    *,
    plan: dict[str, Any],
    confirmed: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    css: str,
    js: str,
    sha_resolver: Sha256Resolver,
) -> str:
    run_id = str(plan.get("run_id") or "<unknown>")
    target = str(plan.get("target") or "<unknown>")
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    by_severity = Counter(f["severity"] for f in confirmed)
    by_category = Counter(f["category"] for f in confirmed)
    by_module = Counter(f["module"] for f in confirmed)
    by_confidence = Counter(f["confidence"] for f in confirmed)
    by_verifier_status = Counter(f["verifier"]["status"] for f in confirmed)
    total = len(confirmed)

    parts: list[str] = []
    parts.append("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n")
    parts.append("<meta charset=\"UTF-8\">\n")
    parts.append(
        f"<title>Code Audit Report — {html.escape(run_id)}</title>\n"
    )
    parts.append(f"<style>\n{css}\n</style>\n")
    parts.append("</head>\n<body>\n")

    parts.append("<header class=\"report-banner\">\n")
    parts.append("  <h1>Code Audit Report</h1>\n")
    parts.append("  <dl>\n")
    parts.append(f"    <dt>Run ID</dt><dd>{html.escape(run_id)}</dd>\n")
    parts.append(f"    <dt>Target</dt><dd>{html.escape(target)}</dd>\n")
    parts.append(f"    <dt>Generated</dt><dd>{html.escape(generated_at)}</dd>\n")
    parts.append(f"    <dt>Pack</dt><dd>code-audit v{html.escape(PACK_VERSION)}</dd>\n")
    if total > 0:
        parts.append(
            "    <dt>Visible</dt><dd><span id=\"visible-count\">"
            + str(total)
            + "</span> / "
            + str(total)
            + " findings</dd>\n"
        )
    parts.append("  </dl>\n</header>\n")

    parts.append("<section class=\"summary\">\n")
    parts.append("  <div class=\"stat-row\">\n")
    parts.append(f"    <div class=\"stat-card stat-total\">{total} total</div>\n")
    for sev in VALID_SEVERITIES:
        n = by_severity.get(sev, 0)
        parts.append(
            f"    <div class=\"stat-card stat-{sev}\">{n} {sev}</div>\n"
        )
    parts.append("  </div>\n")
    parts.append(_render_donut(by_severity))
    parts.append(_render_module_table(plan, by_severity, by_module, confirmed))
    parts.append("</section>\n")

    parts.append("<section class=\"filters\">\n")
    parts.append(_render_filter_fieldset("Severity", "severity", VALID_SEVERITIES, by_severity))
    parts.append(_render_filter_fieldset("Confidence", "confidence", VALID_CONFIDENCES, by_confidence))
    parts.append(_render_filter_fieldset("Category", "category", VALID_CATEGORIES, by_category))
    modules_seen = sorted(by_module.keys())
    parts.append(_render_filter_fieldset("Module", "module", tuple(modules_seen), by_module))
    parts.append(
        _render_filter_fieldset(
            "Verifier", "verifier-status", VALID_VERIFIER_STATUSES, by_verifier_status
        )
    )
    parts.append(
        "  <div class=\"filter-actions\">\n"
        "    <button type=\"button\" id=\"btn-select-all\">Select all</button>\n"
        "    <button type=\"button\" id=\"btn-clear-all\">Clear all</button>\n"
        "  </div>\n"
    )
    parts.append("</section>\n")

    parts.append("<main class=\"findings\">\n")
    if not confirmed:
        parts.append("  <div class=\"empty-state\">No confirmed findings in this run.</div>\n")
    else:
        for f in sorted(confirmed, key=_finding_sort_key):
            parts.append(_render_finding_card(f, sha_resolver))
    parts.append(
        "  <div class=\"empty-state\" id=\"empty-state\" style=\"display:none\">"
        "No findings match current filters."
        "</div>\n"
    )
    parts.append("</main>\n")

    if rejected:
        parts.append(_render_rejected_section(rejected))

    parts.append(f"<script>\n{js}\n</script>\n")
    parts.append("</body>\n</html>\n")
    return "".join(parts)


def _finding_sort_key(f: dict[str, Any]) -> tuple[int, str, int]:
    severity_order = {s: i for i, s in enumerate(VALID_SEVERITIES)}
    return (
        severity_order.get(f["severity"], 99),
        f["module"],
        int(f["line_start"]),
    )


def _render_filter_fieldset(
    legend: str,
    filter_name: str,
    values: tuple[str, ...],
    counts: Counter[str],
) -> str:
    rows: list[str] = ["  <fieldset>\n"]
    rows.append(f"    <legend>{html.escape(legend)}</legend>\n")
    for v in values:
        count = counts.get(v, 0)
        rows.append(
            f"    <label><input type=\"checkbox\" data-filter=\"{html.escape(filter_name)}\" "
            f"value=\"{html.escape(v)}\" checked> {html.escape(v)}"
            f" <span>({count})</span></label>\n"
        )
    rows.append("  </fieldset>\n")
    return "".join(rows)


def _render_donut(by_severity: Counter[str]) -> str:
    """Tiny SVG donut, severity colors. Pure stdlib, no D3."""
    total = sum(by_severity.values())
    if total == 0:
        return ""
    radius = 60
    circumference = 2 * 3.14159265 * radius
    colors = {
        "critical": "#c0392b",
        "high":     "#e67e22",
        "medium":   "#f39c12",
        "low":      "#27ae60",
        "info":     "#7f8c8d",
    }
    rows = ['<svg class="severity-donut" width="160" height="160" viewBox="0 0 160 160">']
    offset = 0.0
    for sev in VALID_SEVERITIES:
        n = by_severity.get(sev, 0)
        if n == 0:
            continue
        frac = n / total
        dash = circumference * frac
        gap = circumference - dash
        rows.append(
            f'  <circle cx="80" cy="80" r="{radius}" fill="transparent" '
            f'stroke="{colors[sev]}" stroke-width="24" '
            f'stroke-dasharray="{dash:.2f} {gap:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 80 80)"/>'
        )
        offset += dash
    rows.append(
        f'  <text x="80" y="86" text-anchor="middle" fill="#2c3e50" '
        f'font-size="20" font-weight="700">{total}</text>'
    )
    rows.append("</svg>\n")
    return "\n".join(rows)


def _render_module_table(
    plan: dict[str, Any],
    by_severity: Counter[str],
    by_module: Counter[str],
    confirmed: list[dict[str, Any]],
) -> str:
    modules_in_plan = [m.get("name", "<unknown>") for m in plan.get("modules", [])]
    modules_seen = list(dict.fromkeys(modules_in_plan + sorted(by_module.keys())))
    if not modules_seen:
        return ""
    sev_by_module: dict[str, Counter[str]] = {m: Counter() for m in modules_seen}
    for f in confirmed:
        sev_by_module.setdefault(f["module"], Counter())[f["severity"]] += 1

    rows = ['<table class="by-module-table">\n']
    rows.append("  <thead><tr><th>Module</th>")
    for sev in VALID_SEVERITIES:
        rows.append(f"<th>{html.escape(sev)}</th>")
    rows.append("<th>Total</th></tr></thead>\n  <tbody>\n")
    for m in modules_seen:
        c = sev_by_module.get(m, Counter())
        total = sum(c.values())
        rows.append(f"    <tr><td>{html.escape(m)}</td>")
        for sev in VALID_SEVERITIES:
            n = c.get(sev, 0)
            rows.append(f"<td>{n}</td>")
        rows.append(f"<td><strong>{total}</strong></td></tr>\n")
    rows.append("  </tbody>\n</table>\n")
    return "".join(rows)


def _render_finding_card(f: dict[str, Any], sha_resolver: Sha256Resolver) -> str:
    file_path = f["file"]
    current_sha = sha_resolver.resolve(file_path)
    if current_sha is None:
        drift_banner = (
            '<span class="warning">⚠ file no longer exists; '
            "snippet preserved from audit time</span>"
        )
    elif current_sha != f["file_sha256"]:
        drift_banner = (
            '<span class="warning">⚠ file changed since audit; '
            "line numbers may have shifted</span>"
        )
    else:
        drift_banner = ""

    loc_text = f"{file_path}:{f['line_start']}-{f['line_end']}"

    rows: list[str] = []
    rows.append(
        "  <article class=\"finding\" "
        f"data-severity=\"{html.escape(f['severity'])}\" "
        f"data-category=\"{html.escape(f['category'])}\" "
        f"data-confidence=\"{html.escape(f['confidence'])}\" "
        f"data-module=\"{html.escape(f['module'])}\" "
        f"data-verifier-status=\"{html.escape(f['verifier']['status'])}\">\n"
    )
    rows.append("    <header>\n")
    rows.append(
        f"      <span class=\"badge badge-severity-{html.escape(f['severity'])}\">"
        f"{html.escape(f['severity'])}</span>\n"
    )
    rows.append(
        f"      <span class=\"badge badge-category\">{html.escape(f['category'])}</span>\n"
    )
    rows.append(
        f"      <span class=\"badge badge-confidence-{html.escape(f['confidence'])}\">"
        f"confidence: {html.escape(f['confidence'])}</span>\n"
    )
    rows.append(
        f"      <span class=\"badge badge-id\">{html.escape(f['id'])}</span>\n"
    )
    if drift_banner:
        rows.append(f"      {drift_banner}\n")
    rows.append(f"      <h2>{html.escape(f['title'])}</h2>\n")
    rows.append(
        f"      <code class=\"location\">{html.escape(loc_text)}</code>\n"
    )
    rows.append(
        f"      <button type=\"button\" class=\"btn-copy-location\" "
        f"data-loc=\"{html.escape(loc_text)}\" title=\"Copy location\">📋</button>\n"
    )
    rows.append("    </header>\n")

    rows.append(
        f"    <section class=\"description\">{html.escape(f['description'])}</section>\n"
    )

    ev = f["evidence"]
    rows.append("    <section class=\"evidence\">\n")
    rows.append(
        f"      <pre><code>{html.escape(ev['code_snippet'])}</code></pre>\n"
    )
    rows.append("      <dl>\n")
    rows.append(
        f"        <dt>Reasoning</dt><dd>{html.escape(ev['reasoning'])}</dd>\n"
    )
    rows.append(
        f"        <dt>Trigger</dt><dd>{html.escape(ev['trigger_conditions'])}</dd>\n"
    )
    rows.append(
        f"        <dt>Expected vs Actual</dt><dd>{html.escape(ev['expected_vs_actual'])}</dd>\n"
    )
    related = ev.get("related_files") or []
    if related:
        rows.append("        <dt>Related</dt><dd><ul>\n")
        for r in related:
            rows.append(f"          <li><code>{html.escape(str(r))}</code></li>\n")
        rows.append("        </ul></dd>\n")
    rows.append("      </dl>\n")
    rows.append("    </section>\n")

    rows.append("    <section class=\"suggested-fix\">\n")
    rows.append("      <h3>Suggested fix</h3>\n")
    rows.append(f"      <p>{html.escape(f['suggested_fix'])}</p>\n")
    rows.append("    </section>\n")

    vr = f["verifier"]
    rows.append("    <footer class=\"audit-trail\">\n")
    rows.append(
        "      <div class=\"reviewer\">Reviewed by "
        f"<code>{html.escape(f['reviewer']['agent'])}</code> at "
        f"{html.escape(f['reviewer']['ts'])}</div>\n"
    )
    rows.append(
        "      <div class=\"verifier\">"
        f"<strong>{html.escape(vr['status'])}</strong> by "
        f"<code>{html.escape(vr['agent'])}</code> at "
        f"{html.escape(vr['ts'])}\n"
    )
    rows.append("        <details>\n")
    rows.append("          <summary>Reason &amp; evidence_check</summary>\n")
    rows.append(
        f"          <p><strong>Reason:</strong> {html.escape(vr['reason'])}</p>\n"
    )
    rows.append(
        f"          <p><strong>Evidence check:</strong> {html.escape(vr['evidence_check'])}</p>\n"
    )
    if vr.get("severity_after"):
        rows.append(
            "          <p><strong>Severity adjusted:</strong> "
            f"{html.escape(str(f.get('severity_before', '<unknown>')))} → "
            f"{html.escape(str(vr['severity_after']))}</p>\n"
        )
    rows.append("        </details>\n")
    rows.append("      </div>\n")
    rows.append("    </footer>\n")
    rows.append("  </article>\n")
    return "".join(rows)


def _render_rejected_section(rejected: list[dict[str, Any]]) -> str:
    rows = ["<details class=\"rejected-section\">\n"]
    rows.append(
        f"  <summary>Rejected &amp; needs_more_evidence findings ({len(rejected)})</summary>\n"
    )
    rows.append(
        "  <table>\n    <thead><tr><th>id</th><th>module</th><th>file</th>"
        "<th>status</th><th>reason</th></tr></thead>\n    <tbody>\n"
    )
    for f in rejected:
        vr = f.get("verifier") or {}
        status = vr.get("status", "")
        rows.append(
            "      <tr>"
            f"<td><code>{html.escape(str(f.get('id', '')))}</code></td>"
            f"<td>{html.escape(str(f.get('module', '')))}</td>"
            f"<td><code>{html.escape(str(f.get('file', '')))}</code></td>"
            f"<td class=\"status-{html.escape(status)}\">{html.escape(status)}</td>"
            f"<td>{html.escape(str(vr.get('reason', '')))}</td>"
            "</tr>\n"
        )
    rows.append("    </tbody>\n  </table>\n</details>\n")
    return "".join(rows)


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="render_html",
        description="Render code-audit confirmed.json into a single-file HTML report.",
    )
    p.add_argument("--workspace", type=Path, default=Path.cwd(),
                   help="Workspace root (default: cwd). Used with --run-id.")
    p.add_argument("--run-id", type=str, default=None,
                   help="Run ID under .garage/code-audit/runs/<run-id>/.")
    p.add_argument("--confirmed-path", type=Path, default=None,
                   help="Explicit path to confirmed.json (overrides --workspace/--run-id).")
    p.add_argument("--plan-path", type=Path, default=None,
                   help="Explicit path to plan.json.")
    p.add_argument("--findings-dir", type=Path, default=None,
                   help="Explicit path to findings/ directory.")
    p.add_argument("--output", type=Path, default=None,
                   help="Explicit output HTML path.")
    args = p.parse_args(argv)

    try:
        result = render_report(
            workspace_root=args.workspace,
            run_id=args.run_id,
            confirmed_path=args.confirmed_path,
            plan_path=args.plan_path,
            findings_dir=args.findings_dir,
            output_path=args.output,
        )
    except ReportError as exc:
        print(f"render_html: error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Wrote {result.output_path} ({result.finding_count} findings, "
        f"{result.rejected_count} rejected/needs_more_evidence)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
