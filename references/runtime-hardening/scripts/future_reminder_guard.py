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
from operational_drift_guard import COMPILE_STATUS, collect_newer_sources, parse_last_full_compile


ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "07-Daily"
OPEN_LOOPS = ROOT / "Meta" / "Operational" / "Open-Loops.md"
CURRENT_STATE = ROOT / "Meta" / "Operational" / "Current-State.md"

HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
LIST_RE = re.compile(r"^(?:-\s+|\d+\.\s+)(?P<body>.+\S)\s*$")
NEXT_STEP_RE = re.compile(r"^-+\s*Next step:\s*(?P<body>.+\S)\s*$")
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
WIKILINK_RE = re.compile(r"\[\[(?P<path>[^|\]]+)(?:\|(?P<label>[^\]]+))?\]\]")

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
CURRENT_STATE_ACTION_SECTIONS = {"mostani fokusz"}
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
    "felirat",
    "recept",
)


@dataclass
class ReminderCandidate:
    text: str
    source_kind: str
    source_path: str
    section: str
    event_date: date
    severity: str
    source_ref: str
    normalized: str = field(init=False)
    tokens: set[str] = field(init=False)
    related_paths: set[str] = field(default_factory=set)
    covered_by: str = ""

    def __post_init__(self) -> None:
        self.normalized = normalize_text(self.text)
        self.tokens = meaningful_tokens(self.text)
        if not self.related_paths:
            self.related_paths = set()


@dataclass
class EventCoverage:
    event_date: date
    title: str
    source_path: str
    related_path: str
    normalized: str = field(init=False)
    tokens: set[str] = field(init=False)

    def __post_init__(self) -> None:
        self.normalized = normalize_text(self.title)
        self.tokens = meaningful_tokens(self.title)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def daily_path(day: date) -> Path:
    return DAILY_DIR / f"{day.isoformat()}.md"


