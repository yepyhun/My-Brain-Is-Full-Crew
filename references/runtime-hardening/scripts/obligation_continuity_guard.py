#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import daily_rollover
import temporal_radar
from operational_drift_guard import (
    COMPILE_STATUS,
    GENERIC_BULLETS,
    collect_newer_sources,
    parse_last_full_compile,
    weekly_review_path,
)


ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "07-Daily"
TEMPORAL_RADAR = ROOT / "Meta" / "Operational" / "Temporal-Radar.md"
OPEN_LOOPS = ROOT / "Meta" / "Operational" / "Open-Loops.md"
CURRENT_STATE = ROOT / "Meta" / "Operational" / "Current-State.md"
TODAY_FOCUS = ROOT / "Meta" / "Operational" / "Today-Focus.md"
WEEKLY_FOCUS = ROOT / "Meta" / "Operational" / "Weekly-Focus.md"

HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
LIST_RE = re.compile(r"^(?:-\s+|\d+\.\s+)(?P<body>.+\S)\s*$")
NEXT_STEP_RE = re.compile(r"^-+\s*Next step:\s*(?P<body>.+\S)\s*$")
WIKILINK_RE = re.compile(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]")
DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")

RADAR_SURFACE_SECTIONS = {"overdue", "today", "heads-up"}
ACTION_SECTION_KEYWORDS = (
    "what stayed open",
    "preparation needed",
    "kovetkezo konkret lepesek",
    "jelenlegi legfontosabb nyitott feladatok",
    "konkret hataridok es figyelendo idoszakok",
    "napi minimum ehhez a szalhoz",
    "heti minimum ehhez a szalhoz",
    "laura-related next steps",
    "legal aid",
    "immediate next step",
)
CURRENT_STATE_ACTION_SECTIONS = {"mostani fokusz"}
FOCUS_BULLET_SECTIONS = {"fixed commitments", "deliverable"}
FOCUS_HEADING_SECTIONS = {"strategic focus", "this week focus"}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
NON_OBLIGATION_PREFIXES = ("jelenlegi kontakt", "kontakt:")
STOPWORDS = {
    "a",
    "az",
    "egy",
    "es",
    "is",
    "de",
    "ha",
    "hogy",
    "mert",
    "mar",
    "ma",
    "mai",
    "holnap",
    "kell",
    "csak",
    "most",
    "vagy",
    "ami",
    "mint",
    "nem",
    "van",
    "volt",
    "lesz",
    "this",
    "that",
    "with",
    "from",
    "into",
    "then",
    "only",
}
ACTION_KEYWORDS = (
    "ir",
    "irni",
    "email",
    "hiv",
    "felhiv",
    "ker",
    "keres",
    "tisztaz",
    "megnez",
    "atnez",
    "rogzit",
    "szamol",
    "figyel",
    "rendez",
    "kidolgoz",
    "utana",
    "bead",
    "felvenni",
    "egyeztet",
)


@dataclass
class SurfaceItem:
    text: str
    source_kind: str
    source_path: str
    section: str
    normalized: str = field(init=False)

    def __post_init__(self) -> None:
        self.normalized = normalize_text(self.text)


@dataclass
class Obligation:
    text: str
    source_kind: str
    source_path: str
    section: str
    severity: str
    normalized: str = field(init=False)
    source_refs: list[str] = field(default_factory=list)
    matched_surface: str = ""

    def __post_init__(self) -> None:
        self.normalized = normalize_text(self.text)
        if not self.source_refs:
            self.source_refs = [f"{self.source_path}::{self.section}"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("carry-forward", "current-state"), required=True)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--source-date", type=date.fromisoformat)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def daily_path(day: date) -> Path:
    return DAILY_DIR / f"{day.isoformat()}.md"


def unwrap_wikilinks(text: str) -> str:
    return WIKILINK_RE.sub(r"\1", text)


