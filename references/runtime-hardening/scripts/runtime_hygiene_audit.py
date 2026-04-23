#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    import canonical_deliverable_runtime
    import coherence_compiler
    import temporal_radar
except ModuleNotFoundError:  # pragma: no cover - package import fallback for tests
    from scripts import canonical_deliverable_runtime, coherence_compiler, temporal_radar

ROOT = Path(__file__).resolve().parent.parent
DATE_FIELD_RE = re.compile(r'(?m)^date:\s*"(?P<value>\d{4}-\d{2}-\d{2})"\s*$')
CONFIDENCE_RE = re.compile(r'(?m)^focus-confidence:\s*"(?P<value>[^"]+)"\s*$')
HEADER_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--grace-days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def root_for(path: Path | None) -> Path:
    return path if path is not None else ROOT


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def frontmatter_value(path: Path, pattern: re.Pattern[str]) -> str:
    match = pattern.search(read_text(path))
    return match.group("value").strip() if match else ""


def parse_focus_titles(path: Path, section_name: str) -> list[str]:
    if not path.exists():
        return []
    current = ""
    titles: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        header = HEADER_RE.match(line)
        if not header:
            continue
        hashes = header.group("hashes")
        title = header.group("title").strip()
        if hashes == "##":
            current = title
            continue
        if hashes == "###" and current == section_name:
            titles.append(re.sub(r"^\d+\.\s+", "", title).strip())
    return titles


def parse_focus_bullets(path: Path, section_name: str) -> list[str]:
    if not path.exists():
        return []
    current = ""
    items: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        header = HEADER_RE.match(line.strip())
        if header and header.group("hashes") == "##":
            current = header.group("title").strip()
            continue
        if current != section_name:
            continue
        if line.startswith("- "):
            items.append(line[2:].strip())
    return items


def title_covered(title: str, surfaced: list[str]) -> bool:
    normalized_title = coherence_compiler.normalize(title)
    for item in surfaced:
        normalized_item = coherence_compiler.normalize(item)
        if normalized_title in normalized_item or normalized_item in normalized_title:
            return True
        title_tokens = {token for token in normalized_title.split() if len(token) >= 4}
        item_tokens = {token for token in normalized_item.split() if len(token) >= 4}
        if title_tokens & item_tokens:
            return True
    return False


def stale_temporal_events(target_date: date, grace_days: int, root: Path | None = None) -> list[str]:
    real_root = root_for(root)
    original_events_dir = temporal_radar.EVENTS_DIR
    try:
        temporal_radar.EVENTS_DIR = real_root / "Meta" / "Temporal" / "Events"
        events, _errors = temporal_radar.load_events()
    finally:
        temporal_radar.EVENTS_DIR = original_events_dir

    cutoff = target_date - timedelta(days=grace_days)
    stale = []
    for event in events:
        if event.status != "active":
            continue
        if event.event_date <= cutoff:
            stale.append(f"{event.event_date.isoformat()} {event.title}".strip())
    return stale


def build_report(target_date: date, grace_days: int = 7, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    today_focus_path = real_root / "Meta" / "Operational" / "Today-Focus.md"
    weekly_focus_path = real_root / "Meta" / "Operational" / "Weekly-Focus.md"
    open_loops_path = real_root / "Meta" / "Operational" / "Open-Loops.md"

    today_titles = parse_focus_titles(today_focus_path, "Strategic Focus")
    today_fixed_commitments = parse_focus_bullets(today_focus_path, "Fixed Commitments")
    weekly_titles = parse_focus_titles(weekly_focus_path, "This Week Focus")
    surfaced_titles = today_titles + today_fixed_commitments + weekly_titles
    critical_loops = [
        entry.title
        for entry in coherence_compiler.parse_open_loops(open_loops_path)
        if entry.band == "Kritikus / kozeljovo" and entry.status.casefold() in {"open", "active", "pending"}
    ]
    uncovered = [title for title in critical_loops if not title_covered(title, surfaced_titles)]

    today_focus_date = frontmatter_value(today_focus_path, DATE_FIELD_RE)
    weekly_focus_date = frontmatter_value(weekly_focus_path, DATE_FIELD_RE)
    today_focus_confidence = frontmatter_value(today_focus_path, CONFIDENCE_RE)
    weekly_focus_confidence = frontmatter_value(weekly_focus_path, CONFIDENCE_RE)
    stale_events = stale_temporal_events(target_date, grace_days, real_root)
    today_deliverable = canonical_deliverable_runtime.build_payload("today", target_date, root=real_root)
    weekly_deliverable = canonical_deliverable_runtime.build_payload("weekly", target_date, root=real_root)

    missing_or_stale_surfaces = []
    if not today_focus_path.exists():
        missing_or_stale_surfaces.append("Today-Focus.md missing")
    elif today_focus_date != target_date.isoformat():
        missing_or_stale_surfaces.append("Today-Focus.md date mismatch")
    if not weekly_focus_path.exists():
        missing_or_stale_surfaces.append("Weekly-Focus.md missing")
    elif weekly_focus_date != target_date.isoformat():
        missing_or_stale_surfaces.append("Weekly-Focus.md date mismatch")

    deliverable_issues = []
    if today_deliverable["status"] == "drift":
        deliverable_issues.append(f"Today-Focus deliverable issue: {today_deliverable['reason'] or 'drift'}")
    if weekly_deliverable["status"] == "drift":
        deliverable_issues.append(f"Weekly-Focus deliverable issue: {weekly_deliverable['reason'] or 'drift'}")

    status = "ok"
    if missing_or_stale_surfaces or deliverable_issues or stale_events:
        status = "drift"
    elif uncovered or today_focus_confidence == "watch" or weekly_focus_confidence == "watch":
        status = "watch"

    return {
        "date": target_date.isoformat(),
        "status": status,
        "today_focus_confidence": today_focus_confidence,
        "weekly_focus_confidence": weekly_focus_confidence,
        "missing_or_stale_surfaces": missing_or_stale_surfaces,
        "deliverable_issues": deliverable_issues,
        "critical_loop_coverage_gaps": uncovered,
        "stale_temporal_events": stale_events,
        "surface_paths": {
            "today": str(today_focus_path.relative_to(real_root)),
            "weekly": str(weekly_focus_path.relative_to(real_root)),
        },
    }


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Date: {payload['date']}",
        f"Status: {payload['status']}",
        f"Today focus confidence: {payload['today_focus_confidence'] or 'unknown'}",
        f"Weekly focus confidence: {payload['weekly_focus_confidence'] or 'unknown'}",
    ]
    if payload["missing_or_stale_surfaces"]:
        lines.append("Surface issues:")
        for item in payload["missing_or_stale_surfaces"]:
            lines.append(f"- {item}")
    if payload["deliverable_issues"]:
        lines.append("Deliverable issues:")
        for item in payload["deliverable_issues"]:
            lines.append(f"- {item}")
    if payload["critical_loop_coverage_gaps"]:
        lines.append("Coverage gaps:")
        for item in payload["critical_loop_coverage_gaps"]:
            lines.append(f"- {item}")
    if payload["stale_temporal_events"]:
        lines.append("Stale temporal events:")
        for item in payload["stale_temporal_events"]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    payload = build_report(args.date, args.grace_days)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
