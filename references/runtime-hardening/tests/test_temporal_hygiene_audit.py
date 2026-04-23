from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from scripts import temporal_hygiene_audit


class TemporalHygieneAuditTests(unittest.TestCase):
    def make_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "Meta" / "Temporal" / "Events").mkdir(parents=True, exist_ok=True)
        (root / "Meta" / "Operational").mkdir(parents=True, exist_ok=True)
        return root

    def write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")

    def test_stale_event_with_followup_open_loop_gets_cancel_suggestion(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Temporal/Events/2026-04-15 Beszallito hivas 1430.md",
            """
            ---
            type: temporal-event
            date: "2026-04-15"
            status: active
            event-date: "2026-04-15"
            event-time: "14:30"
            timezone: "Europe/Budapest"
            kind: call
            related-note: "[[02-Areas/Personal/Admin/2026-04-15 Beszallito idopontegyeztetes]]"
            ---

            # Beszallito hivas
            """,
        )
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            # Open Loops
            ### Beszallito idopontegyeztetes
            - Next step: ujra felhivni a beszallitot, mert az elso kapcsolatfelvetel nem ment at.
            """,
        )

        payload = temporal_hygiene_audit.build_report(date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "drift")
        self.assertEqual(payload["stale_events"][0]["suggested_status"], "cancelled")
        self.assertEqual(payload["stale_events"][0]["confidence"], "high")
