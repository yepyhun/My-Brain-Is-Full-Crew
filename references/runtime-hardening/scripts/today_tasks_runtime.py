#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Any
from unittest import mock

import daily_rollover
import obligation_continuity_guard

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "07-Daily"
TEMPORAL_RADAR = ROOT / "Meta" / "Operational" / "Temporal-Radar.md"

FIXED_SECTION_TITLES = {"fix kotottsegek", "fixed commitments"}
TASK_SECTION_TITLES = {"tasks"}
WATCH_SECTION_TITLES = {"needs review"}


def root_for(root: Path | None = None) -> Path:
    return root.resolve() if root else ROOT


def daily_path(target_date: date, root: Path | None = None) -> Path:
    return root_for(root) / "07-Daily" / f"{target_date.isoformat()}.md"


def normalize_text(text: str) -> str:
    return obligation_continuity_guard.normalize_text(text)


def dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item.strip())
    return result


def is_similar_text(left: str, right: str) -> bool:
    score, shared = obligation_continuity_guard.similarity(left, right)
    return (score >= 0.66 and shared >= 2) or (score >= 0.5 and shared >= 3)


def dedupe_similar_preserve(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if not item.strip():
            continue
        if any(is_similar_text(item, existing) for existing in result):
            continue
        result.append(item.strip())
    return result


def choose_more_specific_text(left: str, right: str) -> str:
    left_tokens = len(obligation_continuity_guard.meaningful_tokens(left))
    right_tokens = len(obligation_continuity_guard.meaningful_tokens(right))
    if right_tokens > left_tokens:
        return right.strip()
    if right_tokens < left_tokens:
        return left.strip()
    if len(right.strip()) > len(left.strip()):
        return right.strip()
    return left.strip()


def dedupe_near_duplicate_tasks(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        candidate = item.strip()
        if not candidate:
            continue
        merged = False
        for index, existing in enumerate(result):
            score, shared = obligation_continuity_guard.similarity(candidate, existing)
            if score >= 0.84 and shared >= 6:
                result[index] = choose_more_specific_text(existing, candidate)
                merged = True
                break
        if not merged:
            result.append(candidate)
    return dedupe_preserve(result)


def format_task_body(body: str) -> str:
    text = daily_rollover.TAG_RE.sub("", body)
    text = daily_rollover.review_display_body(text).strip()
    return obligation_continuity_guard.unwrap_wikilinks(text)


def collect_daily_groups(target_date: date, root: Path | None = None) -> tuple[list[str], list[str], list[str]]:
    path = daily_path(target_date, root)
    if not path.exists():
        return [], [], []

    fixed: list[str] = []
    tasks: list[str] = []
    watch: list[str] = []
    current_section = ""
    in_comment = False

    for line in path.read_text(encoding="utf-8").splitlines():
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue

        header_match = daily_rollover.HEADER_RE.match(line)
        if header_match:
            current_section = daily_rollover.normalize_section(header_match.group("title"))
            continue

        task_match = daily_rollover.TASK_RE.match(line)
        if not task_match or task_match.group("mark").lower() == "x":
            continue

        body = task_match.group("body").strip()
        clean = format_task_body(body)
        _roll_mode, due_date, explicit_event = daily_rollover.parse_task_tags(body)
        is_fixed = (
            current_section in FIXED_SECTION_TITLES
            or explicit_event
            or daily_rollover.looks_one_time(clean, due_date, explicit_event)
        )

        if current_section in WATCH_SECTION_TITLES:
            watch.append(clean)
        elif is_fixed:
            fixed.append(clean)
        elif current_section in TASK_SECTION_TITLES or not current_section:
            tasks.append(clean)
        else:
            tasks.append(clean)

    return dedupe_preserve(fixed), dedupe_preserve(tasks), dedupe_preserve(watch)


def collect_temporal_today(target_date: date, root: Path | None = None) -> list[str]:
    radar_path = root_for(root) / "Meta" / "Operational" / "Temporal-Radar.md"
    if not radar_path.exists():
        return []
    today_items: list[str] = []
    section = ""
    for line in radar_path.read_text(encoding="utf-8").splitlines():
        heading_match = obligation_continuity_guard.HEADING_RE.match(line)
        if heading_match:
            section = daily_rollover.normalize_section(heading_match.group("title"))
            continue
        bullet_match = obligation_continuity_guard.LIST_RE.match(line.strip())
        if not bullet_match or section != "today":
            continue
        body = obligation_continuity_guard.unwrap_wikilinks(bullet_match.group("body").strip())
        if body.startswith("Source:") or daily_rollover.normalize_section(body) == "nincs":
            continue
        today_items.append(body)
    return dedupe_preserve(today_items)


def _patch_dependency_roots(root: Path):
    return [
        mock.patch.object(obligation_continuity_guard, "ROOT", root),
        mock.patch.object(obligation_continuity_guard.temporal_radar, "ROOT", root),
        mock.patch.object(obligation_continuity_guard.temporal_radar, "EVENTS_DIR", root / "Meta" / "Temporal" / "Events"),
    ]


def compact_high_signal_items(items: list[dict[str, object]]) -> list[str]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for item in items:
        source_path = str(item.get("source_path", ""))
        section = str(item.get("section", ""))
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        grouped.setdefault((source_path, section), []).append(text)

    compacted: list[str] = []
    for (_source_path, section), values in grouped.items():
        unique = dedupe_preserve(values)
        if not unique:
            continue
        normalized_values = {normalize_text(value) for value in unique}
        title = section.strip()
        normalized_title = normalize_text(title)
        use_section_title = bool(title) and normalized_title not in normalized_values

        if len(unique) == 1:
            if use_section_title:
                compacted.append(f"{title}: {unique[0]}")
            else:
                compacted.append(unique[0])
            continue

        if len(unique) == 2:
            detail_text = f"{unique[0]}, es {unique[1]}"
        else:
            detail_text = "; ".join(unique)

        if use_section_title:
            compacted.append(f"{title}: {detail_text}")
        else:
            compacted.append(detail_text)
    return dedupe_preserve(compacted)


def surface_items_for_matching(fixed_commitments: list[str], tasks: list[str], target_date: date, root: Path | None = None) -> list[obligation_continuity_guard.SurfaceItem]:
    items: list[obligation_continuity_guard.SurfaceItem] = []
    daily_rel = str(daily_path(target_date, root).relative_to(root_for(root)))
    radar_rel = str((root_for(root) / "Meta" / "Operational" / "Temporal-Radar.md").relative_to(root_for(root)))
    for text in fixed_commitments:
        items.append(
            obligation_continuity_guard.SurfaceItem(
                text=text,
                source_kind="temporal-radar",
                source_path=radar_rel,
                section="today",
            )
        )
    for text in tasks:
        items.append(
            obligation_continuity_guard.SurfaceItem(
                text=text,
                source_kind="daily",
                source_path=daily_rel,
                section="Tasks",
            )
        )
    return items


def collect_unsurfaced_high_signal(target_date: date, fixed_commitments: list[str], tasks: list[str], root: Path | None = None) -> list[str]:
    resolved_root = root_for(root)
    open_loops_path = resolved_root / "Meta" / "Operational" / "Open-Loops.md"
    surfaced = surface_items_for_matching(fixed_commitments, tasks, target_date, root)

    if root is None:
        candidates = obligation_continuity_guard.collect_open_loop_obligations(open_loops_path)
        candidates = [item for item in candidates if item.severity == "high"]
        unsurfaced = [
            item for item in candidates
            if not obligation_continuity_guard.temporal_surface_covered(item, target_date)
            and not obligation_continuity_guard.best_surface_match(item, surfaced)
        ]
    else:
        with ExitStack() as stack:
            for patcher in _patch_dependency_roots(resolved_root):
                stack.enter_context(patcher)
            candidates = obligation_continuity_guard.collect_open_loop_obligations(open_loops_path)
            candidates = [item for item in candidates if item.severity == "high"]
            unsurfaced = [
                item for item in candidates
                if not obligation_continuity_guard.temporal_surface_covered(item, target_date)
                and not obligation_continuity_guard.best_surface_match(item, surfaced)
            ]

    return compact_high_signal_items(
        [
            {
                "text": item.text,
                "source_path": item.source_path,
                "section": item.section,
            }
            for item in unsurfaced
        ]
    )


def build_payload(target_date: date, root: Path | None = None) -> dict[str, Any]:
    fixed_from_daily, tasks, watch_items = collect_daily_groups(target_date, root)
    tasks = dedupe_near_duplicate_tasks(tasks)
    fixed_from_temporal = collect_temporal_today(target_date, root)

    fixed_commitments = dedupe_similar_preserve(fixed_from_daily + fixed_from_temporal)
    unsurfaced_high_signal = [
        item
        for item in collect_unsurfaced_high_signal(target_date, fixed_commitments, tasks, root)
        if normalize_text(item) not in {normalize_text(task) for task in tasks}
    ]

    status = "ok"
    if unsurfaced_high_signal:
        status = "watch"

    lines: list[str] = []
    if fixed_commitments:
        lines.append("Fix kötöttségek:")
        lines.extend(f"- {item}" for item in fixed_commitments)
    if tasks:
        if lines:
            lines.append("")
        lines.append("Mai teendők:")
        lines.extend(f"- {item}" for item in tasks)
    if unsurfaced_high_signal:
        if lines:
            lines.append("")
        lines.append("Még surfacedelendő fontos szálak:")
        lines.extend(f"- {item}" for item in unsurfaced_high_signal)
    if watch_items:
        if lines:
            lines.append("")
        lines.append("Figyelendő:")
        lines.extend(f"- {item}" for item in watch_items)

    return {
        "date": target_date.isoformat(),
        "status": status,
        "fixed_commitments": fixed_commitments,
        "today_tasks": tasks,
        "unsurfaced_high_signal": unsurfaced_high_signal,
        "watch_items": watch_items,
        "deliverable": "\n".join(lines).strip(),
        "daily_path": str(daily_path(target_date, root).relative_to(root_for(root))),
        "temporal_radar_path": str((root_for(root) / "Meta" / "Operational" / "Temporal-Radar.md").relative_to(root_for(root))),
    }


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"# Today Tasks Runtime - {payload['date']}",
        "",
        f"- Status: `{payload['status']}`",
    ]

    if payload["fixed_commitments"]:
        lines.extend(["", "## Fixed Commitments"])
        lines.extend(f"- {item}" for item in payload["fixed_commitments"])
    if payload["today_tasks"]:
        lines.extend(["", "## Today Tasks"])
        lines.extend(f"- {item}" for item in payload["today_tasks"])
    if payload["unsurfaced_high_signal"]:
        lines.extend(["", "## Unsurfaced High Signal"])
        lines.extend(f"- {item}" for item in payload["unsurfaced_high_signal"])
    if payload["watch_items"]:
        lines.extend(["", "## Watch Items"])
        lines.extend(f"- {item}" for item in payload["watch_items"])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Read the grounded daily task runtime output.")
    serve.add_argument("--date", required=True)
    serve.add_argument("--format", choices=("deliverable", "text", "json"), default="deliverable")
    serve.add_argument("--root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = date.fromisoformat(args.date)
    payload = build_payload(target_date, root=args.root)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "text":
        print(render_text(payload))
    else:
        print(payload["deliverable"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
