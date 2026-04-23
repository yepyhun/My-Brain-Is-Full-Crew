from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from scripts import post_turn_orchestrator


class PostTurnOrchestratorTests(unittest.TestCase):
    def test_prompt_is_informational_not_overall_failure(self) -> None:
        actions = [
            {"name": "measurements_radar", "status": "prompt"},
            {"name": "current_state_continuity", "status": "ok"},
            {"name": "operational_drift", "status": "ok"},
        ]

        self.assertEqual(post_turn_orchestrator.overall_status(actions), "ok")

    def test_watch_still_outranks_ok(self) -> None:
        actions = [
            {"name": "measurements_radar", "status": "prompt"},
            {"name": "source_retention_hygiene_audit", "status": "watch"},
        ]

        self.assertEqual(post_turn_orchestrator.overall_status(actions), "watch")


if __name__ == "__main__":
    unittest.main()
