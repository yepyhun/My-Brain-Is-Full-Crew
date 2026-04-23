#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import measurements_radar
import temporal_radar
from backlog_hygiene_audit import build_report as build_backlog_hygiene_report, render_surface as render_backlog_hygiene_surface
from canonical_deliverable_runtime import build_payload as build_deliverable_payload
from coherence_compiler import build_focus_package, write_surfaces as write_focus_surfaces
from daily_measurements_guard import evaluate_measurements
from future_reminder_guard import build_report as build_future_reminder_report
from hook_runtime_state import consume_prompt_classification
from inbox_lossy_merge_guard import validate_report as validate_inbox_report
from obligation_continuity_guard import current_state_report
from operational_drift_guard import (
    COMPILE_STATUS,
    SECTION_NAMES,
    collect_newer_sources,
    extract_section_bullets,
    flatten_non_empty_sections,
    parse_last_full_compile,
    weekly_review_path,
)
from runtime_hygiene_audit import build_report as build_hygiene_report
from source_retention_hygiene_audit import build_report as build_source_retention_hygiene_report
from temporal_hygiene_audit import build_report as build_temporal_hygiene_report

ROOT = Path(__file__).resolve().parent.parent
RECEIPT_PATH = ROOT / "Meta" / "states" / "post-turn-orchestrator.md"
HEALTH_REPORTS_DIR = ROOT / "Meta" / "health-reports"
LOCAL_TZ = ZoneInfo("Europe/Budapest")
STATUS_PRIORITY = {
    "error": 5,
    "drift": 4,
    "loss_detected": 4,
    "stale": 3,
    "watch": 2,
    "medium": 1,
    "prompt": 0,
    "suppressed": 0,
    "ok": 0,
    "missing": 0,
    "no-report": 0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", choices=("session-start", "stop", "manual"), default="manual")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--turn-id")
    parser.add_argument("--touch", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def baseline_touches(event: str) -> set[str]:
    if event == "session-start":
        return {"daily", "measurements", "operational", "temporal"}
    if event == "stop":
        return {"daily", "measurements", "operational"}
    return set()


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, content: str) -> str:
    existing = read_text(path)
    if existing == content:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "updated"


def operational_drift_report(target_date: date) -> dict[str, object]:
    last_full_compile = parse_last_full_compile(COMPILE_STATUS)
    review_path = weekly_review_path(target_date)
    review_sections = extract_section_bullets(review_path, SECTION_NAMES)
    actionable_signals = flatten_non_empty_sections(review_sections)
    newer_sources = collect_newer_sources(last_full_compile, target_date)
    stale = last_full_compile is None or last_full_compile < target_date
    has_newer_review_signal = review_path.exists() and bool(actionable_signals)
    status = "stale" if stale and (has_newer_review_signal or bool(newer_sources)) else "ok"
    return {
        "date": target_date.isoformat(),
        "compile_status_path": str(COMPILE_STATUS.relative_to(ROOT)),
        "last_full_compile": last_full_compile.isoformat() if last_full_compile else "",
        "stale": stale,
        "same_day_weekly_review_path": str(review_path.relative_to(ROOT)) if review_path.exists() else "",
        "weekly_review_sections": review_sections,
        "actionable_signals": actionable_signals,
        "newer_source_notes": newer_sources,
        "status": status,
        "reason": "compiled operational layer predates newer source notes" if status == "stale" else "",
    }


def inbox_digest_path(target_date: date) -> Path:
    matches = sorted(HEALTH_REPORTS_DIR.glob(f"{target_date.isoformat()}*Inbox Triage Digest.md"))
    if matches:
        return matches[-1]
    return HEALTH_REPORTS_DIR / f"{target_date.isoformat()} — Inbox Triage Digest.md"


def summarize_action(name: str, status: str, details: dict[str, object]) -> dict[str, object]:
    payload = {"name": name, "status": status}
    payload.update(details)
    return payload


