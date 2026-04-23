#!/usr/bin/env python3
"""Report whether a daily note still needs a measurements prompt."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "07-Daily"
STATE_PATH = ROOT / "Meta" / "states" / "daily-measurements-nudges.json"
SECTION_HEADER = "## Measurements"
HEADER_RE = re.compile(r"^##\s+")
FIELD_RE = re.compile(r"^-\s*(?P<label>[^:]+):\s*(?P<value>.*)$")
TIME_RE = re.compile(r"\b(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)\b")
STATE_RETENTION_DAYS = 45
PROMPT_COOLDOWN = timedelta(hours=4)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    prompt_fragment: str


@dataclass(frozen=True)
class PromptDecision:
    status: str
    needed: list[FieldSpec]
    prompt: str
    fingerprint: str
    suppression_reason: str = ""
    cooldown_until: str = ""


FIELDS = (
    FieldSpec("wake_time", "Felkelesi ido", "a felkelesi idot"),
    FieldSpec("bed_time", "Mai esti lefekves (kb)", "a mai esti lefekves kb. idejet"),
    FieldSpec(
        "late_reason",
        "Kesoi lefekves oka (ha ejfel utan)",
        "ha ejfel utanra csuszik, a kesoi okot",
    ),
    FieldSpec(
        "rhythm_note",
        "Alvas ritmusa megfigyeles",
        "egy rovid megfigyelest az alvas ritmusarol",
    ),
)
FIELD_BY_LABEL = {field.label: field for field in FIELDS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--now",
        help="Override current local datetime, ISO format, e.g. 2026-04-21T20:15",
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        help="Do not read or update prompt state; useful for diagnostics.",
    )
    return parser.parse_args()


def resolve_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now()
    return datetime.fromisoformat(raw)


def daily_path(day: date) -> Path:
    return DAILY_DIR / f"{day.isoformat()}.md"


def load_prompt_state() -> dict[str, dict[str, object]]:
    if not STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    cleaned: dict[str, dict[str, object]] = {}
    for day_key, value in payload.items():
        if not isinstance(day_key, str) or not isinstance(value, dict):
            continue
        prompts = value.get("prompts", {})
        if not isinstance(prompts, dict):
            prompts = {}
        cleaned_prompts = {
            key: str(timestamp)
            for key, timestamp in prompts.items()
            if isinstance(key, str) and isinstance(timestamp, str)
        }
        # Backward compatibility with the previous once-per-day suppression shape.
        if not cleaned_prompts:
            fingerprints = value.get("prompted_fingerprints", [])
            if not isinstance(fingerprints, list):
                fingerprints = []
            legacy_last_prompt_at = str(value.get("last_prompt_at", ""))
            for item in fingerprints:
                if isinstance(item, str):
                    cleaned_prompts[item] = legacy_last_prompt_at
        cleaned[day_key] = {
            "prompts": cleaned_prompts,
            "last_prompt_at": str(value.get("last_prompt_at", "")),
        }
    return cleaned


def save_prompt_state(state: dict[str, dict[str, object]], today: date) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    retained: dict[str, dict[str, object]] = {}
    for day_key, value in state.items():
        try:
            day_value = date.fromisoformat(day_key)
        except ValueError:
            continue
        if abs((today - day_value).days) > STATE_RETENTION_DAYS:
            continue
        retained[day_key] = value
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(retained, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(STATE_PATH)


def extract_measurements(path: Path) -> tuple[bool, dict[str, str]]:
    values = {field.key: "" for field in FIELDS}
    if not path.exists():
        return False, values

    lines = path.read_text(encoding="utf-8").splitlines()
    in_section = False
    section_exists = False

    for line in lines:
        stripped = line.strip()
        if stripped == SECTION_HEADER:
            in_section = True
            section_exists = True
            continue
        if in_section and HEADER_RE.match(stripped):
            break
        if not in_section:
            continue
        match = FIELD_RE.match(stripped)
        if not match:
            continue
        field = FIELD_BY_LABEL.get(match.group("label").strip())
        if not field:
            continue
        values[field.key] = match.group("value").strip()

    # Some historical daily notes repeated the filled measurement lines later in
    # the file instead of editing the original block. Honor the latest non-empty
    # value anywhere in the note so the guard does not keep prompting incorrectly.
    for line in lines:
        match = FIELD_RE.match(line.strip())
        if not match:
            continue
        field = FIELD_BY_LABEL.get(match.group("label").strip())
        if not field:
            continue
        value = match.group("value").strip()
        if value:
            values[field.key] = value

    return section_exists, values


def bedtime_after_midnight(value: str) -> bool:
    match = TIME_RE.search(value)
    if not match:
        return False
    hour = int(match.group("hour"))
    return 0 <= hour < 5


def required_fields(day: date, now_dt: datetime, values: dict[str, str]) -> list[FieldSpec]:
    today = now_dt.date()
    missing = [field for field in FIELDS if not values[field.key]]
    if day < today:
        return missing

    result: list[FieldSpec] = []
    if not values["wake_time"]:
        result.append(FIELD_BY_LABEL["Felkelesi ido"])

    if now_dt.hour >= 18:
        if not values["bed_time"]:
            result.append(FIELD_BY_LABEL["Mai esti lefekves (kb)"])
        if not values["rhythm_note"]:
            result.append(FIELD_BY_LABEL["Alvas ritmusa megfigyeles"])

    if values["bed_time"] and bedtime_after_midnight(values["bed_time"]) and not values["late_reason"]:
        result.append(FIELD_BY_LABEL["Kesoi lefekves oka (ha ejfel utan)"])

    return result


def join_fragments(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} es {parts[1]}"
    return ", ".join(parts[:-1]) + f", es {parts[-1]}"


def build_prompt(
    note_exists: bool,
    section_exists: bool,
    needed: list[FieldSpec],
) -> str:
    if not needed:
        return ""
    intro = "A mai `Measurements` meg hianyos."
    if not note_exists:
        intro = "A mai daily note meg nincs letrehozva, es a `Measurements` is hianyzik."
    elif not section_exists:
        intro = "A mai daily note-ban a `Measurements` blokk meg hianyzik."
    request = join_fragments([field.prompt_fragment for field in needed])
    return f"{intro} Beirom neked, ha megadod {request}?"


def prompt_fingerprint(day: date, needed: list[FieldSpec]) -> str:
    keys = ",".join(sorted(field.key for field in needed))
    return f"{day.isoformat()}::{keys}"


def prompt_decision(
    day: date,
    now_dt: datetime,
    note_exists: bool,
    section_exists: bool,
    needed: list[FieldSpec],
    *,
    stateless: bool,
) -> PromptDecision:
    prompt = build_prompt(note_exists, section_exists, needed)
    fingerprint = prompt_fingerprint(day, needed) if needed else ""
    if not needed:
        return PromptDecision(status="ok", needed=[], prompt="", fingerprint="")
    if stateless:
        return PromptDecision(status="prompt", needed=needed, prompt=prompt, fingerprint=fingerprint)

    state = load_prompt_state()
    day_key = day.isoformat()
    entry = state.get(day_key, {})
    prompts = entry.get("prompts", {})
    if not isinstance(prompts, dict):
        prompts = {}

    last_prompt_raw = prompts.get(fingerprint, "")
    if isinstance(last_prompt_raw, str) and last_prompt_raw:
        try:
            last_prompt_at = datetime.fromisoformat(last_prompt_raw)
        except ValueError:
            last_prompt_at = None
        if last_prompt_at is not None:
            cooldown_until = last_prompt_at + PROMPT_COOLDOWN
            if now_dt < cooldown_until:
                return PromptDecision(
                    status="suppressed",
                    needed=needed,
                    prompt="",
                    fingerprint=fingerprint,
                    suppression_reason="cooldown_active_for_same_required_fields",
                    cooldown_until=cooldown_until.isoformat(timespec="minutes"),
                )

    prompts[fingerprint] = now_dt.isoformat(timespec="minutes")
    state[day_key] = {
        "prompts": prompts,
        "last_prompt_at": now_dt.isoformat(timespec="minutes"),
    }
    save_prompt_state(state, now_dt.date())
    return PromptDecision(status="prompt", needed=needed, prompt=prompt, fingerprint=fingerprint)


def evaluate_measurements(
    day: date,
    now_dt: datetime,
    *,
    stateless: bool = False,
) -> dict[str, object]:
    path = daily_path(day)
    section_exists, values = extract_measurements(path)
    missing_fields = [field.label for field in FIELDS if not values[field.key]]
    decision = prompt_decision(
        day,
        now_dt,
        path.exists(),
        section_exists,
        required_fields(day, now_dt, values),
        stateless=stateless,
    )
    return {
        "date": day.isoformat(),
        "now": now_dt.isoformat(timespec="minutes"),
        "daily_note_path": str(path.relative_to(ROOT)),
        "daily_note_exists": path.exists(),
        "measurements_section_exists": section_exists,
        "values": values,
        "missing_fields": missing_fields,
        "required_now": [field.label for field in decision.needed],
        "status": decision.status,
        "prompt": decision.prompt,
        "prompt_fingerprint": decision.fingerprint,
        "suppression_reason": decision.suppression_reason,
        "cooldown_until": decision.cooldown_until,
    }


def main() -> int:
    args = parse_args()
    now_dt = resolve_now(args.now)
    payload = evaluate_measurements(args.date, now_dt, stateless=args.stateless)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
