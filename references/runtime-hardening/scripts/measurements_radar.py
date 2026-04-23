#!/usr/bin/env python3
"""Compile the current day's measurements prompt state into an operational surface."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from daily_measurements_guard import evaluate_measurements, resolve_now


ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "Meta" / "Operational" / "Measurements-Radar.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--now",
        help="Override current local datetime, ISO format, e.g. 2026-04-22T22:20",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "deliverable"),
        default="json",
        help="Output JSON, compiled markdown, or the exact user-facing deliverable only.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the compiled markdown surface to Meta/Operational/Measurements-Radar.md.",
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        help="Do not read or update prompt cooldown state; useful for diagnostics.",
    )
    return parser.parse_args()


def status_summary(payload: dict[str, object]) -> str:
    status = str(payload.get("status", ""))
    if status == "prompt":
        return "Promptolni kell: a compact measurements kerdes most user-facing surfaced lehet."
    if status == "suppressed":
        until = str(payload.get("cooldown_until", ""))
        if until:
            return f"Most nem kell ujrapromptolni: aktiv cooldown van {until}-ig."
        return "Most nem kell ujrapromptolni: a jelenlegi hianyhalmaz mar meg lett kerdezve."
    return "A mai measurements elegsegesen ki van toltve; nincs user-facing prompt."


def render_surface(payload: dict[str, object]) -> str:
    date_value = str(payload["date"])
    status = str(payload["status"])
    note_path = str(payload["daily_note_path"])
    values = payload.get("values", {})
    if not isinstance(values, dict):
        values = {}
    required_now = payload.get("required_now", [])
    if not isinstance(required_now, list):
        required_now = []
    missing_fields = payload.get("missing_fields", [])
    if not isinstance(missing_fields, list):
        missing_fields = []

    lines = [
        "---",
        "type: measurements-radar",
        f'date: "{date_value}"',
        "maintained-by: measurements-radar",
        f'status: "{status}"',
        "---",
        "",
        f"# Measurements Radar - {date_value}",
        "",
        "## Status",
        "",
        f"- {status_summary(payload)}",
    ]

    suppression_reason = str(payload.get("suppression_reason", "")).strip()
    cooldown_until = str(payload.get("cooldown_until", "")).strip()
    if suppression_reason:
        lines.append(f"- Suppression reason: `{suppression_reason}`")
    if cooldown_until:
        lines.append(f"- Cooldown until: `{cooldown_until}`")

    lines.extend(["", "## Required Now", ""])
    if required_now:
        lines.extend([f"- {item}" for item in required_now if isinstance(item, str)])
    else:
        lines.append("- Nincs immediate measurements top-up igeny.")

    lines.extend(["", "## Prompt", ""])
    prompt = str(payload.get("prompt", "")).strip()
    if status == "prompt" and prompt:
        lines.append(prompt)
    else:
        lines.append("Nincs most user-facing measurements prompt.")

    lines.extend(["", "## Current Values", ""])
    value_labels = {
        "wake_time": "Felkelesi ido",
        "bed_time": "Mai esti lefekves (kb)",
        "late_reason": "Kesoi lefekves oka (ha ejfel utan)",
        "rhythm_note": "Alvas ritmusa megfigyeles",
    }
    for key in ("wake_time", "bed_time", "late_reason", "rhythm_note"):
        label = value_labels[key]
        value = str(values.get(key, "")).strip()
        lines.append(f"- {label}: {value if value else '---'}")

    lines.extend(["", "## Missing Fields", ""])
    if missing_fields:
        lines.extend([f"- {item}" for item in missing_fields if isinstance(item, str)])
    else:
        lines.append("- Nincs hianyzo mezo.")

    lines.extend(["", "## Source Refs", "", f"- Daily note: [[{note_path}]]"])
    return "\n".join(lines) + "\n"


def write_surface(content: str) -> None:
    SURFACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SURFACE_PATH.write_text(content, encoding="utf-8")


def main() -> int:
    args = parse_args()
    now_dt = resolve_now(args.now)
    payload = evaluate_measurements(args.date, now_dt, stateless=args.stateless)
    surface = render_surface(payload)
    if args.write:
        write_surface(surface)

    if args.format == "markdown":
        print(surface, end="")
        return 0
    if args.format == "deliverable":
        if payload.get("status") == "prompt":
            print(str(payload.get("prompt", "")).strip())
        return 0

    output = dict(payload)
    output["surface_path"] = str(SURFACE_PATH.relative_to(ROOT))
    output["deliverable"] = str(payload.get("prompt", "")).strip() if payload.get("status") == "prompt" else ""
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
