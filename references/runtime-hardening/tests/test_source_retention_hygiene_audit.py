from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from scripts import source_retention_hygiene_audit


class SourceRetentionHygieneAuditTests(unittest.TestCase):
    def make_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "Meta" / "health-reports").mkdir(parents=True, exist_ok=True)
        (root / "04-Archive" / "Processed-Inbox").mkdir(parents=True, exist_ok=True)
        return root

    def write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")

    def test_reports_drift_for_orphan_processed_inbox_file(self) -> None:
        root = self.make_root()
        self.write(root, "04-Archive/Processed-Inbox/example.md", "# Example")
        self.write(
            root,
            "Meta/health-reports/2026-04-22 — Inbox Triage Digest.md",
            """
            # Inbox Triage Digest — 2026-04-22
            ## Canonical Merges
            - `00-Inbox/x.md`
              - merged into [[Meta/Operational/Open-Loops]]
              - source retained at [[02-Areas/Personal/Admin/example]]
            """,
        )

        payload = source_retention_hygiene_audit.build_report(root=root)

        self.assertEqual(payload["status"], "drift")
        self.assertIn("04-Archive/Processed-Inbox/example.md", payload["orphan_processed_inbox_files"])
