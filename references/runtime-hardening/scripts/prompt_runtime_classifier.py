#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date

ISO_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
DOT_DATE_RE = re.compile(r"\b(0?[1-9]|1[0-2])\.(0?[1-9]|[12]\d|3[01])\.?\b")

TEMPORAL_KEYWORDS = (
    "holnap",
    "ma",
    "mostmar mai",
    "jovo",
    "jovo heten",
    "jovo honap",
    "hatarido",
    "idopont",
    "talalkozo",
    "appointment",
    "deadline",
    "reminder",
)
MEASUREMENTS_KEYWORDS = (
    "measurements",
    "meres",
    "alvas",
    "lefekves",
    "felkeles",
    "ritmus",
    "sleep",
    "wake",
    "bedtime",
)
INBOX_KEYWORDS = (
    "inbox",
    "triage",
    "digest",
    "sort my notes",
    "process the inbox",
)
STATE_QUERY_KEYWORDS = (
    "mi a feladat",
    "mi a teendo",
    "milyen feladataim",
    "feladataim vannak",
    "mi van ma",
    "mara",
    "mit csinaljak",
    "what should i do",
    "what now",
    "nyitva",
    "prioritas",
    "fokusz",
    "open loop",
    "current state",
    "weekly review",
)
CAPTURE_KEYWORDS = (
    "ugy erzem",
    "megint",
    "elveszett",
    "szetszort",
    "bug",
    "spamol",
    "nem eleg",
    "nem jo",
    "this happened again",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    return parser.parse_args()


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in folded if not unicodedata.combining(char))


def has_future_date(prompt: str, today: date) -> bool:
    for match in ISO_DATE_RE.findall(prompt):
        try:
            if date.fromisoformat(match) > today:
                return True
        except ValueError:
            continue
    normalized = normalize(prompt)
    return bool(DOT_DATE_RE.search(normalized))


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_prompt(prompt: str, today: date) -> dict[str, object]:
    normalized = normalize(prompt)
    touches: set[str] = set()

    explicit_future_date = has_future_date(prompt, today)
    temporal_language = contains_any(normalized, TEMPORAL_KEYWORDS)
    measurements_related = contains_any(normalized, MEASUREMENTS_KEYWORDS)
    inbox_related = contains_any(normalized, INBOX_KEYWORDS)
    state_query = contains_any(normalized, STATE_QUERY_KEYWORDS)
    capture_bearing = len(prompt.strip()) > 40 and contains_any(normalized, CAPTURE_KEYWORDS)

    if explicit_future_date or temporal_language:
        touches.add("temporal")
    if measurements_related:
        touches.update({"daily", "measurements"})
    if inbox_related:
        touches.add("inbox")
    if state_query or capture_bearing:
        touches.update({"daily", "operational"})
    if not touches and ("task" in normalized or "feladat" in normalized):
        touches.update({"daily", "operational"})

    return {
        "touches": sorted(touches),
        "signals": {
            "explicit_future_date": explicit_future_date,
            "temporal_language": temporal_language,
            "measurements_related": measurements_related,
            "inbox_related": inbox_related,
            "state_query": state_query,
            "capture_bearing": capture_bearing,
        },
    }


def main() -> int:
    args = parse_args()
    payload = classify_prompt(args.prompt, args.today)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
