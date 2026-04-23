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

from scripts import canonical_deliverable_runtime


class CanonicalDeliverableRuntimeTests(unittest.TestCase):
    def make_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "Meta" / "Operational").mkdir(parents=True, exist_ok=True)
        return root

    def write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")

    def test_today_deliverable_reads_canonical_sentence(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Today-Focus.md",
            """
            ---
            date: "2026-04-23"
            focus-confidence: "high"
            ---
            # Today Focus

            ## Deliverable
            - Ma a fix kotottsegek utan a kovetkezo konkret adminlepest kell rogzitani.
            """,
        )

        payload = canonical_deliverable_runtime.build_payload("today", date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["deliverable"], "Ma a fix kotottsegek utan a kovetkezo konkret adminlepest kell rogzitani.")

    def test_weekly_deliverable_watch_confidence_stays_servable(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Weekly-Focus.md",
            """
            ---
            date: "2026-04-23"
            focus-confidence: "watch"
            ---
            # Weekly Focus

            ## Deliverable
            - Ezen a heten a stabilizalas az elso tengely.
            """,
        )

        payload = canonical_deliverable_runtime.build_payload("weekly", date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "watch")
        self.assertEqual(payload["deliverable"], "Ezen a heten a stabilizalas az elso tengely.")

    def test_measurements_suppressed_has_no_deliverable(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Measurements-Radar.md",
            """
            ---
            date: "2026-04-23"
            status: "suppressed"
            ---
            # Measurements Radar - 2026-04-23

            ## Prompt
            Nincs most user-facing measurements prompt.
            """,
        )

        payload = canonical_deliverable_runtime.build_payload("measurements", date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "suppressed")
        self.assertEqual(payload["deliverable"], "")

    def test_measurements_prompt_exposes_exact_prompt(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Measurements-Radar.md",
            """
            ---
            date: "2026-04-23"
            status: "prompt"
            ---
            # Measurements Radar - 2026-04-23

            ## Prompt
            Mikor keltel ma, es kb. mikor fogsz lefekudni?
            """,
        )

        payload = canonical_deliverable_runtime.build_payload("measurements", date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "prompt")
        self.assertEqual(payload["deliverable"], "Mikor keltel ma, es kb. mikor fogsz lefekudni?")

    def test_future_reminders_heads_up_uses_temporal_radar(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Temporal-Radar.md",
            """
            ---
            date: "2026-04-23"
            status: "active"
            ---
            # Temporal Radar — 2026-04-23

            ## Heads-Up
            - 2026-04-24 10:00 Valami fontos (appointment)

            ## Upcoming (7 days)
            - 2026-04-28 Masik dolog
            """,
        )

        payload = canonical_deliverable_runtime.build_payload("future-reminders", date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "ok")
        self.assertIn("Kozelgo emlekeztetok", payload["deliverable"])
        self.assertIn("Utana ez jon", payload["deliverable"])


if __name__ == "__main__":
    unittest.main()
