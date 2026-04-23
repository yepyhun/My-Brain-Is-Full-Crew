#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

try:
    import temporal_radar
except ModuleNotFoundError:  # pragma: no cover
    from scripts import temporal_radar

ROOT = Path(__file__).resolve().parent.parent
OPEN_LOOPS_PATH = ROOT / "Meta" / "Operational" / "Open-Loops.md"
SURFACE_PATH = ROOT / "Meta" / "Operational" / "Backlog-Hygiene.md"
CRITICAL_BUCKET = "kritikus / kozeljovo"
SOURCE_REFS_HEADER = "source refs"
DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
HEADING_RE = re.compile(r"^(?P<hashes>#{2,6})\s+(?P<title>.+?)\s*$")
FIELD_RE = re.compile(r"^-+\s*(?P<label>Status|Context|Next step|Why it matters|Source refs):\s*(?P<body>.*)$")
LIST_RE = re.compile(r"^(?:-\s+|\d+\.\s+)(?P<body>.+\S)\s*$")
WIKILINK_RE = re.compile(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]")
STATUS_IGNORE = {"done", "cancelled", "closed"}


@dataclass
class LoopThread:
    bucket: str
    title: str
    status: str = ""
    context: str = ""
    next_step: str = ""
    why: str = ""
    source_refs: list[str] = field(default_factory=list)


