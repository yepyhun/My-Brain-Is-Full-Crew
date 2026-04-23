#!/usr/bin/env python3
"""Guard against lossy inbox merges that drop source-bearing captures."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / "00-Inbox"
HEALTH_REPORTS_DIR = ROOT / "Meta" / "health-reports"
PROCESSED_INBOX_DIR = ROOT / "04-Archive" / "Processed-Inbox"
DIGEST_DASH = "\u2014"

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?\d[\d ()/-]{6,}\d)")
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
ADDRESS_RE = re.compile(
    r"\b(?:Budapest|utca|u\.|ut|ter|krt\.|korut|koz|emelet|hazszam)\b",
    re.IGNORECASE,
)
EVIDENCE_RE = re.compile(
    r"\b(?:hirdetes|uzenetvaltas|bizonylat|foto|video|idorendi|"
    r"kinek lehet irni|mit vigyek|jogsegely|jogi segitseg|tanacs)\b",
    re.IGNORECASE,
)
MERGE_ENTRY_RE = re.compile(r"^- `(?P<source>[^`]+)`\s*$")
WIKILINK_RE = re.compile(r"\[\[(?P<target>[^\]|#]+)")


@dataclass
class MergeFinding:
    source: str
    merged_into: str
    source_retained_at: str
    status: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify-note", help="Classify whether an inbox note is safe for merge-only handling.")
    classify.add_argument("--path", required=True, help="Path to the note, relative to the repo root or absolute.")

    validate = subparsers.add_parser("validate-report", help="Validate canonical merges in an Inbox Triage Digest.")
    validate.add_argument("--report", help="Path to a specific Inbox Triage Digest markdown file.")
    validate.add_argument("--date", help="Digest date in YYYY-MM-DD format; resolves Meta/health-reports/<date> - Inbox Triage Digest.md.")

    return parser.parse_args()


def resolve_repo_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def existing_note_path(raw: str) -> Path:
    path = resolve_repo_path(raw)
    if path.exists():
        return path
    if path.suffix:
        return path
    md_path = path.with_suffix(".md")
    if md_path.exists():
        return md_path
    return path


def classify_note(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "path": str(path),
            "status": "missing",
            "safe_merge_only": False,
            "signals": [],
            "reason": "note_not_found",
        }

    text = path.read_text(encoding="utf-8", errors="ignore")
    signals: list[str] = []
    if EMAIL_RE.search(text):
        signals.append("contains_email")
    if PHONE_RE.search(text):
        signals.append("contains_phone")
    if URL_RE.search(text):
        signals.append("contains_url")
    if ADDRESS_RE.search(text):
        signals.append("contains_address_like_text")
    if EVIDENCE_RE.search(text):
        signals.append("contains_evidence_or_contact_keywords")

    bullet_lines = sum(1 for line in text.splitlines() if line.lstrip().startswith(("- ", "* ")))
    if bullet_lines >= 4:
        signals.append("contains_multi_item_list")

    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    long_lines = sum(1 for line in nonempty_lines if len(line) >= 120)
    if long_lines >= 2:
        signals.append("contains_long_prose_blocks")

    paragraphs = [block.strip() for block in text.split("\n\n") if block.strip()]
    prose_paragraphs = [block for block in paragraphs if not block.startswith("---") and len(block.split()) >= 20]
    if len(prose_paragraphs) >= 2:
        signals.append("contains_multi_paragraph_context")

    source_bearing = bool(signals)
    return {
        "path": str(path.relative_to(ROOT)),
        "status": "watch" if source_bearing else "ok",
        "safe_merge_only": not source_bearing,
        "signals": signals,
        "reason": "source_bearing_capture" if source_bearing else "atomic_or_low_context_note",
        "recommended_retention_lane": str(PROCESSED_INBOX_DIR.relative_to(ROOT)) if source_bearing else "",
    }


def resolve_digest_path(report: str | None, day: str | None) -> Path:
    if report:
        return resolve_repo_path(report)
    if not day:
        raise ValueError("Either --report or --date is required.")
    return HEALTH_REPORTS_DIR / f"{day} {DIGEST_DASH} Inbox Triage Digest.md"


def link_target_from_line(line: str) -> str:
    match = WIKILINK_RE.search(line)
    if match:
        return match.group("target").strip()
    tick_start = line.find("`")
    if tick_start != -1:
        tick_end = line.find("`", tick_start + 1)
        if tick_end != -1:
            return line[tick_start + 1 : tick_end].strip()
    return ""


def parse_canonical_merges(report_path: Path) -> list[MergeFinding]:
    text = report_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    in_section = False
    findings: list[MergeFinding] = []
    current: MergeFinding | None = None

    for line in lines:
        if line.startswith("## "):
            if line.strip() == "## Canonical Merges":
                in_section = True
                continue
            if in_section:
                break
        if not in_section:
            continue
        match = MERGE_ENTRY_RE.match(line)
        if match:
            if current is not None:
                findings.append(current)
            current = MergeFinding(
                source=match.group("source").strip(),
                merged_into="",
                source_retained_at="",
                status="watch",
                reason="merge_receipt_incomplete",
            )
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- merged into "):
            current.merged_into = link_target_from_line(stripped)
        elif stripped.startswith("- source retained at "):
            current.source_retained_at = link_target_from_line(stripped)

    if current is not None:
        findings.append(current)
    return findings


def validate_report(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "report_path": str(path),
            "status": "missing",
            "findings": [],
            "reason": "report_not_found",
        }

    findings = parse_canonical_merges(path)
    if not findings:
        return {
            "report_path": str(path.relative_to(ROOT)),
            "status": "ok",
            "findings": [],
            "reason": "no_canonical_merges",
        }

    worst = "ok"
    payload_findings: list[dict[str, object]] = []
    for item in findings:
        source_exists = existing_note_path(item.source).exists()
        retained_exists = existing_note_path(item.source_retained_at).exists() if item.source_retained_at else False

        if not item.merged_into:
            item.status = "drift"
            item.reason = "missing_merge_target"
        elif source_exists:
            item.status = "ok"
            item.reason = "source_still_exists"
        elif item.source_retained_at and retained_exists:
            item.status = "ok"
            item.reason = "source_retained_elsewhere"
        elif item.source_retained_at and not retained_exists:
            item.status = "drift"
            item.reason = "source_retention_path_missing"
        else:
            item.status = "drift"
            item.reason = "lossy_merge_without_retained_source"

        if item.status == "drift":
            worst = "drift"
        elif item.status == "watch" and worst == "ok":
            worst = "watch"

        payload_findings.append(
            {
                "source": item.source,
                "merged_into": item.merged_into,
                "source_retained_at": item.source_retained_at,
                "source_exists": source_exists,
                "retained_exists": retained_exists,
                "status": item.status,
                "reason": item.reason,
            }
        )

    return {
        "report_path": str(path.relative_to(ROOT)),
        "status": worst,
        "findings": payload_findings,
        "reason": "",
    }


def main() -> int:
    args = parse_args()
    if args.command == "classify-note":
        payload = classify_note(resolve_repo_path(args.path))
    else:
        payload = validate_report(resolve_digest_path(args.report, args.date))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
