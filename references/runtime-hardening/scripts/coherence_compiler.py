#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STABILIZATION_DIR = ROOT / "02-Areas" / "Personal" / "Stabilization"
OPERATIONAL_DIR = ROOT / "Meta" / "Operational"
CURRENT_STATE_PATH = OPERATIONAL_DIR / "Current-State.md"
OPEN_LOOPS_PATH = OPERATIONAL_DIR / "Open-Loops.md"
TEMPORAL_RADAR_PATH = OPERATIONAL_DIR / "Temporal-Radar.md"
WEEKLY_FOCUS_PATH = OPERATIONAL_DIR / "Weekly-Focus.md"
TODAY_FOCUS_PATH = OPERATIONAL_DIR / "Today-Focus.md"
DAILY_DIR = ROOT / "07-Daily"

HEADER_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
BULLET_RE = re.compile(r"^-\s+(?P<body>.+\S)\s*$")
TASK_RE = re.compile(r"^- \[(?P<mark>[ xX])\]\s+(?P<body>.+\S)\s*$")
LINK_RE = re.compile(r"\[\[(.+?)\]\]")


@dataclass(frozen=True)
class BucketSpec:
    bucket_id: str
    title: str
    weekly_reason: str
    today_reason: str
    keywords: tuple[str, ...]


@dataclass
class Signal:
    text: str
    label: str
    weight: int
    source_ref: str
    bucket_hint: str = ""


@dataclass
class OpenLoopEntry:
    band: str
    title: str
    status: str
    next_step: str
    why_it_matters: str
    source_refs: list[str]


