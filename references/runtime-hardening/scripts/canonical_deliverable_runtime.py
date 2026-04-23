#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

try:
    import today_tasks_runtime
except ModuleNotFoundError:  # pragma: no cover - package import fallback for tests
    from scripts import today_tasks_runtime

ROOT = Path(__file__).resolve().parent.parent
HEADER_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
DATE_FIELD_RE = re.compile(r'(?m)^\s*date:\s*"(?P<value>\d{4}-\d{2}-\d{2})"\s*$')
STATUS_FIELD_RE = re.compile(r'(?m)^\s*status:\s*"(?P<value>[^"]+)"\s*$')
CONFIDENCE_FIELD_RE = re.compile(r'(?m)^\s*focus-confidence:\s*"(?P<value>[^"]+)"\s*$')

SURFACE_PATHS = {
    "today-focus": Path("Meta/Operational/Today-Focus.md"),
    "weekly": Path("Meta/Operational/Weekly-Focus.md"),
    "measurements": Path("Meta/Operational/Measurements-Radar.md"),
    "future-reminders": Path("Meta/Operational/Temporal-Radar.md"),
}


def root_for(root: Path | None = None) -> Path:
    return root.resolve() if root else ROOT


def frontmatter_value(path: Path, pattern: re.Pattern[str]) -> str | None:
    if not path.exists():
        return None
    match = pattern.search(path.read_text(encoding="utf-8"))
    return match.group("value").strip() if match else None


