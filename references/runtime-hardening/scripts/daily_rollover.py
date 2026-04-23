#!/usr/bin/env python3
"""Create or update a daily note by rolling forward unfinished tasks.

Default behavior:
- unchecked checklist items roll forward
- completed checklist items do not
- explicit one-time / event tasks do not roll after their date passes
- ambiguous past-due tasks are surfaced in a review section instead of disappearing

Supported inline hints inside task text:
- [due:YYYY-MM-DD]
- [event:YYYY-MM-DD HH:MM]
- [roll:always|until_due|never|ask]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "07-Daily"
TEMPLATE_PATH = ROOT / "Templates" / "Daily Note.md"

TASK_RE = re.compile(r"^(\s*-\s\[(?P<mark>[ xX])\]\s)(?P<body>.*)$")
HEADER_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
TAG_RE = re.compile(r"\[(due|event|roll):([^\]]+)\]")
WIKILINK_RE = re.compile(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]")
REVIEW_REASON_RE = re.compile(r"\s+\(ok:\s*.*\)\s*$")
REVIEW_REASON_CAPTURE_RE = re.compile(r"\s+\(ok:\s*(?P<reason>.*)\)\s*$")

ROLL_ALWAYS = "always"
ROLL_UNTIL_DUE = "until_due"
ROLL_NEVER = "never"
ROLL_ASK = "ask"

CHECKLIST_SECTION_PREFIXES = (
    "tasks",
    "open loops / unfinished",
    "open loops",
    "unfinished",
    "atjott nyitott pontok",
    "átjött nyitott pontok",
)
REVIEW_SECTION = "needs review"

WEEKDAY_SEED_TASKS: dict[int, list[str]] = {
    6: ["Heti review kitoltese a Weekly Review sablon szerint."],
}

MEASUREMENTS_BLOCK = "\n".join(
    [
        "- Felkelesi ido:",
        "- Mai esti lefekves (kb):",
        "- Kesoi lefekves oka (ha ejfel utan):",
        "- Alvas ritmusa megfigyeles:",
    ]
)

ONCE_KEYWORDS = (
    "masszazs",
    "idopont",
    "időpont",
    "appointment",
    "meeting",
    "orvos",
    "allatorvos",
    "állatorvos",
    "menni",
)


@dataclass
class Task:
    source_date: date
    section: str
    raw_prefix: str
    body: str
    source_line: int
    source_kind: str = "checklist"
    review_reason: str = ""


@dataclass
class Decision:
    body: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--source-date", type=date.fromisoformat)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


def normalize_section(title: str) -> str:
    return " ".join(title.strip().lower().split())


def daily_path(day: date) -> Path:
    return DAILY_DIR / f"{day.isoformat()}.md"


def unwrap_wikilinks(text: str) -> str:
    return WIKILINK_RE.sub(r"\1", text)


def normalize_for_inference(body: str) -> str:
    cleaned = TAG_RE.sub("", body)
    cleaned = unwrap_wikilinks(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_task_tags(body: str) -> tuple[str, date | None, bool]:
    roll_mode = ROLL_UNTIL_DUE
    due_date: date | None = None
    event_like = False

    for key, raw_value in TAG_RE.findall(body):
        value = raw_value.strip()
        if key == "roll":
            if value in {ROLL_ALWAYS, ROLL_UNTIL_DUE, ROLL_NEVER, ROLL_ASK}:
                roll_mode = value
        elif key == "due":
            try:
                due_date = date.fromisoformat(value)
            except ValueError:
                pass
        elif key == "event":
            value = value.split()[0]
            try:
                due_date = date.fromisoformat(value)
                event_like = True
            except ValueError:
                pass

    return roll_mode, due_date, event_like


def infer_due_date(body: str, source_date: date) -> tuple[date | None, bool]:
    roll_mode, explicit_due, explicit_event = parse_task_tags(body)
    if explicit_due:
        return explicit_due, explicit_event

    cleaned = normalize_for_inference(body)
    iso_match = DATE_RE.search(cleaned)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1)), explicit_event
        except ValueError:
            pass

    lowered = cleaned.lower()
    if "holnap" in lowered:
        return source_date + timedelta(days=1), explicit_event
    if re.search(r"\bma\b", lowered):
        return source_date, explicit_event

    return None, explicit_event


def looks_one_time(body: str, due_date: date | None, explicit_event: bool) -> bool:
    cleaned = normalize_for_inference(body)
    lowered = cleaned.lower()
    if explicit_event:
        return True
    if due_date and TIME_RE.search(cleaned):
        return True
    return any(keyword in lowered for keyword in ONCE_KEYWORDS) and TIME_RE.search(cleaned) is not None


def sanitize_body(body: str, source_date: date, target_date: date) -> str:
    cleaned = TAG_RE.sub("", body)
    lowered = cleaned.lower()
    if "holnap" in lowered and source_date + timedelta(days=1) == target_date:
        cleaned = re.sub(r"\bholnap\b", "Ma", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def review_display_body(body: str) -> str:
    return REVIEW_REASON_RE.sub("", body).strip()


def review_reason(body: str) -> str:
    match = REVIEW_REASON_CAPTURE_RE.search(body)
    return match.group("reason").strip() if match else ""


def list_daily_dates() -> list[date]:
    result: list[date] = []
    if not DAILY_DIR.exists():
        return result
    for path in DAILY_DIR.glob("*.md"):
        try:
            result.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return sorted(result)


def determine_source_date(target_date: date, explicit: date | None) -> date | None:
    if explicit:
        return explicit
    candidates = [day for day in list_daily_dates() if day < target_date]
    return candidates[-1] if candidates else None


def extract_tasks(path: Path, source_date: date) -> list[Task]:
    lines = path.read_text(encoding="utf-8").splitlines()
    tasks: list[Task] = []
    current_section = ""
    in_comment = False
    for index, line in enumerate(lines, start=1):
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        header_match = HEADER_RE.match(line)
        if header_match:
            current_section = normalize_section(header_match.group("title"))
            continue
        task_match = TASK_RE.match(line)
        if not task_match:
            continue
        if task_match.group("mark").lower() == "x":
            continue
        raw_body = task_match.group("body").strip()
        if current_section == REVIEW_SECTION:
            tasks.append(
                Task(
                    source_date=source_date,
                    section=current_section,
                    raw_prefix=task_match.group(1),
                    body=review_display_body(raw_body),
                    source_line=index,
                    source_kind="needs-review",
                    review_reason=review_reason(raw_body) or "unresolved prior review item",
                )
            )
            continue
        if any(current_section.startswith(prefix) for prefix in CHECKLIST_SECTION_PREFIXES):
            tasks.append(
                Task(
                    source_date=source_date,
                    section=current_section,
                    raw_prefix=task_match.group(1),
                    body=raw_body,
                    source_line=index,
                )
            )
    return tasks


def prompt_yes_no(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def classify_task(task: Task, target_date: date, interactive: bool) -> tuple[str, str]:
    if task.source_kind == "needs-review":
        return "review", task.review_reason or "unresolved prior review item"

    roll_mode, tagged_due, explicit_event = parse_task_tags(task.body)
    due_date, inferred_event = infer_due_date(task.body, task.source_date)
    if tagged_due:
        due_date = tagged_due
    elif roll_mode == ROLL_ALWAYS and not explicit_event:
        due_date = None
        inferred_event = False
    event_like = looks_one_time(task.body, due_date, explicit_event or inferred_event)

    if roll_mode == ROLL_NEVER:
        return "skip", "explicit roll:never"
    if roll_mode == ROLL_ASK:
        if interactive:
            carry = prompt_yes_no(f"Carry forward: {task.body}")
            return ("carry", "interactive confirm") if carry else ("review", "interactive rejected")
        return "review", "explicit roll:ask"

    if due_date and due_date < target_date:
        if event_like:
            return "skip", f"expired one-time task ({due_date.isoformat()})"
        if interactive:
            carry = prompt_yes_no(f"Past-due task; carry forward anyway: {task.body}")
            return ("carry", "interactive overdue confirm") if carry else ("review", "past-due needs review")
        return "review", f"past-due task ({due_date.isoformat()})"

    if due_date == target_date and "holnap" in normalize_for_inference(task.body).lower():
        return "carry", "relative day matched target"

    return "carry", "unfinished task"


def render_new_daily(target_date: date) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        '<% tp.date.now("dddd, MMMM D, YYYY") %>': target_date.isoformat(),
        "<% tp.date.now('YYYY-MM-DD') %>": target_date.isoformat(),
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    template = ensure_measurements_section(template)
    seeded_tasks = seed_tasks_for_date(target_date)
    if seeded_tasks:
        template = merge_into_tasks_section(template, seeded_tasks)
    return template


def ensure_measurements_section(content: str) -> str:
    if "## Measurements" in content:
        return content
    block = f"## Measurements\n\n{MEASUREMENTS_BLOCK}\n\n"
    marker = "## End of Day Reflection"
    if marker in content:
        return content.replace(marker, block + marker, 1)
    return content.rstrip() + "\n\n" + block


def insert_under_section(content: str, section_title: str, block: str) -> str:
    lines = content.splitlines()
    target_header = f"## {section_title}"
    for index, line in enumerate(lines):
        if line.strip() != target_header:
            continue
        insert_at = index + 1
        while insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        lines[insert_at:insert_at] = ["", *block.splitlines(), ""]
        return "\n".join(lines).rstrip() + "\n"
    if not content.endswith("\n"):
        content += "\n"
    return content + f"\n{target_header}\n\n{block}\n"


def replace_or_append_section(content: str, section_title: str, block: str) -> str:
    header = f"## {section_title}"
    pattern = re.compile(rf"(?ms)^{re.escape(header)}\n.*?(?=^## |\Z)")
    content = re.sub(pattern, "", content).rstrip() + "\n"
    new_section = [header, "", *block.splitlines()]
    return content.rstrip() + "\n\n" + "\n".join(new_section) + "\n"


def dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def strip_empty_task_placeholders(content: str) -> str:
    return re.sub(r"(?m)^\s*-\s\[\s\]\s*$\n?", "", content)


def seed_tasks_for_date(target_date: date) -> list[str]:
    return WEEKDAY_SEED_TASKS.get(target_date.weekday(), [])


def existing_task_keys(content: str) -> set[str]:
    keys: set[str] = set()
    in_comment = False
    for line in content.splitlines():
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        match = TASK_RE.match(line)
        if not match:
            continue
        key = sanitize_body(review_display_body(match.group("body").strip()), date.min, date.min).lower()
        keys.add(key)
    return keys


def merge_into_tasks_section(content: str, carried: list[str]) -> str:
    content = strip_empty_task_placeholders(content)
    carried = dedupe_preserve(carried)
    existing = existing_task_keys(content)
    carried = [item for item in carried if item.strip().lower() not in existing]
    if not carried:
        return content
    block = "\n".join(f"- [ ] {item}" for item in carried)
    return insert_under_section(content, "Tasks", block)


def merge_review_section(content: str, review: list[Decision]) -> str:
    if not review:
        return content
    lines = [
        "## Needs Review",
        "",
        "Ezek nem vesztek el, csak nem volt egyertelmu az automatikus gorgetesuk:",
        "",
    ]
    for item in review:
        lines.append(f"- [ ] {item.body} (ok: {item.reason})")
    return replace_or_append_section(content, "Needs Review", "\n".join(lines[2:]))


def unchecked_task_keys(content: str) -> set[str]:
    keys: set[str] = set()
    in_comment = False
    for line in content.splitlines():
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        match = TASK_RE.match(line)
        if not match:
            continue
        if match.group("mark").lower() == "x":
            continue
        key = sanitize_body(review_display_body(match.group("body").strip()), date.min, date.min).lower()
        keys.add(key)
    return keys


def verify_continuity(content: str, carried: list[str], review: list[Decision]) -> tuple[list[str], list[str]]:
    surfaced = unchecked_task_keys(content)
    missing_carried = [item for item in dedupe_preserve(carried) if item.strip().lower() not in surfaced]
    missing_review = [item.body for item in review if item.body.strip().lower() not in surfaced]
    return missing_carried, dedupe_preserve(missing_review)


def build_summary(carried: list[str], skipped: list[Decision], review: list[Decision], target: Path) -> str:
    parts = [f"Target: {target}"]
    parts.append(f"Carried: {len(carried)}")
    if carried:
        parts.extend(f"  - {item}" for item in carried)
    parts.append(f"Skipped: {len(skipped)}")
    if skipped:
        parts.extend(f"  - {item.body} [{item.reason}]" for item in skipped)
    parts.append(f"Needs review: {len(review)}")
    if review:
        parts.extend(f"  - {item.body} [{item.reason}]" for item in review)
    return "\n".join(parts)


def main() -> int:
    args = parse_args()
    target_date: date = args.date
    source_date = determine_source_date(target_date, args.source_date)
    target_path = daily_path(target_date)

    if source_date is None:
        if args.write and not target_path.exists():
            target_path.write_text(render_new_daily(target_date), encoding="utf-8")
        print(build_summary([], [], [], target_path))
        return 0

    source_path = daily_path(source_date)
    if not source_path.exists():
        print(f"Source note not found: {source_path}", file=sys.stderr)
        return 1

    tasks = extract_tasks(source_path, source_date)
    carried: list[str] = []
    skipped: list[Decision] = []
    review: list[Decision] = []

    for task in tasks:
        action, reason = classify_task(task, target_date, args.interactive)
        clean_body = sanitize_body(task.body, task.source_date, target_date)
        if action == "carry":
            carried.append(clean_body)
        elif action == "skip":
            skipped.append(Decision(body=clean_body, reason=reason))
        else:
            review.append(Decision(body=clean_body, reason=reason))

    if args.write:
        content = target_path.read_text(encoding="utf-8") if target_path.exists() else render_new_daily(target_date)
        content = ensure_measurements_section(content)
        seeded_tasks = seed_tasks_for_date(target_date)
        if seeded_tasks:
            content = merge_into_tasks_section(content, seeded_tasks)
        if carried:
            content = merge_into_tasks_section(content, carried)
        if review:
            content = merge_review_section(content, review)
        target_path.write_text(content, encoding="utf-8")
        missing_carried, missing_review = verify_continuity(content, carried, review)
        if missing_carried or missing_review:
            print(build_summary(carried, skipped, review, target_path))
            print("Continuity verification failed after write.", file=sys.stderr)
            for item in missing_carried:
                print(f"Missing carried task: {item}", file=sys.stderr)
            for item in missing_review:
                print(f"Missing review task: {item}", file=sys.stderr)
            return 2

    print(build_summary(carried, skipped, review, target_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