BUCKETS = (
    BucketSpec(
        bucket_id="stabilization",
        title="Stabilizalas es tenyleges rendszerhasznalat",
        weekly_reason="A het akkor marad egyben, ha a rendszerhasznalat, ritmus es minimum mukodes nem csuszik vissza tiszta fejben-hordasba.",
        today_reason="A mai nap akkor lesz hasznos, ha a fix dolgok mellett csak annyi strukturat tart meg, amennyi tenyleg vegrehajtast segit.",
        keywords=(
            "stabil",
            "stabiliz",
            "rendszer",
            "rendszerszintu",
            "mukodes",
            "minimum",
            "ritmus",
            "alvas",
            "meres",
            "eletrendszer",
            "napirend",
        ),
    ),
    BucketSpec(
        bucket_id="personal_case",
        title="Szemelyes ugy es a kapcsolodo konkret adminnyomas",
        weekly_reason="Az erzelmileg terhelo, de adminisztrativ lepest igenylo ugyeknel a kovetkezo lepest ki kell venni a fejbol es kovetheto allapotba kell tenni.",
        today_reason="Ma nem az egesz problemat kell megoldani, hanem a kovetkezo konkret lepest rogzitett adminlepesre huzni.",
        keywords=(
            "szemelyes",
            "vizsgalat",
            "egyeztetes",
            "kedvezmeny",
            "koltseg",
            "ar",
            "idopont",
            "email",
            "telefon",
            "ajanlat",
            "foglalas",
        ),
    ),
    BucketSpec(
        bucket_id="application_path",
        title="Jelentkezesi es kepzesi konkretizalas",
        weekly_reason="A jelentkezesi es kepzesi szalak csak akkor mozognak, ha a keretbol tracked kovetkezo lepes lesz.",
        today_reason="A mai elorelepes itt nem nagy dontes, hanem a kovetkezo valaszthato, kovetheto lepes kijelolese.",
        keywords=(
            "jelentkezes",
            "kepzes",
            "vizsga",
            "tanulas",
            "nyelv",
            "palyazat",
            "felvetel",
            "hatarido",
            "beadas",
            "jelentkezes",
            "kovetelmeny",
        ),
    ),
    BucketSpec(
        bucket_id="admin_legal",
        title="Jogi es szemelyes admin ugyek lezongorazasa",
        weekly_reason="A jogi es admin threadek konnyen felhalmozodnak, de nehany tiszta lepessel sok fejteret lehet visszaszerezni.",
        today_reason="Ma ezek kozul csak a tenyleg aktualis adminpontok kapjanak helyet, ne valjanak ujabb backlog-zajja.",
        keywords=(
            "jogsegely",
            "jogi",
            "hivatal",
            "tanacsado",
            "jogvita",
            "egyeztetes",
            "onkormanyzati",
            "segely",
            "bank",
            "kerel",
            "admin",
            "recept",
            "engedely",
        ),
    ),
)
BUCKET_BY_ID = {bucket.bucket_id: bucket for bucket in BUCKETS}
SECTION_WEIGHTS = {
    "Main Priorities": 4,
    "Preparation Needed": 3,
    "Carry Forward Into Next Week": 3,
    "Weekly Calibration": 2,
    "What Stayed Open": 2,
    "Mostani fokusz": 4,
    "Operativ osszkep": 2,
}
OPEN_LOOP_BAND_WEIGHTS = {
    "Kritikus / kozeljovo": 4,
    "Fontos, de nem tuz": 2,
    "Hosszuabb tavu, de aktiv": 1,
}
OPEN_LOOP_STATUS_WEIGHTS = {
    "open": 2,
    "active": 2,
    "pending": 1,
    "scheduled": 0,
    "watch": 0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--format", choices=("json", "weekly", "today", "deliverable"), default="json")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in folded if not unicodedata.combining(char))


def root_for(path: Path | None) -> Path:
    return path if path is not None else ROOT


def operational_path(root: Path, name: str) -> Path:
    return root / "Meta" / "Operational" / name


def daily_path(root: Path, target_date: date) -> Path:
    return root / "07-Daily" / f"{target_date.isoformat()}.md"


def latest_weekly_review_path(target_date: date, root: Path | None = None) -> Path | None:
    real_root = root_for(root)
    weekly_dir = real_root / "02-Areas" / "Personal" / "Stabilization"
    best: tuple[date, Path] | None = None
    for path in weekly_dir.glob("* Weekly Review.md"):
        try:
            file_date = date.fromisoformat(path.name[:10])
        except ValueError:
            continue
        if file_date > target_date:
            continue
        if best is None or file_date > best[0]:
            best = (file_date, path)
    return best[1] if best else None


def extract_sections(path: Path, section_names: tuple[str, ...]) -> dict[str, list[str]]:
    sections = {name: [] for name in section_names}
    if not path.exists():
        return sections
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        header = HEADER_RE.match(line.strip())
        if header:
            title = header.group("title").strip()
            current = title if title in sections else None
            continue
        if not current:
            continue
        bullet = BULLET_RE.match(line.strip())
        if bullet:
            sections[current].append(bullet.group("body").strip())
    return sections


def extract_task_sections(path: Path, section_names: tuple[str, ...]) -> dict[str, list[str]]:
    sections = {name: [] for name in section_names}
    if not path.exists():
        return sections
    current: str | None = None
    in_comment = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith("<!--"):
            in_comment = True
        if in_comment:
            if stripped_line.endswith("-->") or "-->" in stripped_line:
                in_comment = False
            continue
        header = HEADER_RE.match(line.strip())
        if header:
            title = header.group("title").strip()
            current = title if title in sections else None
            continue
        if not current:
            continue
        task = TASK_RE.match(line.rstrip())
        if task:
            sections[current].append(task.group("body").strip())
    return sections


def extract_temporal_sections(path: Path) -> dict[str, list[str]]:
    sections = {"Today": [], "Heads-Up": [], "Overdue": []}
    if not path.exists():
        return sections
    current: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        header = HEADER_RE.match(line.strip())
        if header and header.group("hashes") == "##":
            title = header.group("title").strip()
            current = title if title in sections else None
            continue
        if not current:
            continue
        if line.startswith("- "):
            sections[current].append(line[2:].strip())
    return sections


def parse_open_loops(path: Path) -> list[OpenLoopEntry]:
    if not path.exists():
        return []
    band = ""
    current: OpenLoopEntry | None = None
    items: list[OpenLoopEntry] = []
    collecting_sources = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        header = HEADER_RE.match(line.strip())
        if header:
            title = header.group("title").strip()
            hashes = header.group("hashes")
            if hashes == "##":
                band = title
                collecting_sources = False
            elif hashes == "###":
                if current:
                    items.append(current)
                current = OpenLoopEntry(
                    band=band,
                    title=title,
                    status="",
                    next_step="",
                    why_it_matters="",
                    source_refs=[],
                )
                collecting_sources = False
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- Status:"):
            current.status = stripped.split(":", 1)[1].strip()
            collecting_sources = False
        elif stripped.startswith("- Next step:"):
            current.next_step = stripped.split(":", 1)[1].strip()
            collecting_sources = False
        elif stripped.startswith("- Why it matters:"):
            current.why_it_matters = stripped.split(":", 1)[1].strip()
            collecting_sources = False
        elif stripped.startswith("- Source refs:"):
            collecting_sources = True
        elif collecting_sources and stripped.startswith("- [["):
            current.source_refs.append(stripped[2:].strip())
        elif stripped.startswith("- "):
            collecting_sources = False
    if current:
        items.append(current)
    return items


def signal_from_weekly_review(path: Path, root: Path | None = None) -> list[Signal]:
    real_root = root_for(root)
    section_names = (
        "Main Priorities",
        "Preparation Needed",
        "Carry Forward Into Next Week",
        "Weekly Calibration",
        "What Stayed Open",
    )
    sections = extract_sections(path, section_names)
    signals: list[Signal] = []
    for name in section_names:
        for item in sections.get(name, []):
            weight = SECTION_WEIGHTS.get(name, 1)
            signals.append(Signal(text=item, label=item, weight=weight, source_ref=f"[[{path.relative_to(real_root)}]]"))
    return signals


def signal_from_current_state(path: Path) -> list[Signal]:
    section_names = ("Mostani fokusz", "Operativ osszkep", "Watchouts")
    sections = extract_sections(path, section_names)
    signals: list[Signal] = []
    for name in ("Mostani fokusz", "Operativ osszkep"):
        for item in sections.get(name, []):
            signals.append(Signal(text=item, label=item, weight=SECTION_WEIGHTS.get(name, 1), source_ref="[[Meta/Operational/Current-State]]"))
    return signals


def signal_from_open_loops(path: Path) -> tuple[list[Signal], list[OpenLoopEntry]]:
    loops = parse_open_loops(path)
    signals: list[Signal] = []
    for entry in loops:
        base = OPEN_LOOP_BAND_WEIGHTS.get(entry.band, 1) + OPEN_LOOP_STATUS_WEIGHTS.get(entry.status.casefold(), 0)
        text = " ".join(part for part in [entry.title, entry.next_step, entry.why_it_matters] if part)
        signals.append(
            Signal(
                text=text,
                label=entry.title,
                weight=max(base, 1),
                source_ref="[[Meta/Operational/Open-Loops]]",
            )
        )
    return signals, loops


def signal_from_daily(path: Path, root: Path | None = None) -> tuple[list[Signal], list[str], list[str]]:
    real_root = root_for(root)
    sections = extract_task_sections(path, ("Tasks", "Needs Review"))
    task_signals = [
        Signal(text=item, label=item, weight=1, source_ref=f"[[{path.relative_to(real_root)}]]")
        for item in sections.get("Tasks", [])
        if "[event:" not in item
    ]
    fixed_commitments = [item.split("[event:", 1)[0].strip() for item in sections.get("Tasks", []) if "[event:" in item]
    return task_signals, fixed_commitments, sections.get("Needs Review", [])


def unwrap_link(text: str) -> str:
    return LINK_RE.sub(lambda match: match.group(1).split("|")[-1], text)


def keyword_hits(text: str, bucket: BucketSpec) -> int:
    normalized = normalize(unwrap_link(text))
    return sum(1 for keyword in bucket.keywords if keyword in normalized)


def bucket_support(signals: list[Signal]) -> dict[str, dict[str, Any]]:
    scores = {
        bucket.bucket_id: {"score": 0, "supports": [], "signals": []}
        for bucket in BUCKETS
    }
    for signal in signals:
        for bucket in BUCKETS:
            hits = keyword_hits(signal.text, bucket)
            if hits <= 0:
                continue
            scores[bucket.bucket_id]["score"] += signal.weight * hits
            scores[bucket.bucket_id]["signals"].append(signal)
            scores[bucket.bucket_id]["supports"].append(
                {
                    "label": signal.label,
                    "source_ref": signal.source_ref,
                    "weight": signal.weight * hits,
                }
            )
    for bucket_id, payload in scores.items():
        seen: set[tuple[str, str]] = set()
        deduped = []
        for item in sorted(payload["supports"], key=lambda current: current["weight"], reverse=True):
            key = (item["label"], item["source_ref"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) == 3:
                break
        payload["supports"] = deduped
    return scores


def loop_bucket_scores(entry: OpenLoopEntry) -> dict[str, int]:
    text = " ".join(part for part in [entry.title, entry.next_step, entry.why_it_matters] if part)
    return {bucket.bucket_id: keyword_hits(text, bucket) for bucket in BUCKETS}


def latest_support_ref(path: Path | None, root: Path | None = None) -> str:
    if path is None:
        return ""
    return f"[[{path.relative_to(root_for(root))}]]"


def select_weekly_axes(
    signals: list[Signal],
    loops: list[OpenLoopEntry],
    weekly_review_path: Path | None,
    root: Path | None = None,
) -> dict[str, Any]:
    support = bucket_support(signals)
    ranked = sorted(
        (
            (bucket_id, data["score"])
            for bucket_id, data in support.items()
            if data["score"] > 0
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    selected = ranked[:3]
    confidence = "watch"
    if len(selected) >= 3 and selected[0][1] >= 8:
        confidence = "high"
    elif len(selected) >= 2:
        confidence = "medium"

    axes = []
    for bucket_id, score in selected:
        spec = BUCKET_BY_ID[bucket_id]
        matching_loops = []
        for entry in loops:
            hits = loop_bucket_scores(entry).get(bucket_id, 0)
            if hits <= 0:
                continue
            priority = OPEN_LOOP_BAND_WEIGHTS.get(entry.band, 1) + OPEN_LOOP_STATUS_WEIGHTS.get(entry.status.casefold(), 0) + hits
            matching_loops.append((priority, entry))
        matching_loops.sort(key=lambda item: item[0], reverse=True)
        next_move = matching_loops[0][1].next_step if matching_loops else (support[bucket_id]["supports"][0]["label"] if support[bucket_id]["supports"] else "")
        axes.append(
            {
                "bucket_id": bucket_id,
                "title": spec.title,
                "score": score,
                "why_it_belongs": spec.weekly_reason,
                "focus_move": next_move,
                "supports": support[bucket_id]["supports"],
            }
        )

    carry_forward = extract_sections(weekly_review_path, ("Carry Forward Into Next Week",)) if weekly_review_path else {"Carry Forward Into Next Week": []}
    carry_bullets = carry_forward.get("Carry Forward Into Next Week", [])
    weekly_rule = carry_bullets[1] if len(carry_bullets) > 1 else ""
    change_to_install = carry_bullets[2] if len(carry_bullets) > 2 else ""

    return {
        "confidence": confidence,
        "axes": axes,
        "weekly_rule": weekly_rule,
        "change_to_install": change_to_install,
        "source_ref": latest_support_ref(weekly_review_path, root),
    }


def temporal_items_for_today(target_date: date, root: Path | None = None) -> dict[str, list[str]]:
    return extract_temporal_sections(operational_path(root_for(root), "Temporal-Radar.md"))


def select_today_focus(
    target_date: date,
    weekly_focus: dict[str, Any],
    loops: list[OpenLoopEntry],
    fixed_commitments: list[str],
    needs_review: list[str],
    temporal_sections: dict[str, list[str]],
) -> dict[str, Any]:
    top_bucket_ids = [axis["bucket_id"] for axis in weekly_focus["axes"]]
    strategic_candidates = []
    seen_titles: set[str] = set()
    for entry in loops:
        if entry.status.casefold() == "scheduled":
            continue
        scores = loop_bucket_scores(entry)
        top_hits = sum(scores.get(bucket_id, 0) for bucket_id in top_bucket_ids)
        if top_hits <= 0:
            continue
        priority = (
            OPEN_LOOP_BAND_WEIGHTS.get(entry.band, 1)
            + OPEN_LOOP_STATUS_WEIGHTS.get(entry.status.casefold(), 0)
            + top_hits
        )
        strategic_candidates.append((priority, entry))
    strategic_candidates.sort(key=lambda item: item[0], reverse=True)

    strategic_items = []
    for _, entry in strategic_candidates:
        if entry.title in seen_titles:
            continue
        seen_titles.add(entry.title)
        strategic_items.append(
            {
                "title": entry.title,
                "next_step": entry.next_step,
                "why_it_matters": entry.why_it_matters,
                "source_ref": "[[Meta/Operational/Open-Loops]]",
            }
        )
        if len(strategic_items) == 3:
            break

    today_items = temporal_sections.get("Today", [])
    fixed = merge_fixed_commitments(fixed_commitments, today_items) if (fixed_commitments or today_items) else []
    watch_items = []
    for item in temporal_sections.get("Heads-Up", [])[:2]:
        watch_items.append({"text": item, "source_ref": "[[Meta/Operational/Temporal-Radar]]"})
    for item in needs_review[:2]:
        watch_items.append({"text": item, "source_ref": f"[[07-Daily/{target_date.isoformat()}]]"})

    if weekly_focus["confidence"] == "watch" and not watch_items:
        watch_items.append(
            {
                "text": "A koherencia meg gyenge; ma inkabb a fix idopontok + 1 konkret lepes legyen az irany.",
                "source_ref": weekly_focus.get("source_ref", ""),
            }
        )

    if weekly_focus["axes"]:
        primary_reason = BUCKET_BY_ID[weekly_focus["axes"][0]["bucket_id"]].today_reason
    else:
        primary_reason = "A mai nap csak a fix kotottsegeket es 1-2 konkret lepest vigyen elore."

    confidence = "watch"
    if len(strategic_items) >= 3 and len(weekly_focus["axes"]) >= 2:
        confidence = "high"
    elif len(strategic_items) >= 2:
        confidence = "medium"

    return {
        "confidence": confidence,
        "fixed_commitments": fixed,
        "strategic_items": strategic_items,
        "watch_items": watch_items,
        "why_together": primary_reason,
    }


def compact_join(items: list[str]) -> str:
    clean = [item.strip() for item in items if item.strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} es {clean[1]}"
    return ", ".join(clean[:-1]) + f", es {clean[-1]}"


def dedupe_commitments(items: list[str]) -> list[str]:
    result: list[str] = []
    token_sets: list[set[str]] = []
    for item in sorted((entry.strip() for entry in items if entry.strip()), key=len, reverse=True):
        normalized = normalize(item)
        tokens = {token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) >= 3}
        if any(tokens and len(tokens & seen_tokens) >= max(2, min(len(tokens), len(seen_tokens)) // 2) for seen_tokens in token_sets):
            continue
        token_sets.append(tokens)
        result.append(item)
    return result


TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def extract_clock_time(text: str) -> str | None:
    match = TIME_RE.search(text)
    return match.group(0) if match else None


def merge_fixed_commitments(daily_fixed_commitments: list[str], temporal_items: list[str]) -> list[str]:
    daily_times = {extract_clock_time(item) for item in daily_fixed_commitments}
    merged = list(daily_fixed_commitments)
    for item in temporal_items:
        item_time = extract_clock_time(item)
        if item_time and item_time in daily_times:
            continue
        merged.append(item)
    return dedupe_commitments(merged)


def weekly_deliverable(weekly_focus: dict[str, Any]) -> str:
    titles = [axis["title"] for axis in weekly_focus["axes"]]
    if not titles:
        return "Ezen a heten nincs eleg eros koherenciajel; a fix kotelezettsegek es 1 konkret open loop kapjon elsobbseget."
    summary = compact_join(titles[:3])
    rule = weekly_focus.get("weekly_rule", "")
    if rule:
        return f"Ezen a heten a fo tengelyek: {summary}. A heti szabaly: {rule}"
    return f"Ezen a heten a fo tengelyek: {summary}."


def today_deliverable(today_focus: dict[str, Any], weekly_focus: dict[str, Any]) -> str:
    fixed = compact_join(today_focus["fixed_commitments"][:3])
    strategic = compact_join([item["title"] for item in today_focus["strategic_items"][:3]])
    if fixed and strategic:
        return f"Ma a fix kotottsegek: {fixed}. A tenyleges fokusz: {strategic}. {today_focus['why_together']}"
    if strategic:
        return f"Ma a tenyleges fokusz: {strategic}. {today_focus['why_together']}"
    if fixed:
        return f"Ma elsosorban a fix kotottsegek szamitanak: {fixed}."
    return weekly_deliverable(weekly_focus)


def collect_source_refs(
    weekly_review_path: Path | None,
    include_daily: date,
    weekly_focus: dict[str, Any],
    today_focus: dict[str, Any],
    root: Path | None = None,
) -> list[str]:
    real_root = root_for(root)
    refs = {
        "[[Meta/Operational/Current-State]]",
        "[[Meta/Operational/Open-Loops]]",
        "[[Meta/Operational/Temporal-Radar]]",
        f"[[07-Daily/{include_daily.isoformat()}]]",
    }
    if weekly_review_path:
        refs.add(f"[[{weekly_review_path.relative_to(real_root)}]]")
    for axis in weekly_focus["axes"]:
        for support in axis["supports"]:
            refs.add(support["source_ref"])
    for item in today_focus["watch_items"]:
        if item["source_ref"]:
            refs.add(item["source_ref"])
    return sorted(refs)


def build_focus_package(target_date: date, root: Path | None = None) -> dict[str, Any]:
    real_root = root_for(root)
    weekly_review_path = latest_weekly_review_path(target_date, real_root)
    weekly_signals = signal_from_weekly_review(weekly_review_path, real_root) if weekly_review_path else []
    current_state_signals = signal_from_current_state(real_root / CURRENT_STATE_PATH.relative_to(ROOT))
    loop_signals, loops = signal_from_open_loops(real_root / OPEN_LOOPS_PATH.relative_to(ROOT))
    daily_signals, fixed_commitments, needs_review = signal_from_daily(daily_path(real_root, target_date), real_root)
    temporal_sections = temporal_items_for_today(target_date, real_root)

    weekly_focus = select_weekly_axes(
        weekly_signals + current_state_signals + loop_signals + daily_signals,
        loops,
        weekly_review_path,
        real_root,
    )
    today_focus = select_today_focus(
        target_date,
        weekly_focus,
        loops,
        fixed_commitments,
        needs_review,
        temporal_sections,
    )
    source_refs = collect_source_refs(weekly_review_path, target_date, weekly_focus, today_focus, real_root)

    return {
        "date": target_date.isoformat(),
        "weekly": {
            **weekly_focus,
            "deliverable": weekly_deliverable(weekly_focus),
            "surface_path": str((real_root / WEEKLY_FOCUS_PATH.relative_to(ROOT)).relative_to(real_root)),
        },
        "today": {
            **today_focus,
            "deliverable": today_deliverable(today_focus, weekly_focus),
            "surface_path": str((real_root / TODAY_FOCUS_PATH.relative_to(ROOT)).relative_to(real_root)),
        },
        "source_refs": source_refs,
    }


def render_weekly_focus(package: dict[str, Any]) -> str:
    weekly = package["weekly"]
    lines = [
        "---",
        'type: operational-weekly-focus',
        f'date: "{package["date"]}"',
        'status: active',
        'maintained-by: coherence-compiler',
        f'focus-confidence: "{weekly["confidence"]}"',
        "---",
        "",
        "# Weekly Focus",
        "",
        "Ez egy rovid coherence surface: nem backlog, hanem a het 2-3 fo tengelye.",
        "",
        "## This Week Focus",
    ]
    if weekly["axes"]:
        for index, axis in enumerate(weekly["axes"], start=1):
            lines.extend(
                [
                    f"### {index}. {axis['title']}",
                    f"- Why it belongs: {axis['why_it_belongs']}",
                    f"- Focus move: {axis['focus_move'] or 'Meg nincs eleg konkret lepes, watch maradjon.'}",
                ]
            )
            if axis["supports"]:
                lines.append("- Supporting signals:")
                for support in axis["supports"]:
                    lines.append(f"  - {support['label']} ({support['source_ref']})")
    else:
        lines.append("- Nincs eleg eros, source-linked koherenciajel; maradjon watch-allapot.")

    lines.extend(
        [
            "",
            "## Carry-Forward Rule",
            f"- Working rule to keep: {weekly.get('weekly_rule') or 'Nincs kinyerheto heti szabaly.'}",
            f"- One change to install: {weekly.get('change_to_install') or 'Nincs tiszta heti valtoztatasi jel.'}",
            "",
            "## Deliverable",
            f"- {weekly['deliverable']}",
            "",
            "## Source refs",
        ]
    )
    for ref in package["source_refs"]:
        lines.append(f"- {ref}")
    lines.append("")
    return "\n".join(lines)


def render_today_focus(package: dict[str, Any]) -> str:
    today = package["today"]
    lines = [
        "---",
        'type: operational-today-focus',
        f'date: "{package["date"]}"',
        'status: active',
        'maintained-by: coherence-compiler',
        f'focus-confidence: "{today["confidence"]}"',
        "---",
        "",
        "# Today Focus",
        "",
        "Ez a napi coherence surface a fix idopontokat es a 2-3 tenyleges fokuszt huzza egybe.",
        "",
        "## Fixed Commitments",
    ]
    if today["fixed_commitments"]:
        for item in today["fixed_commitments"]:
            lines.append(f"- {item}")
    else:
        lines.append("- Nincs kulon fix kotottseg surfaced ma.")

    lines.extend(["", "## Strategic Focus"])
    if today["strategic_items"]:
        for item in today["strategic_items"]:
            lines.extend(
                [
                    f"### {item['title']}",
                    f"- Next step: {item['next_step'] or 'Meg nincs eleg konkret next step.'}",
                    f"- Why it matters: {item['why_it_matters'] or 'Aktiv open loop, ma is fejteret visz.'}",
                    f"- Source: {item['source_ref']}",
                ]
            )
    else:
        lines.append("- Ma nincs eleg eros strategiai szelekcio; maradjanak a fix kotottsegek + 1 konkret lepessel.")

    lines.extend(
        [
            "",
            "## Watch Items",
        ]
    )
    if today["watch_items"]:
        for item in today["watch_items"]:
            ref_suffix = f" ({item['source_ref']})" if item["source_ref"] else ""
            lines.append(f"- {item['text']}{ref_suffix}")
    else:
        lines.append("- Nincs kulon watch surfaced ma.")

    lines.extend(
        [
            "",
            "## Why These Belong Together",
            f"- {today['why_together']}",
            "",
            "## Deliverable",
            f"- {today['deliverable']}",
            "",
            "## Source refs",
        ]
    )
    for ref in package["source_refs"]:
        lines.append(f"- {ref}")
    lines.append("")
    return "\n".join(lines)


def write_if_changed(path: Path, content: str) -> str:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "updated"


def write_surfaces(package: dict[str, Any], root: Path | None = None) -> dict[str, str]:
    real_root = root_for(root)
    weekly_path = real_root / WEEKLY_FOCUS_PATH.relative_to(ROOT)
    today_path = real_root / TODAY_FOCUS_PATH.relative_to(ROOT)
    return {
        "weekly": write_if_changed(weekly_path, render_weekly_focus(package)),
        "today": write_if_changed(today_path, render_today_focus(package)),
    }


def main() -> int:
    args = parse_args()
    package = build_focus_package(args.date)
    if args.write:
        write_surfaces(package)

    if args.format == "json":
        print(json.dumps(package, ensure_ascii=False, indent=2))
    elif args.format == "weekly":
        print(render_weekly_focus(package))
    elif args.format == "today":
        print(render_today_focus(package))
    else:
        print(
            json.dumps(
                {
                    "weekly": package["weekly"]["deliverable"],
                    "today": package["today"]["deliverable"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
