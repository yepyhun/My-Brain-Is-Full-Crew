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

from scripts import runtime_hygiene_audit


class RuntimeHygieneAuditTests(unittest.TestCase):
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
        path.write_text(content.strip() + "\n", encoding="utf-8")

    def test_reports_coverage_gap_for_unsurfaced_critical_loop(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            # Open Loops
            ## Kritikus / kozeljovo
            ### Szemelyes ugy kovetkezo konkret adminlepesei
            - Status: open
            - Next step: vizsgalat lepest rogzitni.
            - Why it matters: konkret nyitott ugy.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Today-Focus.md",
            """
            ---
            date: "2026-04-23"
            focus-confidence: "medium"
            ---
            # Today Focus
            ## Strategic Focus
            ### Valami teljesen mas
            """,
        )
        self.write(
            root,
            "Meta/Operational/Weekly-Focus.md",
            """
            ---
            date: "2026-04-23"
            focus-confidence: "medium"
            ---
            # Weekly Focus
            ## This Week Focus
            ### 1. Masik tengely
            """,
        )

        payload = runtime_hygiene_audit.build_report(date(2026, 4, 23), root=root)

        self.assertIn(payload["status"], {"watch", "drift"})
        self.assertIn("Szemelyes ugy kovetkezo konkret adminlepesei", payload["critical_loop_coverage_gaps"])

    def test_reports_deliverable_issue_when_focus_surface_has_no_deliverable(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            # Open Loops
            ## Kritikus / kozeljovo
            ### Szemelyes ugy kovetkezo konkret adminlepesei
            - Status: open
            - Next step: vizsgalat lepest rogzitni.
            - Why it matters: konkret nyitott ugy.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Today-Focus.md",
            """
            ---
            date: "2026-04-23"
            focus-confidence: "high"
            ---
            # Today Focus

            ## Strategic Focus
            ### Szemelyes ugy kovetkezo konkret adminlepesei
            - Next step: vizsgalat lepest rogzitni.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Weekly-Focus.md",
            """
            ---
            date: "2026-04-23"
            focus-confidence: "high"
            ---
            # Weekly Focus

            ## Deliverable
            - Ezen a heten a szemelyes ugy fontos tengely.
            """,
        )

        payload = runtime_hygiene_audit.build_report(date(2026, 4, 23), root=root)

        self.assertEqual(payload["status"], "drift")
        self.assertTrue(any("Today-Focus deliverable issue" in item for item in payload["deliverable_issues"]))


if __name__ == "__main__":
    unittest.main()