def unwrap_wikilinks(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group("label")
        path = match.group("path")
        return label if label else path

    return WIKILINK_RE.sub(replace, text)


def extract_link_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for match in WIKILINK_RE.finditer(text):
        raw_path = match.group("path").strip()
        if raw_path.endswith(".md"):
            paths.add(raw_path)
        elif "/" in raw_path:
            paths.add(f"{raw_path}.md")
    return paths


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


def tokenish_overlap(left: set[str], right: set[str]) -> int:
    shared = 0
    for lhs in left:
        for rhs in right:
            if lhs == rhs:
                shared += 1
                break
            if len(lhs) >= 6 and lhs in rhs:
                shared += 1
                break
            if len(rhs) >= 6 and rhs in lhs:
                shared += 1
                break
    return shared


def is_actionable_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    tokens = meaningful_tokens(text)
    if not tokens:
        return False
    if any(token.endswith("ni") for token in tokens):
        return True
    return any(keyword in normalized for keyword in ACTION_KEYWORDS)


def future_dates_from_text(text: str, target_date: date) -> list[date]:
    dates: list[date] = []
    cleaned = unwrap_wikilinks(daily_rollover.TAG_RE.sub("", text))
    for raw in DATE_RE.findall(cleaned):
        try:
            parsed = date.fromisoformat(raw)
        except ValueError:
            continue
        if parsed > target_date and parsed not in dates:
            dates.append(parsed)
    return dates


def explicit_task_date(body: str, target_date: date) -> date | None:
    _roll_mode, due_date, _event_like = daily_rollover.parse_task_tags(body)
    if due_date and due_date > target_date:
        return due_date
    return None


def add_candidate(
    candidates: list[ReminderCandidate],
    *,
    text: str,
    source_kind: str,
    source_path: Path,
    section: str,
    target_date: date,
    severity: str,
    extra_paths: set[str] | None = None,
) -> None:
    if not is_actionable_text(text):
        return
    future_dates = future_dates_from_text(text, target_date)
    if not future_dates:
        return
    related_paths = extract_link_paths(text)
    if extra_paths:
        related_paths.update(extra_paths)
    for future_date in future_dates:
        candidates.append(
            ReminderCandidate(
                text=text,
                source_kind=source_kind,
                source_path=str(source_path.relative_to(ROOT)),
                section=section,
                event_date=future_date,
                severity=severity,
                source_ref=f"{source_path.relative_to(ROOT)}::{section}",
                related_paths=related_paths,
            )
        )


def collect_daily_candidates(target_date: date) -> list[ReminderCandidate]:
    path = daily_path(target_date)
    if not path.exists():
        return []
    candidates: list[ReminderCandidate] = []
    for task in daily_rollover.extract_tasks(path, target_date):
        body = daily_rollover.review_display_body(task.body)
        future_date = explicit_task_date(task.body, target_date)
        text = daily_rollover.sanitize_body(body, target_date, target_date)
        extra_text = text if future_date is None else f"{text} {future_date.isoformat()}"
        add_candidate(
            candidates,
            text=extra_text,
            source_kind="daily" if task.source_kind == "checklist" else "daily-review",
            source_path=path,
            section=task.section or "Tasks",
            target_date=target_date,
            severity="high",
        )
    return candidates


def collect_open_loop_candidates(target_date: date) -> list[ReminderCandidate]:
    if not OPEN_LOOPS.exists():
        return []
    candidates: list[ReminderCandidate] = []
    bucket = ""
    thread = ""
    for raw_line in OPEN_LOOPS.read_text(encoding="utf-8").splitlines():
        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            title = heading_match.group("title").strip()
            level = len(heading_match.group("hashes"))
            if level == 2:
                bucket = title
                thread = ""
            elif level == 3:
                thread = title
            continue
        next_step_match = NEXT_STEP_RE.match(raw_line.strip())
        if not next_step_match or not thread:
            continue
        severity = "high" if daily_rollover.normalize_section(bucket) == "kritikus / kozeljovo" else "medium"
        add_candidate(
            candidates,
            text=next_step_match.group("body").strip(),
            source_kind="open-loop",
            source_path=OPEN_LOOPS,
            section=thread,
            target_date=target_date,
            severity=severity,
        )
    return candidates


def collect_current_state_candidates(target_date: date) -> list[ReminderCandidate]:
    if not CURRENT_STATE.exists():
        return []
    candidates: list[ReminderCandidate] = []
    section = ""
    for raw_line in CURRENT_STATE.read_text(encoding="utf-8").splitlines():
        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            section = daily_rollover.normalize_section(heading_match.group("title"))
            continue
        list_match = LIST_RE.match(raw_line.strip())
        if not list_match or section not in CURRENT_STATE_ACTION_SECTIONS:
            continue
        body = list_match.group("body").strip()
        add_candidate(
            candidates,
            text=body,
            source_kind="current-state",
            source_path=CURRENT_STATE,
            section="Mostani fokusz",
            target_date=target_date,
            severity="medium",
        )
    return candidates


def collect_recent_source_candidates(target_date: date) -> list[ReminderCandidate]:
    last_full_compile = parse_last_full_compile(COMPILE_STATUS)
    recent_paths = [ROOT / rel for rel in collect_newer_sources(last_full_compile, target_date)]
    candidates: list[ReminderCandidate] = []
    for path in recent_paths:
        if not path.exists():
            continue
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
            body_match = LIST_RE.match(raw_line.strip())
            if body_match:
                root_title = current[3] or current[1]
                section = root_title if current[1] == root_title else f"{root_title} > {current[1]}"
                add_candidate(
                    candidates,
                    text=body_match.group("body").strip(),
                    source_kind="recent-source",
                    source_path=path,
                    section=section,
                    target_date=target_date,
                    severity="medium",
                )
                continue
            next_step_match = NEXT_STEP_RE.match(raw_line.strip())
            if next_step_match:
                root_title = current[3] or current[1]
                section = root_title if current[1] == root_title else f"{root_title} > {current[1]}"
                add_candidate(
                    candidates,
                    text=next_step_match.group("body").strip(),
                    source_kind="recent-source",
                    source_path=path,
                    section=section,
                    target_date=target_date,
                    severity="medium",
                )
    return candidates


def dedupe_candidates(items: list[ReminderCandidate]) -> list[ReminderCandidate]:
    merged: dict[tuple[str, str], ReminderCandidate] = {}
    for item in items:
        key = (item.normalized, item.event_date.isoformat())
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            continue
        existing.related_paths.update(item.related_paths)
        if SEVERITY_RANK[item.severity] > SEVERITY_RANK[existing.severity]:
            existing.severity = item.severity
        if item.source_kind == "daily":
            existing.source_kind = item.source_kind
            existing.source_path = item.source_path
            existing.section = item.section
            existing.source_ref = item.source_ref
    return list(merged.values())


def related_note_path(raw: str | None) -> str:
    if not raw:
        return ""
    paths = extract_link_paths(raw)
    return next(iter(paths), "")


def load_temporal_coverages() -> list[EventCoverage]:
    events, _errors = temporal_radar.load_events()
    coverages: list[EventCoverage] = []
    for event in events:
        if event.status != "active":
            continue
        coverages.append(
            EventCoverage(
                event_date=event.event_date,
                title=event.title,
                source_path=str(event.path.relative_to(ROOT)),
                related_path=related_note_path(event.related_note),
            )
        )
    return coverages


def is_covered(candidate: ReminderCandidate, events: list[EventCoverage]) -> EventCoverage | None:
    same_day = [event for event in events if event.event_date == candidate.event_date]
    if not same_day:
        return None
    for event in same_day:
        if event.related_path and event.related_path in candidate.related_paths:
            return event
    best_event: EventCoverage | None = None
    best_score = -1
    for event in same_day:
        score = tokenish_overlap(candidate.tokens, event.tokens)
        if score > best_score:
            best_score = score
            best_event = event
    if best_event is None:
        return None
    if best_score >= 2:
        return best_event
    if best_score == 1:
        if best_event.normalized in candidate.normalized or candidate.normalized in best_event.normalized:
            return best_event
        for token in candidate.tokens:
            if len(token) >= 6 and token in best_event.normalized:
                return best_event
        for token in best_event.tokens:
            if len(token) >= 6 and token in candidate.normalized:
                return best_event
    return None


def build_report(target_date: date) -> dict[str, object]:
    candidates = dedupe_candidates(
        collect_daily_candidates(target_date)
        + collect_open_loop_candidates(target_date)
        + collect_current_state_candidates(target_date)
        + collect_recent_source_candidates(target_date)
    )
    events = load_temporal_coverages()
    uncovered: list[ReminderCandidate] = []
    for candidate in candidates:
        match = is_covered(candidate, events)
        if match is None:
            uncovered.append(candidate)
            continue
        candidate.covered_by = match.source_path

    uncovered.sort(key=lambda item: (-SEVERITY_RANK[item.severity], item.event_date, item.source_path, item.text))
    high = [item for item in uncovered if item.severity == "high"]
    status = "drift" if high else ("watch" if uncovered else "ok")

    return {
        "date": target_date.isoformat(),
        "mode": "future-reminder",
        "status": status,
        "candidate_count": len(candidates),
        "uncovered_count": len(uncovered),
        "high_signal_uncovered_count": len(high),
        "candidates": [
            {
                "text": item.text,
                "event_date": item.event_date.isoformat(),
                "source_kind": item.source_kind,
                "source_path": item.source_path,
                "section": item.section,
                "severity": item.severity,
                "source_ref": item.source_ref,
                "covered_by": item.covered_by,
            }
            for item in candidates
        ],
        "uncovered_candidates": [
            {
                "text": item.text,
                "event_date": item.event_date.isoformat(),
                "source_kind": item.source_kind,
                "source_path": item.source_path,
                "section": item.section,
                "severity": item.severity,
                "source_ref": item.source_ref,
            }
            for item in uncovered
        ],
    }


def render_text(payload: dict[str, object]) -> str:
    lines = [
        "Mode: future-reminder",
        f"Status: {payload['status']}",
        f"Date: {payload['date']}",
        f"Candidates: {payload['candidate_count']}",
        f"Uncovered: {payload['uncovered_count']}",
        f"High-signal uncovered: {payload['high_signal_uncovered_count']}",
    ]
    for item in payload["uncovered_candidates"]:
        lines.append(
            f"- {item['severity']} :: {item['event_date']} :: {item['source_path']} :: {item['section']} :: {item['text']}"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    payload = build_report(args.date)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
