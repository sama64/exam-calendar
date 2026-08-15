import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class RolloverTests(unittest.TestCase):
    def test_active_roster_comes_from_academic_state(self):
        state = {
            "subjects": [
                {
                    "code": "0_020",
                    "name": "Calculo I",
                    "status": "in_course",
                    "events": [{"type": "En curso", "academic_period": "2026-2C"}],
                },
                {
                    "code": "0_028",
                    "name": "Mecanica de los Materiales",
                    "status": "in_course",
                    "events": [{"type": "En curso", "academic_period": "2026-2C"}],
                },
                {
                    "code": "0_029",
                    "name": "Ciencia y Tecnologia de los Materiales",
                    "status": "regularized_final_pending",
                    "events": [{"type": "En curso", "academic_period": "2026-1C"}],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "academic-state.yaml"
            import yaml

            path.write_text(yaml.safe_dump(state), encoding="utf-8")
            with patch.object(server, "ACADEMIC_STATE_PATH", path):
                period, subjects = server.active_academic_subjects()
        self.assertEqual(period, "2026-2C")
        self.assertEqual([item["key"] for item in subjects], ["calc", "mec"])

    def test_current_period_moodle_shell_beats_archived_shell(self):
        subjects = [
            {
                "key": "calc",
                "moodleAliases": ["calculo i"],
            }
        ]
        courses = [
            {"id": 99, "display_name": "Cálculo I - 1er Cuat. de 2026"},
            {"id": 7, "display_name": "Cálculo I - Turno Tarde - 2do Cuat. de 2026"},
        ]
        mapping = server.discover_courses(courses, subjects, "2026-2C")
        self.assertEqual(mapping, {"calc": 7})

    def test_old_period_overrides_are_inert(self):
        event = {"id": "event-1", "subject": "calc", "status": "confirmed"}
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / "manual-overrides.json").write_text(
                json.dumps(
                    {
                        "academicPeriod": "2026-1C",
                        "ignoredSubjects": ["calc"],
                        "overrides": [],
                        "extraEvents": [],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(server, "CONFIG_DIR", config):
                result = server.apply_manual_overrides([event], "2026-2C")
        self.assertEqual(result, [event])


if __name__ == "__main__":
    unittest.main()