def normalize_text(text: str) -> str:
    cleaned = unwrap_wikilinks(text)
    cleaned = daily_rollover.TAG_RE.sub("", cleaned)
    cleaned = cleaned.replace("—", " ").replace("–", " ")
    cleaned = unicodedata.normalize("NFKD", cleaned)
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    cleaned = cleaned.lower()
    cleaned = re.sub(r"[^\w\s:/.-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    return cleaned


def meaningful_tokens(text: str) -> set[str]:
    tokens = set()
    for token in normalize_text(text).split():
        if len(token) < 3 and not token.isdigit():
            continue
        if token in STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def surface_match_tokens(text: str) -> set[str]:
    tokens = meaningful_tokens(text)
    expanded = set(tokens)
    derived = set()
    for token in tokens:
        derived.add(token)
        derived.update(part for part in re.split(r"[-/]", token) if len(part) >= 3 or part.isdigit())
    for token in derived:
        expanded.add(token)
        if token.isdigit():
            continue
        compact = re.sub(r"[^a-z0-9]", "", token)
        if len(compact) >= 8:
            expanded.add(compact[:8])
    return expanded


def is_actionable_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    tokens = meaningful_tokens(normalized)
    if not tokens:
        return False
    if DATE_RE.search(text) or TIME_RE.search(text):
        return True
    if ":" in text:
        return True
    if any(token.endswith("ni") for token in tokens):
        return True
    return any(keyword in normalized for keyword in ACTION_KEYWORDS)


def split_obligation_text(text: str) -> list[str]:
    cleaned = unwrap_wikilinks(text).strip(" .")
    if not cleaned:
        return []
    parts = re.split(r"[;,]", cleaned)
    fragments: list[str] = []
    for part in parts:
        fragment = part.strip(" .")
        fragment = re.sub(r"^(es|majd)\s+", "", fragment, flags=re.IGNORECASE)
        if not fragment:
            continue
        if re.match(r"^(mert|de|ha|hogy)\b", fragment, flags=re.IGNORECASE):
            continue
        if len(meaningful_tokens(fragment)) < 2 and not (DATE_RE.search(fragment) or TIME_RE.search(fragment)):
            continue
        if is_actionable_text(fragment):
            fragments.append(fragment)
    if fragments:
        return fragments
    if len(meaningful_tokens(cleaned)) < 2 and not (DATE_RE.search(cleaned) or TIME_RE.search(cleaned)):
        return []
    return [cleaned] if is_actionable_text(cleaned) else []


def dedupe_surface(items: list[SurfaceItem]) -> list[SurfaceItem]:
    seen: dict[str, SurfaceItem] = {}
    for item in items:
        if not item.normalized:
            continue
        seen.setdefault(item.normalized, item)
    return list(seen.values())


def dedupe_obligations(items: list[Obligation]) -> list[Obligation]:
    merged: dict[str, Obligation] = {}
    for item in items:
        if not item.normalized:
            continue
        existing = merged.get(item.normalized)
        if existing is None:
            merged[item.normalized] = item
            continue
        for ref in item.source_refs:
            if ref not in existing.source_refs:
                existing.source_refs.append(ref)
        if SEVERITY_RANK[item.severity] > SEVERITY_RANK[existing.severity]:
            existing.severity = item.severity
    return list(merged.values())


def similarity(candidate: str, surface: str) -> tuple[float, int]:
    candidate_norm = normalize_text(candidate)
    surface_norm = normalize_text(surface)
    if not candidate_norm or not surface_norm:
        return 0.0, 0
    if candidate_norm == surface_norm:
        return 1.0, 999
    if candidate_norm in surface_norm or surface_norm in candidate_norm:
        return 0.92, 999

    candidate_tokens = surface_match_tokens(candidate_norm)
    surface_tokens = surface_match_tokens(surface_norm)
    if not candidate_tokens or not surface_tokens:
        return 0.0, 0

    shared = candidate_tokens & surface_tokens
    if not shared:
        return 0.0, 0

    coverage = len(shared) / len(candidate_tokens)
    reverse = len(shared) / len(surface_tokens)
    jaccard = len(shared) / len(candidate_tokens | surface_tokens)
    return max(coverage, reverse, jaccard), len(shared)


def best_surface_match(obligation: Obligation, surfaces: list[SurfaceItem]) -> SurfaceItem | None:
    best_item: SurfaceItem | None = None
    best_score = 0.0
    best_shared = 0
    for surface in surfaces:
        score, shared = similarity(obligation.text, surface.text)
        if score > best_score or (score == best_score and shared > best_shared):
            best_item = surface
            best_score = score
            best_shared = shared
    if best_item is None:
        return None
    if best_score >= 0.66 and best_shared >= 2:
        return best_item
    if best_score >= 0.5 and best_shared >= 3:
        return best_item
    return None


def collect_unchecked_checklists(path: Path, source_kind: str) -> list[SurfaceItem]:
    if not path.exists():
        return []
    items: list[SurfaceItem] = []
    section = ""
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
            section = header_match.group("title").strip()
            continue
        task_match = daily_rollover.TASK_RE.match(line)
        if not task_match:
            continue
        if task_match.group("mark").lower() == "x":
            continue
        body = daily_rollover.review_display_body(task_match.group("body").strip())
        items.append(
            SurfaceItem(
                text=unwrap_wikilinks(body),
                source_kind=source_kind,
                source_path=str(path.relative_to(ROOT)),
                section=section or "Checklist",
            )
        )
    return items


def collect_temporal_surface(path: Path) -> list[SurfaceItem]:
    if not path.exists():
        return []
    items: list[SurfaceItem] = []
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        header_match = HEADING_RE.match(line)
        if header_match:
            section = daily_rollover.normalize_section(header_match.group("title"))
            continue
        bullet_match = LIST_RE.match(line.strip())
        if not bullet_match or section not in RADAR_SURFACE_SECTIONS:
            continue
        body = unwrap_wikilinks(bullet_match.group("body").strip())
        if body.startswith("Source:"):
            continue
        if daily_rollover.normalize_section(body) in {"nincs", "nincs schema hiba"}:
            continue
        items.append(
            SurfaceItem(
                text=body,
                source_kind="temporal-radar",
                source_path=str(path.relative_to(ROOT)),
                section=section,
            )
        )
    return items


def collect_focus_surface(path: Path, source_kind: str) -> list[SurfaceItem]:
    if not path.exists():
        return []
    items: list[SurfaceItem] = []
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        heading_match = HEADING_RE.match(line)
        if heading_match:
            title = unwrap_wikilinks(heading_match.group("title").strip())
            level = len(heading_match.group("hashes"))
            if level == 2:
                section = daily_rollover.normalize_section(title)
            elif level == 3 and section in FOCUS_HEADING_SECTIONS:
                items.append(
                    SurfaceItem(
                        text=title,
                        source_kind=source_kind,
                        source_path=str(path.relative_to(ROOT)),
                        section=section,
                    )
                )
            continue
        bullet_match = LIST_RE.match(line.strip())
        if not bullet_match or section not in FOCUS_BULLET_SECTIONS:
            continue
        body = unwrap_wikilinks(bullet_match.group("body").strip())
        if daily_rollover.normalize_section(body) == "nincs":
            continue
        items.append(
            SurfaceItem(
                text=body,
                source_kind=source_kind,
                source_path=str(path.relative_to(ROOT)),
                section=section,
            )
        )
    return items


def add_obligation(
    items: list[Obligation],
    text: str,
    source_kind: str,
    source_path: Path,
    section: str,
    severity: str,
    split: bool = True,
) -> None:
    fragments = split_obligation_text(text) if split else [unwrap_wikilinks(text).strip(" .")]
    for fragment in fragments:
        if not fragment or not is_actionable_text(fragment):
            continue
        normalized = normalize_text(fragment)
        if any(normalized.startswith(prefix) for prefix in NON_OBLIGATION_PREFIXES):
            continue
        items.append(
            Obligation(
                text=fragment,
                source_kind=source_kind,
                source_path=str(source_path.relative_to(ROOT)),
                section=section,
                severity=severity,
            )
        )


def collect_open_loop_obligations(path: Path) -> list[Obligation]:
    if not path.exists():
        return []
    bucket = ""
    thread = ""
    items: list[Obligation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        heading_match = HEADING_RE.match(line)
        if heading_match:
            title = heading_match.group("title").strip()
            level = len(heading_match.group("hashes"))
            if level == 2:
                bucket = title
                thread = ""
            elif level == 3:
                thread = title
            continue
        next_step_match = NEXT_STEP_RE.match(line.strip())
        if not next_step_match or not thread:
            continue
        severity = "high" if daily_rollover.normalize_section(bucket) == "kritikus / kozeljovo" else "low"
        add_obligation(
            items,
            next_step_match.group("body").strip(),
            "open-loop",
            path,
            thread,
            severity,
            split=severity == "high",
        )
    return items


def current_state_bullet_actionable(text: str) -> bool:
    if DATE_RE.search(text) or TIME_RE.search(text):
        return True
    normalized = normalize_text(text)
    tokens = meaningful_tokens(text)
    if " kell " in f" {normalized} " or any(token.endswith("ni") for token in tokens):
        return True
    if any(keyword in normalized for keyword in ACTION_KEYWORDS):
        return True
    return ":" in text and any(keyword in normalized for keyword in ACTION_KEYWORDS)


def collect_current_state_obligations(path: Path) -> list[Obligation]:
    if not path.exists():
        return []
    items: list[Obligation] = []
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        heading_match = HEADING_RE.match(line)
        if heading_match:
            section = daily_rollover.normalize_section(heading_match.group("title"))
            continue
        bullet_match = LIST_RE.match(line.strip())
        if not bullet_match or section not in CURRENT_STATE_ACTION_SECTIONS:
            continue
        body = unwrap_wikilinks(bullet_match.group("body").strip())
        if not current_state_bullet_actionable(body):
            continue
        add_obligation(items, body, "current-state", path, "Mostani fokusz", "medium", split=False)
    return items


def collect_action_section_obligations(path: Path, default_severity: str) -> list[Obligation]:
    if not path.exists():
        return []
    items: list[Obligation] = []
    stack: list[tuple[int, str, bool, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            level = len(heading_match.group("hashes"))
            title = heading_match.group("title").strip()
            normalized = daily_rollover.normalize_section(title)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent_active = stack[-1][2] if stack else False
            parent_root = stack[-1][3] if stack else ""
            starts_action = any(keyword in normalized for keyword in ACTION_SECTION_KEYWORDS)
            active = starts_action or parent_active
            root = title if starts_action else parent_root
            stack.append((level, title, active, root))
            continue

        current = stack[-1] if stack else None
        if not current or not current[2]:
            continue
        list_match = LIST_RE.match(raw_line.strip())
        if not list_match:
            continue
        body = unwrap_wikilinks(list_match.group("body").strip())
        if body in GENERIC_BULLETS or not is_actionable_text(body):
            continue
        root_title = current[3] or current[1]
        section = root_title if current[1] == root_title else f"{root_title} > {current[1]}"
        severity = "high" if daily_rollover.normalize_section(root_title) == "preparation needed" else default_severity
        add_obligation(items, body, "recent-source", path, section, severity)
    return items


def temporal_coverage_target(obligation: Obligation, target_date: date) -> date:
    explicit = DATE_RE.search(obligation.text)
    if explicit:
        try:
            event_date = date.fromisoformat(explicit.group(0))
        except ValueError:
            return target_date
        if event_date >= target_date:
            return event_date
    return target_date


def event_match_tokens(event: temporal_radar.Event) -> set[str]:
    parts = [event.title, event.path.stem]
    if event.related_note:
        related = unwrap_wikilinks(event.related_note).strip()
        parts.append(related.rsplit("/", 1)[-1])
    return surface_match_tokens(" ".join(part for part in parts if part))


def temporal_surface_covered(obligation: Obligation, target_date: date) -> bool:
    event_date = temporal_coverage_target(obligation, target_date)
    candidate_tokens = surface_match_tokens(obligation.text)
    if not candidate_tokens:
        return False
    events, _errors = temporal_radar.load_events()
    for event in events:
        if event.status != "active" or event.event_date != event_date:
            continue
        shared = candidate_tokens & event_match_tokens(event)
        if len(shared) >= 2:
            return True
        if len(shared) == 1 and max(len(token) for token in shared) >= 8:
            return True
    return False


def carry_forward_report(target_date: date, explicit_source: date | None) -> dict[str, object]:
    source_date = daily_rollover.determine_source_date(target_date, explicit_source)
    target_path = daily_path(target_date)
    if source_date is None:
        return {
            "mode": "carry-forward",
            "status": "ok",
            "date": target_date.isoformat(),
            "source_date": "",
            "target_path": str(target_path.relative_to(ROOT)),
            "expected_carried": [],
            "expected_review": [],
            "missing_carried": [],
            "missing_review": [],
        }

    source_path = daily_path(source_date)
    tasks = daily_rollover.extract_tasks(source_path, source_date)
    expected_carried: list[str] = []
    expected_review: list[str] = []
    for task in tasks:
        action, _reason = daily_rollover.classify_task(task, target_date, interactive=False)
        cleaned = daily_rollover.sanitize_body(task.body, task.source_date, target_date)
        if action == "carry":
            expected_carried.append(cleaned)
        elif action == "review":
            expected_review.append(cleaned)

    surfaced = collect_unchecked_checklists(target_path, "daily-target")
    surfaced_norms = {item.normalized for item in surfaced}
    missing_carried = [item for item in daily_rollover.dedupe_preserve(expected_carried) if normalize_text(item) not in surfaced_norms]
    missing_review = [item for item in daily_rollover.dedupe_preserve(expected_review) if normalize_text(item) not in surfaced_norms]

    return {
        "mode": "carry-forward",
        "status": "loss_detected" if missing_carried or missing_review else "ok",
        "date": target_date.isoformat(),
        "source_date": source_date.isoformat(),
        "target_path": str(target_path.relative_to(ROOT)),
        "expected_carried": daily_rollover.dedupe_preserve(expected_carried),
        "expected_review": daily_rollover.dedupe_preserve(expected_review),
        "missing_carried": missing_carried,
        "missing_review": missing_review,
    }


def current_state_report(target_date: date) -> dict[str, object]:
    surfaced = dedupe_surface(
        collect_temporal_surface(TEMPORAL_RADAR)
        + collect_unchecked_checklists(daily_path(target_date), "daily")
        + collect_focus_surface(TODAY_FOCUS, "today-focus")
        + collect_focus_surface(WEEKLY_FOCUS, "weekly-focus")
    )

    last_full_compile = parse_last_full_compile(COMPILE_STATUS)
    recent_paths = [ROOT / rel_path for rel_path in collect_newer_sources(last_full_compile, target_date)]

    candidates = collect_open_loop_obligations(OPEN_LOOPS)
    candidates.extend(collect_current_state_obligations(CURRENT_STATE))

    same_day_review = weekly_review_path(target_date)
    if same_day_review.exists():
        candidates.extend(collect_action_section_obligations(same_day_review, "high"))

    for recent_path in recent_paths:
        candidates.extend(collect_action_section_obligations(recent_path, "medium"))

    unique_candidates = dedupe_obligations(candidates)
    unsurfaced: list[Obligation] = []
    for item in unique_candidates:
        if temporal_surface_covered(item, target_date):
            item.matched_surface = "temporal-event"
            continue
        match = best_surface_match(item, surfaced)
        if match:
            item.matched_surface = match.text
            continue
        unsurfaced.append(item)

    unsurfaced.sort(key=lambda item: (-SEVERITY_RANK[item.severity], item.source_path, item.text))
    high_signal_unsurfaced = [item for item in unsurfaced if item.severity == "high"]
    watch_signal_unsurfaced = [item for item in unsurfaced if item.severity == "medium"]

    return {
        "mode": "current-state",
        "status": "drift" if high_signal_unsurfaced else ("watch" if watch_signal_unsurfaced else "ok"),
        "date": target_date.isoformat(),
        "last_full_compile": last_full_compile.isoformat() if last_full_compile else "",
        "surfaced_execution": [
            {
                "text": item.text,
                "source_kind": item.source_kind,
                "source_path": item.source_path,
                "section": item.section,
            }
            for item in surfaced
        ],
        "candidate_obligations": [
            {
                "text": item.text,
                "source_kind": item.source_kind,
                "source_path": item.source_path,
                "section": item.section,
                "severity": item.severity,
                "source_refs": item.source_refs,
                "matched_surface": item.matched_surface,
            }
            for item in unique_candidates
        ],
        "unsurfaced_obligations": [
            {
                "text": item.text,
                "source_kind": item.source_kind,
                "source_path": item.source_path,
                "section": item.section,
                "severity": item.severity,
                "source_refs": item.source_refs,
            }
            for item in unsurfaced
        ],
        "high_signal_unsurfaced": [
            {
                "text": item.text,
                "source_kind": item.source_kind,
                "source_path": item.source_path,
                "section": item.section,
                "severity": item.severity,
                "source_refs": item.source_refs,
            }
            for item in high_signal_unsurfaced
        ],
    }


def render_text(payload: dict[str, object]) -> str:
    mode = payload["mode"]
    lines = [f"Mode: {mode}", f"Status: {payload['status']}"]
    if mode == "carry-forward":
        lines.append(f"Date: {payload['date']}")
        lines.append(f"Source date: {payload['source_date'] or 'none'}")
        lines.append(f"Target: {payload['target_path']}")
        lines.append(f"Expected carried: {len(payload['expected_carried'])}")
        lines.append(f"Expected review: {len(payload['expected_review'])}")
        lines.append(f"Missing carried: {len(payload['missing_carried'])}")
        for item in payload["missing_carried"]:
            lines.append(f"- carry missing :: {item}")
        lines.append(f"Missing review: {len(payload['missing_review'])}")
        for item in payload["missing_review"]:
            lines.append(f"- review missing :: {item}")
        return "\n".join(lines)

    lines.append(f"Date: {payload['date']}")
    lines.append(f"Last full compile: {payload['last_full_compile'] or 'none'}")
    lines.append(f"Surfaced execution items: {len(payload['surfaced_execution'])}")
    lines.append(f"Candidate obligations: {len(payload['candidate_obligations'])}")
    lines.append(f"Unsurfaced obligations: {len(payload['unsurfaced_obligations'])}")
    lines.append(f"High-signal unsurfaced obligations: {len(payload['high_signal_unsurfaced'])}")
    items_to_render = payload["high_signal_unsurfaced"] if payload["high_signal_unsurfaced"] else payload["unsurfaced_obligations"]
    for item in items_to_render:
        lines.append(
            f"- {item['severity']} :: {item['source_path']} :: {item['section']} :: {item['text']}"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if args.mode == "carry-forward":
        payload = carry_forward_report(args.date, args.source_date)
    else:
        payload = current_state_report(args.date)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
