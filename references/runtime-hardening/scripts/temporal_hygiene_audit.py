#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    import temporal_radar
except ModuleNotFoundError:  # pragma: no cover
    from scripts import temporal_radar

ROOT = Path(__file__).resolve().parent.parent
EVENTS_DIR = ROOT / "Meta" / "Temporal" / "Events"
OPEN_LOOPS_PATH = ROOT / "Meta" / "Operational" / "Open-Loops.md"
FOLLOWUP_KEYWORDS = ("ujra", "nem ment at", "nem ment át", "kapcsolatfelvetel", "tovabblepni")


@dataclass
class StaleSuggestion:
    path: Path
    title: str
    event_date: str
    suggested_status: str
    reason: str
    confidence: str


def root_for(root: Path | None = None) -> Path:
    return root.resolve() if root else ROOT


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(char for char in folded if not unicodedata.combining(char))
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def tokens(text: str) -> set[str]:
    return {token for token in normalize(text).split() if len(token) >= 4}


def token_overlap(left: set[str], right: set[str]) -> int:
    return len(left & right)


def load_events(root: Path) -> list[temporal_radar.Event]:
    events: list[temporal_radar.Event] = []
    events_dir = root / "Meta" / "Temporal" / "Events"
    if not events_dir.exists():
        return events
    for path in sorted(events_dir.glob("*.md")):
        event = temporal_radar.load_event(path)
        if event:
            events.append(event)
    return events


def related_tokens(event: temporal_radar.Event) -> set[str]:
    base = tokens(event.title)
    if event.related_note:
        base |= tokens(Path(event.related_note.replace("[[", "").replace("]]", "").split("|")[0]).stem)
    return base


def has_followup_open_loop(event: temporal_radar.Event, open_loops_text: str) -> bool:
    normalized_open_loops = normalize(open_loops_text)
    if not any(keyword in normalized_open_loops for keyword in FOLLOWUP_KEYWORDS):
        return False
    return token_overlap(related_tokens(event), tokens(open_loops_text)) >= 2


def superseded_by_later_event(event: temporal_radar.Event, events: list[temporal_radar.Event]) -> bool:
    event_tokens = related_tokens(event)
    for other in events:
        if other.path == event.path or other.event_date <= event.event_date:
            continue
        if other.kind != event.kind:
            continue
        if token_overlap(event_tokens, related_tokens(other)) >= 1:
            return True
    return False


def build_report(target_date: date, grace_days: int = 7, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    events = load_events(real_root)
    open_loops_text = (real_root / "Meta" / "Operational" / "Open-Loops.md").read_text(encoding="utf-8") if (real_root / "Meta" / "Operational" / "Open-Loops.md").exists() else ""
    cutoff = target_date - timedelta(days=grace_days)
    stale_events: list[dict[str, Any]] = []
    for event in events:
        if event.status != "active" or event.event_date > cutoff:
            continue
        suggestion = "review"
        reason = "stale_active_temporal_event"
        confidence = "watch"
        if has_followup_open_loop(event, open_loops_text):
            suggestion = "cancelled"
            reason = "superseded_by_followup_open_loop"
            confidence = "high"
        elif superseded_by_later_event(event, events):
            suggestion = "cancelled"
            reason = "superseded_by_later_temporal_event"
            confidence = "medium"
        stale_events.append(
            {
                "path": str(event.path.relative_to(real_root)),
                "title": event.title,
                "event_date": event.event_date.isoformat(),
                "kind": event.kind or "",
                "suggested_status": suggestion,
                "reason": reason,
                "confidence": confidence,
            }
        )

    return {
        "date": target_date.isoformat(),
        "status": "drift" if stale_events else "ok",
        "grace_days": grace_days,
        "stale_events": stale_events,
    }


STATUS_RE = re.compile(r'(?m)^status:\s*\"?[^\n\"]+\"?\s*$')


def apply_status(path: Path, status: str) -> None:
    text = path.read_text(encoding="utf-8")
    if STATUS_RE.search(text):
        text = STATUS_RE.sub(f'status: "{status}"', text, count=1)
    else:
        text = text.replace("---\n", f'---\nstatus: "{status}"\n', 1)
    path.write_text(text, encoding="utf-8")


def apply_suggested(target_date: date, grace_days: int = 7, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    payload = build_report(target_date, grace_days=grace_days, root=real_root)
    changed: list[str] = []
    for item in payload["stale_events"]:
        if item["suggested_status"] == "cancelled" and item["confidence"] == "high":
            path = real_root / item["path"]
            apply_status(path, "cancelled")
            changed.append(item["path"])
    return {
        "date": target_date.isoformat(),
        "changed": changed,
        "changed_count": len(changed),
    }


def render_text(payload: dict[str, Any]) -> str:
    lines = [f"Date: {payload['date']}", f"Status: {payload['status']}"]
    for item in payload.get("stale_events", []):
        lines.append(f"- {item['confidence']} :: {item['suggested_status']} :: {item['path']} :: {item['reason']}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--date", required=True)
    audit.add_argument("--grace-days", type=int, default=7)
    audit.add_argument("--json", action="store_true")
    audit.add_argument("--root", type=Path)

    apply_parser = subparsers.add_parser("apply-suggested")
    apply_parser.add_argument("--date", required=True)
    apply_parser.add_argument("--grace-days", type=int, default=7)
    apply_parser.add_argument("--json", action="store_true")
    apply_parser.add_argument("--root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = date.fromisoformat(args.date)
    if args.command == "apply-suggested":
        payload = apply_suggested(target_date, grace_days=args.grace_days, root=args.root)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    payload = build_report(target_date, grace_days=args.grace_days, root=args.root)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
