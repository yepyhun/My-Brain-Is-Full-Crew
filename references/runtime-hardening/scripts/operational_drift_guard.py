#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPILE_STATUS = ROOT / "Meta" / "Operational" / "Compile-Status.md"
WEEKLY_REVIEW_DIR = ROOT / "02-Areas" / "Personal" / "Stabilization"
SOURCE_DIRS = (
    ROOT / "02-Areas" / "Personal" / "Stabilization",
    ROOT / "02-Areas" / "Personal" / "Admin",
)

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
HEADER_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
BULLET_RE = re.compile(r"^-\s+(?P<value>.+\S)\s*$")
SECTION_NAMES = (
    "What Stayed Open",
    "Preparation Needed",
    "Main Priorities",
)
GENERIC_BULLETS = {
    "Mi zárult le.",
    "Mi maradt nyitva.",
    "Mit mutatnak a napi mérések / `Measurements`.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    return parser.parse_args()


def parse_last_full_compile(path: Path) -> date | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("last-full-compile:"):
            continue
        _, raw = stripped.split(":", 1)
        raw = raw.strip().strip("\"'")
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def weekly_review_path(day: date) -> Path:
    return WEEKLY_REVIEW_DIR / f"{day.isoformat()} Weekly Review.md"


def extract_section_bullets(path: Path, section_names: tuple[str, ...]) -> dict[str, list[str]]:
    sections = {name: [] for name in section_names}
    if not path.exists():
        return sections

    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        header_match = HEADER_RE.match(line.strip())
        if header_match:
            title = header_match.group("title").strip()
            current = title if title in sections else None
            continue
        if not current:
            continue
        bullet_match = BULLET_RE.match(line.strip())
        if bullet_match:
            sections[current].append(bullet_match.group("value").strip())
    return sections


def note_date_from_path(path: Path) -> date | None:
    match = DATE_RE.search(path.name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def collect_newer_sources(since: date | None, until: date) -> list[str]:
    results: list[str] = []
    for directory in SOURCE_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            note_date = note_date_from_path(path)
            if not note_date:
                continue
            if since and note_date <= since:
                continue
            if note_date > until:
                continue
            results.append(str(path.relative_to(ROOT)))
    return results


def flatten_non_empty_sections(sections: dict[str, list[str]]) -> list[str]:
    items: list[str] = []
    for name in SECTION_NAMES:
        values = sections.get(name, [])
        items.extend(value for value in values if value not in GENERIC_BULLETS)
    return items


def main() -> int:
    args = parse_args()
    last_full_compile = parse_last_full_compile(COMPILE_STATUS)
    review_path = weekly_review_path(args.date)
    review_sections = extract_section_bullets(review_path, SECTION_NAMES)
    actionable_signals = flatten_non_empty_sections(review_sections)
    newer_sources = collect_newer_sources(last_full_compile, args.date)

    stale = last_full_compile is None or last_full_compile < args.date
    has_newer_review_signal = review_path.exists() and bool(actionable_signals)
    status = "stale" if stale and (has_newer_review_signal or bool(newer_sources)) else "ok"

    payload = {
        "date": args.date.isoformat(),
        "compile_status_path": str(COMPILE_STATUS.relative_to(ROOT)),
        "last_full_compile": last_full_compile.isoformat() if last_full_compile else "",
        "stale": stale,
        "same_day_weekly_review_path": str(review_path.relative_to(ROOT)) if review_path.exists() else "",
        "weekly_review_sections": review_sections,
        "actionable_signals": actionable_signals,
        "newer_source_notes": newer_sources,
        "status": status,
        "reason": (
            "compiled operational layer predates newer source notes"
            if status == "stale"
            else ""
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
