from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from scripts import obligation_continuity_guard


class ObligationContinuityGuardTests(unittest.TestCase):
    def make_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "07-Daily").mkdir(parents=True, exist_ok=True)
        (root / "Meta" / "Operational").mkdir(parents=True, exist_ok=True)
        (root / "Meta" / "Temporal" / "Events").mkdir(parents=True, exist_ok=True)
        return root

    def write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")

    def patch_root(self, root: Path) -> None:
        patches = [
            mock.patch.object(obligation_continuity_guard, "ROOT", root),
            mock.patch.object(obligation_continuity_guard, "DAILY_DIR", root / "07-Daily"),
            mock.patch.object(obligation_continuity_guard, "TEMPORAL_RADAR", root / "Meta" / "Operational" / "Temporal-Radar.md"),
            mock.patch.object(obligation_continuity_guard, "OPEN_LOOPS", root / "Meta" / "Operational" / "Open-Loops.md"),
            mock.patch.object(obligation_continuity_guard, "CURRENT_STATE", root / "Meta" / "Operational" / "Current-State.md"),
            mock.patch.object(obligation_continuity_guard, "TODAY_FOCUS", root / "Meta" / "Operational" / "Today-Focus.md"),
            mock.patch.object(obligation_continuity_guard, "WEEKLY_FOCUS", root / "Meta" / "Operational" / "Weekly-Focus.md"),
            mock.patch.object(obligation_continuity_guard, "COMPILE_STATUS", root / "Meta" / "Operational" / "Compile-Status.md"),
            mock.patch.object(obligation_continuity_guard.temporal_radar, "ROOT", root),
            mock.patch.object(obligation_continuity_guard.temporal_radar, "EVENTS_DIR", root / "Meta" / "Temporal" / "Events"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_current_state_report_respects_temporal_and_focus_coverage(self) -> None:
        root = self.make_root()
        self.patch_root(root)
        self.write(
            root,
            "Meta/Operational/Compile-Status.md",
            """
            ---
            type: operational-compile-status
            date: "2026-04-23"
            status: active
            maintained-by: curator
            last-full-compile: "2026-04-23"
            ---
            """,
        )
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            ## Kritikus / kozeljovo

            ### Engedely megujitas ugye
            - Next step: 2026-07-14-en lehet ujra beadni a megujitasi kerelmet; addig ezt a temporal radar hozza vissza.

            ### Jogvita kovetkezo lepese
            - Next step: a tanacsado irodanak irni vagy telefonalni a jogvita ugyeben; jelenlegi kontakt: `contact@example.org`
            """,
        )
        self.write(
            root,
            "Meta/Operational/Current-State.md",
            """
            ## Mostani fokusz
            - Emailben tisztazni a kepzesi hataridot es a kovetkezmenyeket.
            """,
        )
        self.write(
            root,
            "07-Daily/2026-04-23.md",
            """
            ## Tasks
            - [ ] Emailben tisztazni a kepzesi hataridot es a kovetkezmenyeket.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Today-Focus.md",
            """
            # Today Focus

            ## Fixed Commitments
            - Tanacsado iroda 13:00 korul a jogvita miatt.

            ## Deliverable
            - Ma a jogvita es a kepzesi teendo is surfaced.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Weekly-Focus.md",
            """
            # Weekly Focus

            ## This Week Focus
            ### Kepzesi hatarido es tanulasi rendszer

            ## Deliverable
            - Ezen a heten a kepzesi hatarido is fokuszban van.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Temporal-Radar.md",
            """
            # Temporal Radar - 2026-04-23

            ## Today
            - 13:00 Tanacsado iroda (admin)
            """,
        )
        self.write(
            root,
            "Meta/Temporal/Events/2026-04-23 Tanacsado iroda 1300.md",
            """
            ---
            type: temporal-event
            status: active
            event-date: "2026-04-23"
            event-time: "13:00"
            ---

            # Tanacsado iroda
            """,
        )
        self.write(
            root,
            "Meta/Temporal/Events/2026-07-14 Engedely megujitasa.md",
            """
            ---
            type: temporal-event
            status: active
            event-date: "2026-07-14"
            remind-days-before: [7]
            ---

            # Engedely megujitasa
            """,
        )

        payload = obligation_continuity_guard.current_state_report(date(2026, 4, 23))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["unsurfaced_obligations"], [])
        candidate_texts = [item["text"] for item in payload["candidate_obligations"]]
        self.assertNotIn("jelenlegi kontakt: contact@example.org", candidate_texts)

    def test_low_severity_background_backlog_does_not_raise_watch(self) -> None:
        root = self.make_root()
        self.patch_root(root)
        self.write(
            root,
            "Meta/Operational/Compile-Status.md",
            """
            ---
            type: operational-compile-status
            date: "2026-04-23"
            status: active
            maintained-by: curator
            last-full-compile: "2026-04-23"
            ---
            """,
        )
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            ## Fontos, de nem tuz

            ### Banki kerelmi igeny
            - Next step: a banknak eljuttatni a kerelmet az egyszeri ingyenes keszpenzfelvetelhez.
            """,
        )
        self.write(root, "Meta/Operational/Current-State.md", "## Mostani fokusz\n- Semmi surgos nincs itt.\n")
        self.write(root, "Meta/Operational/Temporal-Radar.md", "# Temporal Radar\n\n## Today\n- Nincs\n")
        self.write(root, "07-Daily/2026-04-23.md", "## Tasks\n")
        self.write(root, "Meta/Operational/Today-Focus.md", "# Today Focus\n\n## Deliverable\n- Nincs kulon napi fokusz.\n")
        self.write(root, "Meta/Operational/Weekly-Focus.md", "# Weekly Focus\n\n## Deliverable\n- Hatter-backlog maradhat hatterben.\n")

        payload = obligation_continuity_guard.current_state_report(date(2026, 4, 23))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(payload["high_signal_unsurfaced"]), 0)
        self.assertTrue(
            all(item["severity"] == "low" for item in payload["unsurfaced_obligations"]),
            payload["unsurfaced_obligations"],
        )


if __name__ == "__main__":
    unittest.main()
