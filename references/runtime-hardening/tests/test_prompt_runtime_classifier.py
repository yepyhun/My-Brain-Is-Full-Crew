from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from scripts.prompt_runtime_classifier import classify_prompt


class PromptRuntimeClassifierTests(unittest.TestCase):
    def test_mixed_hungarian_prompt_touches_daily_operational_and_temporal(self) -> None:
        payload = classify_prompt(
            "Holnap 11-re mennem kell a hivatalba, es ma milyen feladataim vannak meg?",
            date(2026, 4, 23),
        )
        self.assertEqual(payload["touches"], ["daily", "operational", "temporal"])
        self.assertTrue(payload["signals"]["temporal_language"])
        self.assertTrue(payload["signals"]["state_query"])

    def test_measurements_prompt_marks_measurements_lane(self) -> None:
        payload = classify_prompt(
            "A mai measurements hianyos? Felkeles, lefekves es alvasritmus erdekel.",
            date(2026, 4, 23),
        )
        self.assertIn("daily", payload["touches"])
        self.assertIn("measurements", payload["touches"])
        self.assertTrue(payload["signals"]["measurements_related"])


if __name__ == "__main__":
    unittest.main()
