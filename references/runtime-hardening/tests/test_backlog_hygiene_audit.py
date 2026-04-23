from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from scripts import backlog_hygiene_audit


class BacklogHygieneAuditTests(unittest.TestCase):
    def make_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "Meta" / "Operational").mkdir(parents=True, exist_ok=True)
        (root / "Meta" / "Temporal" / "Events").mkdir(parents=True, exist_ok=True)
        return root

    def write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")

    def test_reports_temporal_gap_and_source_thin_review_now_items(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            ## Fontos, de nem tuz

            ### Licenc megujitasa
            - Status: open
            - Next step: 2026-07-14-en lehet ujra beadni a megujitasi kerelmet.
            - Source refs:
              - [[02-Areas/Personal/Admin/2026-04-14 Engedely]]

            ### Tema utanajarasa
            - Status: open
            - Next step: utana keresni, hogy a tema milyen gyakorlati jelentoseggel bir.
            - Source refs:
              - [[Meta/Operational/Open-Loops]]
            """,
        )

        payload = backlog_hygiene_audit.build_report(date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "watch")
        reasons = {item["title"]: item["reason"] for item in payload["review_now"]}
        self.assertEqual(reasons["Licenc megujitasa"], "temporal_promotion_gap")
        self.assertEqual(reasons["Tema utanajarasa"], "source_thin_background_loop")

    def test_reports_stale_and_temporal_covered_separately(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            ## Fontos, de nem tuz

            ### Regi banki kerelem
            - Status: open
            - Next step: a banknak eljuttatni a kerelmet az egyszeri ingyenes keszpenzfelvetelhez.
            - Source refs:
              - [[02-Areas/Personal/Admin/2026-03-01 Bank kerelem]]

            ### Masszazs idopont
            - Status: scheduled
            - Next step: a kovetkezo fix temporal tetel a 2026-04-23 09:30-as masszazs.
            - Source refs:
              - [[02-Areas/Personal/Admin/2026-04-15 Masszazs idopontegyeztetes]]
            """,
        )
        self.write(
            root,
            "Meta/Temporal/Events/2026-04-23 Masszazs 0930.md",
            """
            ---
            type: temporal-event
            status: active
            event-date: "2026-04-23"
            event-time: "09:30"
            ---

            # Masszazs
            """,
        )

        payload = backlog_hygiene_audit.build_report(date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "watch")
        self.assertTrue(any(item["title"] == "Regi banki kerelem" and item["reason"] == "stale_background_loop" for item in payload["review_now"]))
        self.assertTrue(any(item["title"] == "Masszazs idopont" and item["reason"] == "covered_by_active_temporal_event" for item in payload["temporal_covered"]))

    def test_aging_item_stays_out_of_review_now(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            ## Fontos, de nem tuz

            ### Kozepesen regi szal
            - Status: open
            - Next step: a kovetkezo lepest tisztazni kell.
            - Source refs:
              - [[02-Areas/Personal/Admin/2026-04-05 Valami]]
            """,
        )

        payload = backlog_hygiene_audit.build_report(date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(payload["review_now"]), 0)
        self.assertEqual(len(payload["aging"]), 1)
        self.assertEqual(payload["aging"][0]["title"], "Kozepesen regi szal")


if __name__ == "__main__":
    unittest.main()
