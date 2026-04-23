#!/usr/bin/env python3
"""Compile a deterministic temporal reminder surface from canonical event notes."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import date, datetime
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
EVENTS_DIR = ROOT / "Meta" / "Temporal" / "Events"
DEFAULT_OUTPUT = ROOT / "Meta" / "Operational" / "Temporal-Radar.md"
GENERATED_AT_RE = re.compile(r'(?m)^generated-at:\s*"[^"]*"\s*$')


@dataclass
class Event:
    path: Path
    title: str
    status: str
    event_date: date
    event_time: str | None
    timezone: str | None
    kind: str | None
    priority: str | None
    remind_days_before: list[int]
    related_note: str | None


def parse_value(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in "\"'" and raw[-1] == raw[0]:
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        try:
            value = ast.literal_eval(raw)
            return value if isinstance(value, list) else [value]
        except Exception:
            return []
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        return raw


def parse_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}
    data: dict[str, Any] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = parse_value(value)
    return data


def parse_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def load_event(path: Path) -> Event | None:
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm.get("type") != "temporal-event":
        return None
    status = str(fm.get("status", "active")).strip()
    if status not in {"active", "done", "cancelled"}:
        status = "active"
    try:
        event_date = date.fromisoformat(str(fm["event-date"]))
    except Exception as exc:
        raise ValueError(f"invalid event-date ({exc})")
    remind_days_before = fm.get("remind-days-before", [])
    if isinstance(remind_days_before, int):
        remind_days_before = [remind_days_before]
    remind_days_before = [int(x) for x in remind_days_before]
    return Event(
        path=path,
        title=parse_title(text, path.stem),
        status=status,
        event_date=event_date,
        event_time=str(fm["event-time"]).strip() if fm.get("event-time") else None,
        timezone=str(fm["timezone"]).strip() if fm.get("timezone") else None,
        kind=str(fm["kind"]).strip() if fm.get("kind") else None,
        priority=str(fm["priority"]).strip() if fm.get("priority") else None,
        remind_days_before=sorted(set(remind_days_before)),
        related_note=str(fm["related-note"]).strip() if fm.get("related-note") else None,
    )


def load_events() -> tuple[list[Event], list[str]]:
    events: list[Event] = []
    errors: list[str] = []
    if not EVENTS_DIR.exists():
        return events, errors
    for path in sorted(EVENTS_DIR.glob("*.md")):
        try:
            event = load_event(path)
            if event:
                events.append(event)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return events, errors


def atomic_write_text(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return "unchanged"
        if GENERATED_AT_RE.sub('generated-at: "__stable__"', existing) == GENERATED_AT_RE.sub(
            'generated-at: "__stable__"', content
        ):
            return "unchanged"
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_path).replace(path)
        return "updated"
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def detect_duplicate_warnings(events: list[Event]) -> list[str]:
    grouped: dict[tuple[str, str, str], list[Event]] = {}
    for event in events:
        if event.status != "active":
            continue
        key = (
            event.event_date.isoformat(),
            event.event_time or "",
            event.title.casefold(),
        )
        grouped.setdefault(key, []).append(event)

    warnings: list[str] = []
    for (event_date, event_time, _title_key), matches in sorted(grouped.items()):
        if len(matches) < 2:
            continue
        title = matches[0].title
        file_list = ", ".join(match.path.name for match in matches)
        warnings.append(
            f'DUPLICATE: {event_date} {event_time or "(no-time)"} "{title}" appears {len(matches)}x ({file_list})'
        )
    return warnings


def relation_text(delta_days: int, locale: str) -> str:
    if locale == "hu":
        if delta_days == 0:
            return "ma"
        if delta_days == 1:
            return "holnap"
        return f"{delta_days} nap mulva"
    if delta_days == 0:
        return "today"
    if delta_days == 1:
        return "tomorrow"
    return f"in {delta_days} days"


def render_event_line(event: Event, prefix: str = "") -> str:
    parts = []
    if prefix:
        parts.append(prefix)
    if event.event_time:
        parts.append(event.event_time)
    parts.append(event.title)
    if event.kind:
        parts.append(f"({event.kind})")
    return " ".join(parts).strip()


def render_source(event: Event) -> str:
    rel = event.path.relative_to(ROOT).as_posix()
    return f"[[{rel}]]"


def compile_radar(target_date: date, locale: str, horizon_days: int = 7) -> tuple[str, list[str], list[str]]:
    events, errors = load_events()
    warnings = detect_duplicate_warnings(events)
    overdue: list[Event] = []
    today: list[Event] = []
    heads_up: list[tuple[Event, int]] = []
    upcoming: list[tuple[Event, int]] = []

    for event in events:
        if event.status != "active":
            continue
        delta = (event.event_date - target_date).days
        if delta < 0:
            overdue.append(event)
        elif delta == 0:
            today.append(event)
        elif delta in event.remind_days_before:
            heads_up.append((event, delta))
        elif delta <= horizon_days:
            upcoming.append((event, delta))

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "---",
        "type: temporal-radar",
        f'date: "{target_date.isoformat()}"',
        "status: active",
        "maintained-by: temporal-radar",
        f'generated-at: "{generated_at}"',
        f"source-count: {len(events)}",
        "---",
        "",
        f"# Temporal Radar — {target_date.isoformat()}",
        "",
        "Ez egy gepileg forditott temporal surface. A relative date-logikat a compiler szamolja ki, nem a keresesi improvizacio.",
        "",
    ]

    lines.append("## Overdue")
    if overdue:
        for event in overdue:
            lines.append(f"- {render_event_line(event)} — elmult, de meg mindig aktiv")
            lines.append(f"  - Source: {render_source(event)}")
    else:
        lines.append("- Nincs")
    lines.append("")

    lines.append("## Today")
    if today:
        for event in today:
            lines.append(f"- {render_event_line(event)}")
            lines.append(f"  - Source: {render_source(event)}")
    else:
        lines.append("- Nincs mai fix temporal tetel")
    lines.append("")

    lines.append("## Heads-Up")
    if heads_up:
        for event, delta in sorted(heads_up, key=lambda item: (item[1], item[0].event_time or "")):
            relation = relation_text(delta, locale)
            if locale == "hu" and delta == 1:
                message = (
                    f"Bocsika, ez nem mai feladat, de {relation} viszont: "
                    f"{event.event_date.isoformat()} {event.event_time or ''} {event.title}".strip()
                )
            else:
                message = (
                    f"Nem mai feladat, de {relation}: "
                    f"{event.event_date.isoformat()} {event.event_time or ''} {event.title}".strip()
                )
            lines.append(f"- {message}")
            if event.related_note:
                lines.append(f"  - Related note: {event.related_note}")
            lines.append(f"  - Source: {render_source(event)}")
    else:
        lines.append("- Nincs aktiv heads-up reminder")
    lines.append("")

    lines.append(f"## Upcoming ({horizon_days} days)")
    if upcoming:
        for event, delta in sorted(upcoming, key=lambda item: (item[1], item[0].event_time or "")):
            relation = relation_text(delta, locale)
            lines.append(
                f"- {event.event_date.isoformat()} {event.event_time or ''} {event.title} — {relation}".strip()
            )
            lines.append(f"  - Source: {render_source(event)}")
    else:
        lines.append("- Nincs")
    lines.append("")

    lines.append("## Compiler Notes")
    if errors:
        for error in errors:
            lines.append(f"- ERROR: {error}")
    if warnings:
        for warning in warnings:
            lines.append(f"- WARNING: {warning}")
    if not errors and not warnings:
        lines.append("- Nincs schema-hiba")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n", errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="target_date", required=True, help="Target date in YYYY-MM-DD")
    parser.add_argument("--locale", default="hu", choices=["hu", "en"])
    parser.add_argument("--write", action="store_true", help="Write compiled output to Meta/Operational/Temporal-Radar.md")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Override output file path")
    args = parser.parse_args()

    try:
        target_date = date.fromisoformat(args.target_date)
    except ValueError:
        print("Invalid --date. Use YYYY-MM-DD.", file=sys.stderr)
        return 2

    compiled, errors, warnings = compile_radar(target_date, args.locale)
    if args.write:
        output_path = Path(args.output)
        atomic_write_text(output_path, compiled)
    sys.stdout.write(compiled)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
