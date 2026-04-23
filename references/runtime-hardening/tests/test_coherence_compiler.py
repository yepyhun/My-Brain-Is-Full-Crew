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

from scripts import coherence_compiler


class CoherenceCompilerTests(unittest.TestCase):
    def make_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "Meta" / "Operational").mkdir(parents=True, exist_ok=True)
        (root / "02-Areas" / "Personal" / "Stabilization").mkdir(parents=True, exist_ok=True)
        (root / "07-Daily").mkdir(parents=True, exist_ok=True)
        return root

    def write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")

    def test_build_focus_package_from_grounded_inputs(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "02-Areas/Personal/Stabilization/2026-04-21 Weekly Review.md",
            """
            # Weekly Review
            ## Main Priorities
            - Szemelyes ugy: vizsgalat, idopont, kedvezmeny es email konkret lepese.
            - Jelentkezesi es kepzesi hataridok konkretizalasa.
            - A rendszer tenyleges hasznalata.
            ## Preparation Needed
            - A szemelyes ugy kovetkezo adminlepese.
            - Jogvita miatt tanacsadast kerni.
            ## Carry Forward Into Next Week
            - Rhythm to preserve: kezdeményezés.
            - Working rule to keep: a konkret lepest ki kell venni a fejbol.
            - One change to install next week: a rendszer tenyleges hasznalata.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Current-State.md",
            """
            # Current State
            ## Operativ osszkep
            - A stabilizalas az elso.
            ## Mostani fokusz
            - Szemelyes ugy kovetese: vizsgalat, egyeztetes es email.
            - A jelentkezesi folyamat konkretizalasa.
            - A nap leszukitese minimum mukodesre.
            """,
        )
        self.write(
            root,
            "Meta/Operational/Open-Loops.md",
            """
            # Open Loops
            ## Kritikus / kozeljovo
            ### Szemelyes ugy kovetkezo konkret adminlepesei
            - Status: open
            - Next step: vizsgalat / email kovetkezo lepesse huzasa.
            - Why it matters: konkret adminteher.
            - Source refs:
              - [[02-Areas/Personal/Stabilization/2026-04-21 Weekly Review]]
            ### Jelentkezesi folyamat konkretumainak kibontasa
            - Status: active
            - Next step: kepzesi / vizsga tracked lepesei.
            - Why it matters: a 30 napos fokusz egyik fo tengelye.
            - Source refs:
              - [[02-Areas/Personal/Stabilization/2026-04-21 Weekly Review]]
            ## Fontos, de nem tuz
            ### Jogvita miatti tanacsadas
            - Status: open
            - Next step: a tanacsado irodanak irni.
            - Why it matters: konkret nyitott jogi ugy.
            - Source refs:
              - [[02-Areas/Personal/Stabilization/2026-04-21 Weekly Review]]
            ### Eletrendszer kidolgozasa
            - Status: active
            - Next step: egyszeru napirendszer kitalalasa.
            - Why it matters: stabilizacios alap.
            - Source refs:
              - [[02-Areas/Personal/Stabilization/2026-04-21 Weekly Review]]
            """,
        )
        self.write(
            root,
            "Meta/Operational/Temporal-Radar.md",
            """
            # Temporal Radar
            ## Today
            - 2026-04-23 09:30 Masszazs
            - 2026-04-23 11:00 Csomag atvetele
            ## Heads-Up
            - Nem mai feladat, de holnap: 2026-04-24 valami
            """,
        )
        self.write(
            root,
            "07-Daily/2026-04-23.md",
            """
            # 2026-04-23
            ## Tasks
            - [ ] Masszazs 09:30 [event:2026-04-23 09:30]
            - [ ] Szemelyes ugy kovetkezo konkret lepese.
            - [ ] Emailben tisztazni a kepzesi hataridot.
            ## Needs Review
            - [ ] Regi bizonytalan task.
            """,
        )

        package = coherence_compiler.build_focus_package(date(2026, 4, 23), root)

        self.assertEqual(package["weekly"]["confidence"], "high")
        self.assertEqual(package["today"]["confidence"], "high")
        weekly_titles = [axis["title"] for axis in package["weekly"]["axes"]]
        self.assertIn("Szemelyes ugy es a kapcsolodo konkret adminnyomas", weekly_titles)
        self.assertIn("Jelentkezesi es kepzesi konkretizalas", weekly_titles)
        today_titles = [item["title"] for item in package["today"]["strategic_items"]]
        self.assertIn("Szemelyes ugy kovetkezo konkret adminlepesei", today_titles)
        self.assertIn("Jelentkezesi folyamat konkretumainak kibontasa", today_titles)

        writes = coherence_compiler.write_surfaces(package, root)
        self.assertEqual(writes, {"weekly": "updated", "today": "updated"})
        second_writes = coherence_compiler.write_surfaces(package, root)
        self.assertEqual(second_writes, {"weekly": "unchanged", "today": "unchanged"})

    def test_build_focus_package_prefers_daily_fixed_commitment_when_time_matches_temporal(self) -> None:
        root = self.make_root()
        self.write(root, "Meta/Operational/Current-State.md", "# Current State\n## Mostani fokusz\n- Masszazs utan admin.\n")
        self.write(root, "Meta/Operational/Open-Loops.md", "# Open Loops\n")
        self.write(root, "Meta/Operational/Temporal-Radar.md", "# Temporal Radar\n## Today\n- 09:30 Masszazs (appointment)\n- 11:00 Csomag atvetele (pickup)\n")
        self.write(root, "07-Daily/2026-04-23.md", "# 2026-04-23\n## Tasks\n- [ ] Masszazs 09:30 [event:2026-04-23 09:30]\n- [ ] Csomag atvetele 11:00 [event:2026-04-23 11:00]\n")

        package = coherence_compiler.build_focus_package(date(2026, 4, 23), root)

        self.assertCountEqual(package["today"]["fixed_commitments"], ["Masszazs 09:30", "Csomag atvetele 11:00"])

    def test_build_focus_package_downgrades_sparse_signals(self) -> None:
        root = self.make_root()
        self.write(
            root,
            "Meta/Operational/Current-State.md",
            """
            # Current State
            ## Operativ osszkep
            - Csendes nap.
            ## Mostani fokusz
            - Egyetlen apro task.
            """,
        )
        self.write(root, "Meta/Operational/Open-Loops.md", "# Open Loops\n")
        self.write(root, "Meta/Operational/Temporal-Radar.md", "# Temporal Radar\n## Today\n")
        self.write(
            root,
            "07-Daily/2026-04-23.md",
            """
            # 2026-04-23
            ## Tasks
            - [ ] Apro task
            """,
        )

        package = coherence_compiler.build_focus_package(date(2026, 4, 23), root)

        self.assertEqual(package["weekly"]["confidence"], "watch")
        self.assertEqual(package["today"]["confidence"], "watch")
        self.assertIn("nincs eleg eros", coherence_compiler.render_weekly_focus(package).casefold())


if __name__ == "__main__":
    unittest.main()
