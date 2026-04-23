#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "Meta" / "states" / "codex-hook-runtime.json"
MAX_PENDING_TURNS = 48


def default_state() -> dict[str, Any]:
    return {
        "last_session_start": {},
        "pending_turns": {},
    }


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return default_state()
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    if not isinstance(payload, dict):
        return default_state()
    payload.setdefault("last_session_start", {})
    payload.setdefault("pending_turns", {})
    if not isinstance(payload["pending_turns"], dict):
        payload["pending_turns"] = {}
    return payload


def save_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(STATE_PATH)


def prune_pending_turns(payload: dict[str, Any]) -> None:
    pending = payload.get("pending_turns", {})
    if not isinstance(pending, dict) or len(pending) <= MAX_PENDING_TURNS:
        return
    items = sorted(
        pending.items(),
        key=lambda item: str(item[1].get("captured_at", "")),
    )
    trimmed = dict(items[-MAX_PENDING_TURNS:])
    payload["pending_turns"] = trimmed


def record_session_start(session_id: str, source: str, cwd: str) -> None:
    payload = load_state()
    payload["last_session_start"] = {
        "session_id": session_id,
        "source": source,
        "cwd": cwd,
        "recorded_at": utc_now_iso(),
    }
    save_state(payload)


def record_prompt_classification(
    turn_id: str,
    session_id: str,
    prompt_preview: str,
    classification: dict[str, Any],
) -> None:
    payload = load_state()
    payload["pending_turns"][turn_id] = {
        "session_id": session_id,
        "prompt_preview": prompt_preview,
        "classification": classification,
        "captured_at": utc_now_iso(),
    }
    prune_pending_turns(payload)
    save_state(payload)


def consume_prompt_classification(turn_id: str) -> dict[str, Any] | None:
    payload = load_state()
    pending = payload.get("pending_turns", {})
    if not isinstance(pending, dict):
        return None
    item = pending.pop(turn_id, None)
    save_state(payload)
    if not isinstance(item, dict):
        return None
    return item
