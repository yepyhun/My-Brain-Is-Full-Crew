#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import inbox_lossy_merge_guard
except ModuleNotFoundError:  # pragma: no cover
    from scripts import inbox_lossy_merge_guard

ROOT = Path(__file__).resolve().parent.parent
HEALTH_REPORTS_DIR = ROOT / "Meta" / "health-reports"
PROCESSED_INBOX_DIR = ROOT / "04-Archive" / "Processed-Inbox"
STATUS_PRIORITY = {"drift": 3, "watch": 2, "missing": 2, "ok": 0, "no-report": 0}


def root_for(root: Path | None = None) -> Path:
    return root.resolve() if root else ROOT


def digest_paths(root: Path) -> list[Path]:
    if not (root / "Meta" / "health-reports").exists():
        return []
    return sorted((root / "Meta" / "health-reports").glob("*Inbox Triage Digest.md"))


def resolve_under_root(root: Path, raw: str) -> Path:
    raw = raw.strip()
    if not raw:
        return root / "__missing__"
    candidate = root / raw
    if candidate.exists():
        return candidate
    if candidate.suffix != ".md" and candidate.with_suffix(".md").exists():
        return candidate.with_suffix(".md")
    return candidate


def validate_digest(path: Path, root: Path) -> dict[str, Any]:
    findings = inbox_lossy_merge_guard.parse_canonical_merges(path)
    if not findings:
        return {
            "report_path": str(path.relative_to(root)),
            "status": "ok",
            "reason": "no_canonical_merges",
            "findings": [],
        }

    payload_findings: list[dict[str, Any]] = []
    worst = "ok"
    for item in findings:
        source_exists = resolve_under_root(root, item.source).exists()
        retained_exists = resolve_under_root(root, item.source_retained_at).exists() if item.source_retained_at else False
        status = "ok"
        reason = ""
        if not item.merged_into:
            status = "drift"
            reason = "missing_merge_target"
        elif source_exists:
            status = "ok"
            reason = "source_still_exists"
        elif not item.source_retained_at:
            status = "drift"
            reason = "missing_source_retention"
        elif retained_exists:
            status = "ok"
            reason = "source_retained"
        else:
            status = "drift"
            reason = "retained_source_missing"
        if STATUS_PRIORITY.get(status, 0) > STATUS_PRIORITY.get(worst, 0):
            worst = status
        payload_findings.append(
            {
                "source": item.source,
                "merged_into": item.merged_into,
                "source_retained_at": item.source_retained_at,
                "status": status,
                "reason": reason,
            }
        )
    return {
        "report_path": str(path.relative_to(root)),
        "status": worst,
        "reason": "" if worst == "ok" else "merge_receipt_problem",
        "findings": payload_findings,
    }


def build_report(root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    digests = digest_paths(real_root)
    retained_paths: set[str] = set()
    report_summaries: list[dict[str, Any]] = []
    worst_status = "ok"

    for digest in digests:
        payload = validate_digest(digest, real_root)
        report_summaries.append(
            {
                "report_path": payload.get("report_path", str(digest.relative_to(real_root))),
                "status": payload.get("status", "ok"),
                "reason": payload.get("reason", ""),
                "finding_count": len(payload.get("findings", [])),
            }
        )
        for finding in payload.get("findings", []):
            retained = str(finding.get("source_retained_at", "")).strip()
            if retained:
                retained_paths.add(retained)
        if STATUS_PRIORITY.get(str(payload.get("status", "ok")), 0) > STATUS_PRIORITY.get(worst_status, 0):
            worst_status = str(payload.get("status", "ok"))

    orphan_processed_inbox_files: list[str] = []
    processed_inbox_dir = real_root / "04-Archive" / "Processed-Inbox"
    if processed_inbox_dir.exists():
        for path in sorted(processed_inbox_dir.rglob("*.md")):
            rel = str(path.relative_to(real_root))
            if rel.endswith("README.md"):
                continue
            if rel not in retained_paths:
                orphan_processed_inbox_files.append(rel)

    status = worst_status
    if orphan_processed_inbox_files:
        status = "drift"

    return {
        "status": status,
        "digest_count": len(digests),
        "reports": report_summaries,
        "retained_source_count": len(retained_paths),
        "orphan_processed_inbox_files": orphan_processed_inbox_files,
        "processed_inbox_path": str(processed_inbox_dir.relative_to(real_root)),
    }


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Digest count: {payload['digest_count']}",
        f"Retained source count: {payload['retained_source_count']}",
    ]
    if payload["reports"]:
        lines.append("Reports:")
        for report in payload["reports"]:
            lines.append(f"- {report['status']} :: {report['report_path']} :: {report['reason']}")
    if payload["orphan_processed_inbox_files"]:
        lines.append("Orphan processed inbox files:")
        for item in payload["orphan_processed_inbox_files"]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(root=args.root)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