def extract_section_lines(path: Path, section_name: str) -> list[str]:
    if not path.exists():
        return []
    lines: list[str] = []
    active = False
    active_level = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        header = HEADER_RE.match(raw_line.strip())
        if header:
            level = len(header.group("hashes"))
            title = header.group("title").strip()
            if active and level <= active_level:
                break
            if level == 2 and title == section_name:
                active = True
                active_level = level
                continue
        if active:
            lines.append(raw_line.rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def compact_section_text(lines: list[str]) -> str:
    meaningful = [line.strip() for line in lines if line.strip()]
    if not meaningful:
        return ""
    if all(line.startswith("- ") for line in meaningful):
        items = [line[2:].strip() for line in meaningful]
        return "\n".join(items)
    return "\n".join(meaningful)


def extract_top_level_bullets(path: Path, section_name: str) -> list[str]:
    lines = extract_section_lines(path, section_name)
    items: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- ") and not stripped.startswith("- Source:"):
            items.append(stripped[2:].strip())
    return items


def compact_join(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} es {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, es {cleaned[-1]}"


def build_today_tasks_payload(target_date: date, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    payload = today_tasks_runtime.build_payload(target_date, root=real_root)
    status = payload["status"]
    reason = ""
    if not payload["deliverable"]:
        status = "drift"
        reason = "deliverable_missing"
    return {
        "kind": "today",
        "date": target_date.isoformat(),
        "status": status,
        "deliverable": payload["deliverable"] if status != "drift" else "",
        "reason": reason,
        "surface_path": payload["daily_path"],
    }


def build_focus_payload(kind: str, target_date: date, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    surface_path = real_root / SURFACE_PATHS[kind]
    surface_date = frontmatter_value(surface_path, DATE_FIELD_RE)
    confidence = frontmatter_value(surface_path, CONFIDENCE_FIELD_RE)
    deliverable = compact_section_text(extract_section_lines(surface_path, "Deliverable"))
    reason = ""
    status = "ok"

    if not surface_path.exists():
        status = "drift"
        reason = "surface_missing"
    elif surface_date != target_date.isoformat():
        status = "drift"
        reason = "surface_date_mismatch"
    elif not deliverable:
        status = "drift"
        reason = "deliverable_missing"
    elif confidence == "watch":
        status = "watch"
        reason = "confidence_watch"
    elif confidence not in {"high", "medium"}:
        status = "watch"
        reason = "confidence_unknown"

    return {
        "kind": kind,
        "date": target_date.isoformat(),
        "status": status,
        "confidence": confidence,
        "deliverable": deliverable if status != "drift" else "",
        "reason": reason,
        "surface_path": str(surface_path.relative_to(real_root)),
    }


def build_measurements_payload(target_date: date, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    surface_path = real_root / SURFACE_PATHS["measurements"]
    surface_date = frontmatter_value(surface_path, DATE_FIELD_RE)
    surface_status = frontmatter_value(surface_path, STATUS_FIELD_RE)
    prompt_text = compact_section_text(extract_section_lines(surface_path, "Prompt"))
    if prompt_text == "Nincs most user-facing measurements prompt.":
        prompt_text = ""

    reason = ""
    status = surface_status or "drift"

    if not surface_path.exists():
        status = "drift"
        reason = "surface_missing"
    elif surface_date != target_date.isoformat():
        status = "drift"
        reason = "surface_date_mismatch"
    elif surface_status == "prompt" and not prompt_text:
        status = "drift"
        reason = "deliverable_missing"
    elif surface_status in {"suppressed", "ok"} and prompt_text:
        status = "drift"
        reason = "unexpected_prompt_when_not_prompting"
    elif surface_status is None:
        status = "drift"
        reason = "status_missing"

    return {
        "kind": "measurements",
        "date": target_date.isoformat(),
        "status": status,
        "deliverable": prompt_text if status == "prompt" else "",
        "reason": reason,
        "surface_path": str(surface_path.relative_to(real_root)),
    }


def build_future_reminders_payload(target_date: date, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    surface_path = real_root / SURFACE_PATHS["future-reminders"]
    surface_date = frontmatter_value(surface_path, DATE_FIELD_RE)
    status = "suppressed"
    reason = ""
    deliverable = ""

    if not surface_path.exists():
        status = "drift"
        reason = "surface_missing"
    elif surface_date != target_date.isoformat():
        status = "drift"
        reason = "surface_date_mismatch"
    else:
        heads_up = [item for item in extract_top_level_bullets(surface_path, "Heads-Up") if not item.casefold().startswith("nincs")]
        upcoming = [item for item in extract_top_level_bullets(surface_path, "Upcoming (7 days)") if not item.casefold().startswith("nincs")]
        parts: list[str] = []
        if heads_up:
            parts.append(f"Kozelgo emlekeztetok: {compact_join(heads_up)}.")
        if upcoming:
            parts.append(f"Utana ez jon: {compact_join(upcoming)}.")
        if heads_up:
            status = "ok"
            deliverable = " ".join(parts)
        elif upcoming:
            status = "watch"
            deliverable = " ".join(parts)

    return {
        "kind": "future-reminders",
        "date": target_date.isoformat(),
        "status": status,
        "deliverable": deliverable,
        "reason": reason,
        "surface_path": str(surface_path.relative_to(real_root)),
    }


def build_payload(kind: str, target_date: date, root: Path | None = None) -> dict[str, Any]:
    if kind == "today":
        return build_today_tasks_payload(target_date, root=root)
    if kind == "today-focus":
        return build_focus_payload(kind, target_date, root=root)
    if kind == "measurements":
        return build_measurements_payload(target_date, root=root)
    if kind == "future-reminders":
        return build_future_reminders_payload(target_date, root=root)
    return build_focus_payload(kind, target_date, root=root)


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Kind: {payload['kind']}",
        f"Date: {payload['date']}",
        f"Status: {payload['status']}",
        f"Surface: {payload['surface_path']}",
    ]
    if payload.get("confidence"):
        lines.append(f"Confidence: {payload['confidence']}")
    if payload.get("reason"):
        lines.append(f"Reason: {payload['reason']}")
    if payload.get("deliverable"):
        lines.extend(["Deliverable:", payload["deliverable"]])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Read the canonical user-facing deliverable for a runtime surface.")
    serve.add_argument("--kind", choices=("today", "today-focus", "weekly", "measurements", "future-reminders"), required=True)
    serve.add_argument("--date", required=True)
    serve.add_argument("--format", choices=("deliverable", "text", "json"), default="deliverable")
    serve.add_argument("--root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = date.fromisoformat(args.date)
    payload = build_payload(args.kind, target_date, root=args.root)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "text":
        print(render_text(payload))
    else:
        print(payload["deliverable"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