def root_for(root: Path | None = None) -> Path:
    return root.resolve() if root else ROOT


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(ch for ch in folded if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w\s:/.-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def tokens(text: str) -> set[str]:
    base = set()
    for token in normalize(text).split():
        if len(token) >= 4 and re.search(r"[a-z]", token):
            base.add(token)
        for part in re.split(r"[-/]", token):
            if len(part) >= 4 and re.search(r"[a-z]", part):
                base.add(part)
    return base


def token_overlap(left: set[str], right: set[str]) -> int:
    return len(left & right)


def unwrap_wikilinks(text: str) -> str:
    return WIKILINK_RE.sub(r"\1", text)


def latest_source_date(thread: LoopThread, target_date: date) -> date | None:
    dates: list[date] = []
    for ref in thread.source_refs:
        raw = unwrap_wikilinks(ref)
        if "Meta/Operational/Open-Loops" in raw:
            continue
        for match in DATE_RE.findall(raw):
            try:
                ref_date = date.fromisoformat(match)
            except ValueError:
                continue
            if ref_date <= target_date:
                dates.append(ref_date)
    return max(dates) if dates else None


def explicit_future_date(text: str, target_date: date) -> date | None:
    for match in DATE_RE.findall(text):
        try:
            when = date.fromisoformat(match)
        except ValueError:
            continue
        if when >= target_date:
            return when
    return None


def parse_open_loops(path: Path) -> list[LoopThread]:
    if not path.exists():
        return []
    bucket = ""
    current: LoopThread | None = None
    source_ref_mode = False
    threads: list[LoopThread] = []

    def flush() -> None:
        nonlocal current, source_ref_mode
        if current and current.title:
            threads.append(current)
        current = None
        source_ref_mode = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            title = heading_match.group("title").strip()
            level = len(heading_match.group("hashes"))
            if level == 2:
                flush()
                bucket = title
            elif level == 3:
                flush()
                current = LoopThread(bucket=bucket, title=title)
            continue

        if current is None:
            continue

        field_match = FIELD_RE.match(raw_line.strip())
        if field_match:
            label = normalize(field_match.group("label"))
            body = field_match.group("body").strip()
            source_ref_mode = label == SOURCE_REFS_HEADER
            if label == "status":
                current.status = body
            elif label == "context":
                current.context = body
            elif label == "next step":
                current.next_step = body
            elif label == "why it matters":
                current.why = body
            elif label == SOURCE_REFS_HEADER and body:
                current.source_refs.append(body)
            continue

        if source_ref_mode:
            bullet_match = LIST_RE.match(raw_line.strip())
            if bullet_match:
                current.source_refs.append(bullet_match.group("body").strip())
                continue
            if raw_line.strip():
                source_ref_mode = False

    flush()
    return threads


def event_tokens(event: temporal_radar.Event) -> set[str]:
    values = [event.title, event.path.stem]
    if event.related_note:
        raw = unwrap_wikilinks(event.related_note).strip()
        values.append(Path(raw.split("|", 1)[0]).stem)
    return tokens(" ".join(values))


def load_events(root: Path) -> list[temporal_radar.Event]:
    events_dir = root / "Meta" / "Temporal" / "Events"
    if not events_dir.exists():
        return []
    events: list[temporal_radar.Event] = []
    for path in sorted(events_dir.glob("*.md")):
        event = temporal_radar.load_event(path)
        if event:
            events.append(event)
    return events


def active_temporal_match(thread: LoopThread, events: list[temporal_radar.Event], target_date: date) -> temporal_radar.Event | None:
    required_date = explicit_future_date(thread.next_step, target_date)
    thread_tokens = tokens(" ".join([thread.title, thread.next_step, *thread.source_refs]))
    if not thread_tokens:
        return None
    for event in events:
        if event.status != "active":
            continue
        if required_date and event.event_date != required_date:
            continue
        shared = thread_tokens & event_tokens(event)
        if len(shared) >= 2:
            return event
        if len(shared) == 1 and any(len(token) >= 8 for token in shared):
            return event
    return None


def build_report(
    target_date: date,
    aging_days: int = 14,
    stale_days: int = 30,
    root: Path | None = None,
) -> dict[str, Any]:
    real_root = root_for(root)
    threads = parse_open_loops(real_root / "Meta" / "Operational" / "Open-Loops.md")
    events = load_events(real_root)

    review_now: list[dict[str, Any]] = []
    aging: list[dict[str, Any]] = []
    temporal_covered: list[dict[str, Any]] = []
    healthy_count = 0

    for thread in threads:
        bucket_norm = normalize(thread.bucket)
        status_norm = normalize(thread.status)
        if bucket_norm == CRITICAL_BUCKET or status_norm in STATUS_IGNORE:
            continue

        match = active_temporal_match(thread, events, target_date)
        next_date = explicit_future_date(thread.next_step, target_date)
        last_source = latest_source_date(thread, target_date)
        common = {
            "bucket": thread.bucket,
            "title": thread.title,
            "status": thread.status,
            "next_step": thread.next_step,
            "context": thread.context,
            "source_refs": thread.source_refs,
            "last_dated_source": last_source.isoformat() if last_source else "",
        }

        if next_date and not match:
            review_now.append(
                {
                    **common,
                    "reason": "temporal_promotion_gap",
                    "suggested_action": "promote_temporal",
                    "target_date": next_date.isoformat(),
                    "age_days": None,
                }
            )
            continue

        if match:
            temporal_covered.append(
                {
                    **common,
                    "reason": "covered_by_active_temporal_event",
                    "suggested_action": "keep_background_or_close",
                    "temporal_event_path": str(match.path.relative_to(real_root)),
                    "age_days": (target_date - last_source).days if last_source else None,
                }
            )
            continue

        if last_source is None:
            review_now.append(
                {
                    **common,
                    "reason": "source_thin_background_loop",
                    "suggested_action": "review_close_or_reanchor",
                    "target_date": "",
                    "age_days": None,
                }
            )
            continue

        age_days = (target_date - last_source).days
        if age_days >= stale_days:
            review_now.append(
                {
                    **common,
                    "reason": "stale_background_loop",
                    "suggested_action": "review_close_park_or_rewrite",
                    "target_date": "",
                    "age_days": age_days,
                }
            )
        elif age_days >= aging_days:
            aging.append(
                {
                    **common,
                    "reason": "aging_background_loop",
                    "suggested_action": "touch_keep_or_close",
                    "target_date": "",
                    "age_days": age_days,
                }
            )
        else:
            healthy_count += 1

    review_now.sort(key=lambda item: (item["reason"], -(item["age_days"] or -1), item["title"]))
    aging.sort(key=lambda item: (-(item["age_days"] or -1), item["title"]))
    temporal_covered.sort(key=lambda item: item["title"])

    status = "watch" if review_now else "ok"
    return {
        "date": target_date.isoformat(),
        "status": status,
        "aging_days": aging_days,
        "stale_days": stale_days,
        "review_now": review_now,
        "aging": aging,
        "temporal_covered": temporal_covered,
        "healthy_background_count": healthy_count,
        "open_loops_path": str((real_root / "Meta" / "Operational" / "Open-Loops.md").relative_to(real_root)),
        "surface_path": str((real_root / "Meta" / "Operational" / "Backlog-Hygiene.md").relative_to(real_root)),
    }


def deliverable_text(payload: dict[str, Any]) -> str:
    review_now = payload.get("review_now", [])
    aging = payload.get("aging", [])
    temporal_covered = payload.get("temporal_covered", [])
    if review_now:
        titles = ", ".join(item["title"] for item in review_now[:3])
        return (
            f"A heti hatter-backlog review most {len(review_now)} szalat ker atnezesre. "
            f"A fo review-now tetelek: {titles}. "
            f"{len(aging)} tovabbi szal csak oregszik, de nem napi drift."
        )
    if aging:
        titles = ", ".join(item["title"] for item in aging[:3])
        return (
            f"A hatter-backlogban nincs azonnali review-now tetel, de {len(aging)} szal oregszik. "
            f"A legregebb aktivak: {titles}."
        )
    if temporal_covered:
        return (
            f"A hatter-backlog jelenleg rendezett. {len(temporal_covered)} szal mar temporal lane-ben kovetett, "
            "kulon review-now tetel nincs."
        )
    return "A hatter-backlog jelenleg rendezett; nincs kulon review-now vagy oregedo szal."


def render_surface(payload: dict[str, Any]) -> str:
    lines = [
        "---",
        "type: operational-backlog-hygiene",
        f'date: "{payload["date"]}"',
        'status: "active"',
        'maintained-by: "backlog-hygiene-audit"',
        f'aging-days: "{payload["aging_days"]}"',
        f'stale-days: "{payload["stale_days"]}"',
        "---",
        "",
        f'# Backlog Hygiene - {payload["date"]}',
        "",
        "## Status",
        "",
        f'- Review now: `{len(payload["review_now"])}`',
        f'- Aging: `{len(payload["aging"])}`',
        f'- Covered by temporal: `{len(payload["temporal_covered"])}`',
        f'- Healthy background loops: `{payload["healthy_background_count"]}`',
        "",
        "## Deliverable",
        "",
        f'- {deliverable_text(payload)}',
        "",
        "## Review Now",
        "",
    ]
    if payload["review_now"]:
        for item in payload["review_now"]:
            age = f"{item['age_days']} napos" if item["age_days"] is not None else "nincs datalt source"
            lines.extend(
                [
                    f"### {item['title']}",
                    f"- Bucket: `{item['bucket']}`",
                    f"- Reason: `{item['reason']}`",
                    f"- Suggested action: `{item['suggested_action']}`",
                    f"- Age / source: `{age}`",
                    f"- Next step: {item['next_step'] or 'Nincs'}",
                ]
            )
            if item["source_refs"]:
                lines.append("- Source refs:")
                lines.extend([f"  - {ref}" for ref in item["source_refs"]])
            lines.append("")
    else:
        lines.extend(["- Nincs review-now backlog higienia tetel.", ""])

    lines.extend(["## Aging", ""])
    if payload["aging"]:
        for item in payload["aging"]:
            lines.extend(
                [
                    f"### {item['title']}",
                    f"- Bucket: `{item['bucket']}`",
                    f"- Age: `{item['age_days']} nap`",
                    f"- Suggested action: `{item['suggested_action']}`",
                    f"- Next step: {item['next_step'] or 'Nincs'}",
                    "",
                ]
            )
    else:
        lines.extend(["- Nincs oregedo hatter-szal.", ""])

    lines.extend(["## Covered By Temporal", ""])
    if payload["temporal_covered"]:
        for item in payload["temporal_covered"]:
            lines.extend(
                [
                    f"### {item['title']}",
                    f"- Temporal source: [[{item['temporal_event_path']}]]",
                    f"- Suggested action: `{item['suggested_action']}`",
                    "",
                ]
            )
    else:
        lines.extend(["- Nincs temporal lane altal fedett hatter-szal.", ""])

    lines.extend(["## Source Refs", "", f"- Open loops: [[{payload['open_loops_path']}]]"])
    return "\n".join(lines) + "\n"


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Date: {payload['date']}",
        f"Status: {payload['status']}",
        f"Review now: {len(payload['review_now'])}",
        f"Aging: {len(payload['aging'])}",
        f"Covered by temporal: {len(payload['temporal_covered'])}",
    ]
    for item in payload["review_now"]:
        lines.append(f"- review :: {item['title']} :: {item['reason']} :: {item['suggested_action']}")
    for item in payload["aging"]:
        lines.append(f"- aging :: {item['title']} :: {item['age_days']} nap")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--aging-days", type=int, default=14)
    parser.add_argument("--stale-days", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(args.date, aging_days=args.aging_days, stale_days=args.stale_days, root=args.root)
    if args.write:
        real_root = root_for(args.root)
        surface_path = real_root / "Meta" / "Operational" / "Backlog-Hygiene.md"
        surface_path.parent.mkdir(parents=True, exist_ok=True)
        surface_path.write_text(render_surface(payload), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