def overall_status(actions: list[dict[str, object]]) -> str:
    winner = "ok"
    best = 0
    for action in actions:
        status = str(action.get("status", "ok"))
        score = STATUS_PRIORITY.get(status, 0)
        if score > best:
            winner = status
            best = score
    return winner if best > 0 else "ok"


def render_receipt(payload: dict[str, object]) -> str:
    lines = [
        "# Post-Turn Orchestrator",
        "",
        f"- Ran at: `{payload['ran_at']}`",
        f"- Event: `{payload['event']}`",
        f"- Date: `{payload['date']}`",
        f"- Overall status: `{payload['status']}`",
        f"- Touches: `{', '.join(payload['touches']) if payload['touches'] else 'none'}`",
    ]

    classification = payload.get("prompt_classification") or {}
    if classification:
        touches = classification.get("touches", [])
        signals = classification.get("signals", {})
        lines.extend(
            [
                "",
                "## Prompt Classification",
                f"- Touches: `{', '.join(touches) if touches else 'none'}`",
                f"- Signals: `{json.dumps(signals, ensure_ascii=False, sort_keys=True)}`",
            ]
        )

    lines.extend(["", "## Actions"])
    for action in payload.get("actions", []):
        name = action.get("name", "unknown")
        status = action.get("status", "ok")
        lines.append(f"- `{name}` -> `{status}`")
        for key in ("write_result", "reason", "report_path", "surface_path"):
            value = action.get(key)
            if value:
                lines.append(f"  - {key}: `{value}`")
        if action.get("warning_count"):
            lines.append(f"  - warning_count: `{action['warning_count']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    target_date = args.date or today_local()
    touches = baseline_touches(args.event)
    touches.update(args.touch)

    prompt_record: dict[str, Any] | None = None
    if args.turn_id:
        prompt_record = consume_prompt_classification(args.turn_id)
        classification = prompt_record.get("classification", {}) if prompt_record else {}
        touches.update(classification.get("touches", []))
    else:
        classification = {}

    actions: list[dict[str, object]] = []

    if {"daily", "measurements"} & touches:
        measurement_payload = evaluate_measurements(target_date, now_local(), stateless=False)
        measurement_surface = measurements_radar.render_surface(measurement_payload)
        write_result = write_if_changed(measurements_radar.SURFACE_PATH, measurement_surface)
        actions.append(
            summarize_action(
                "measurements_radar",
                str(measurement_payload.get("status", "ok")),
                {
                    "write_result": write_result,
                    "surface_path": str(measurements_radar.SURFACE_PATH.relative_to(ROOT)),
                },
            )
        )

    if {"daily", "operational"} & touches:
        continuity_payload = current_state_report(target_date)
        actions.append(
            summarize_action(
                "current_state_continuity",
                str(continuity_payload.get("status", "ok")),
                {"reason": str(continuity_payload.get("reason", ""))},
            )
        )

        drift_payload = operational_drift_report(target_date)
        actions.append(
            summarize_action(
                "operational_drift",
                str(drift_payload.get("status", "ok")),
                {"reason": str(drift_payload.get("reason", ""))},
            )
        )

        focus_package = build_focus_package(target_date)
        focus_writes = write_focus_surfaces(focus_package)
        focus_status = "watch"
        if focus_package["today"]["confidence"] == "high" and focus_package["weekly"]["confidence"] in {"high", "medium"}:
            focus_status = "ok"
        elif focus_package["today"]["confidence"] == "medium" or focus_package["weekly"]["confidence"] == "medium":
            focus_status = "medium"
        actions.append(
            summarize_action(
                "coherence_focus_refresh",
                focus_status,
                {
                    "write_result": json.dumps(focus_writes, ensure_ascii=False, sort_keys=True),
                    "surface_path": "Meta/Operational/Today-Focus.md + Meta/Operational/Weekly-Focus.md",
                },
            )
        )

        hygiene_payload = build_hygiene_report(target_date)
        actions.append(
            summarize_action(
                "runtime_hygiene_audit",
                str(hygiene_payload.get("status", "ok")),
                {
                    "reason": "critical loop coverage gap" if hygiene_payload.get("critical_loop_coverage_gaps") else "",
                },
            )
        )

        source_retention_payload = build_source_retention_hygiene_report()
        actions.append(
            summarize_action(
                "source_retention_hygiene_audit",
                str(source_retention_payload.get("status", "ok")),
                {
                    "reason": "orphan processed inbox file" if source_retention_payload.get("orphan_processed_inbox_files") else "",
                },
            )
        )

        backlog_payload = build_backlog_hygiene_report(target_date)
        backlog_surface = render_backlog_hygiene_surface(backlog_payload)
        backlog_surface_path = ROOT / "Meta" / "Operational" / "Backlog-Hygiene.md"
        backlog_write = write_if_changed(backlog_surface_path, backlog_surface)
        actions.append(
            summarize_action(
                "backlog_hygiene_refresh",
                "ok",
                {
                    "finding_status": str(backlog_payload.get("status", "ok")),
                    "review_now_count": len(backlog_payload.get("review_now", [])),
                    "aging_count": len(backlog_payload.get("aging", [])),
                    "surface_path": str(backlog_surface_path.relative_to(ROOT)),
                    "write_result": backlog_write,
                    "reason": "weekly-style background backlog review available" if backlog_payload.get("review_now") else "",
                },
            )
        )

    if "temporal" in touches:
        future_payload = build_future_reminder_report(target_date)
        actions.append(
            summarize_action(
                "future_reminder_guard",
                str(future_payload.get("status", "ok")),
                {"reason": str(future_payload.get("reason", ""))},
            )
        )

        future_deliverable_payload = build_deliverable_payload("future-reminders", target_date)
        actions.append(
            summarize_action(
                "future_reminder_deliverable",
                str(future_deliverable_payload.get("status", "ok")),
                {
                    "surface_path": str(future_deliverable_payload.get("surface_path", "")),
                    "reason": str(future_deliverable_payload.get("reason", "")),
                },
            )
        )

        compiled, warnings, errors = temporal_radar.compile_radar(target_date, "hu")
        write_result = "skipped"
        if not errors:
            write_result = temporal_radar.atomic_write_text(temporal_radar.DEFAULT_OUTPUT, compiled)
        actions.append(
            summarize_action(
                "temporal_radar_refresh",
                "error" if errors else ("watch" if warnings else "ok"),
                {
                    "warning_count": len(warnings),
                    "reason": errors[0] if errors else "",
                    "surface_path": str(temporal_radar.DEFAULT_OUTPUT.relative_to(ROOT)),
                    "write_result": write_result,
                },
            )
        )

        temporal_hygiene_payload = build_temporal_hygiene_report(target_date)
        actions.append(
            summarize_action(
                "temporal_hygiene_audit",
                str(temporal_hygiene_payload.get("status", "ok")),
                {
                    "reason": "stale active temporal event" if temporal_hygiene_payload.get("stale_events") else "",
                },
            )
        )

    if "inbox" in touches:
        report_path = inbox_digest_path(target_date)
        inbox_payload = validate_inbox_report(report_path)
        actions.append(
            summarize_action(
                "inbox_lossy_merge_validate",
                str(inbox_payload.get("status", "ok")),
                {
                    "report_path": str(report_path.relative_to(ROOT)) if report_path.exists() else str(report_path.relative_to(ROOT)),
                    "reason": str(inbox_payload.get("reason", "")),
                },
            )
        )

    payload = {
        "event": args.event,
        "date": target_date.isoformat(),
        "turn_id": args.turn_id or "",
        "touches": sorted(touches),
        "prompt_classification": classification,
        "status": overall_status(actions),
        "actions": actions,
        "ran_at": now_local().isoformat(timespec="seconds"),
    }

    receipt = render_receipt(payload)
    write_if_changed(RECEIPT_PATH, receipt)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
