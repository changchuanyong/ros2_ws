from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reproduce import check_result, main, read_json


class TrainingSourceLayoutTest(unittest.TestCase):
    def test_default_training_sources_work_without_neighboring_checkouts(self):
        lock = read_json(Path(__file__).with_name("sources.json"))
        lock["robopianist"]["files"] = {}
        with (
            TemporaryDirectory() as neighbors,
            patch("reproduce.CODE", Path(neighbors)),
            patch("reproduce.read_json", return_value=lock),
            patch.object(sys, "argv", ["reproduce.py", "check-sources"]),
            redirect_stdout(StringIO()) as output,
        ):
            main()
        self.assertEqual(output.getvalue().strip(), "Source locks verified")


class BaselineResultTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.run_dir = Path(directory.name)
        self.evaluation = self.run_dir / "reloaded_seed202"
        self.evaluation.mkdir()
        self.result = {
            "termination_reason": "score_complete",
            "executed_steps": 26,
            "score_steps": 26,
            "f1": 1.0,
            "onset_recall": 1.0,
            "missed_notes": 0,
            "false_positive_key_frames": 0,
            "collision_frames": 0,
            "joint_limit_frames": 0,
            "notes": [{"pitch": 72, "start": .5, "end": .75}],
        }
        self.events = [
            {"type": "NoteOn", "note": 72, "time": .512},
            {"type": "NoteOff", "note": 72, "time": .813},
        ]
        self.write("evaluation.json", self.result)
        self.write("midi_events.json", self.events)
        self.write("reload_check.json", {"deterministic_actions_equal": True, "max_abs_error": 0})
        (self.run_dir / "training_summary.json").write_text(json.dumps({
            "steps": 20_000, "updates": 19_500, "physics_invalid_steps": 0,
            "initial_actor_sha256": "initial", "final_actor_sha256": "updated",
        }), encoding="utf-8")

    def write(self, name, data):
        (self.evaluation / name).write_text(json.dumps(data), encoding="utf-8")

    def test_passes_with_measured_press_and_release(self):
        result = check_result(self.run_dir, self.evaluation)
        self.assertEqual(result["onset_ms"], 12.0)
        self.assertEqual(result["release_ms"], 63.0)

    def test_rejects_missing_release_even_with_perfect_frame_f1(self):
        self.write("midi_events.json", self.events[:1])
        with self.assertRaisesRegex(ValueError, "press and release"):
            check_result(self.run_dir, self.evaluation)

    def test_rejects_late_release(self):
        self.events[1]["time"] = .826
        self.write("midi_events.json", self.events)
        with self.assertRaisesRegex(ValueError, "timing"):
            check_result(self.run_dir, self.evaluation)

    def test_rejects_collision_and_reload_mismatch(self):
        self.result["collision_frames"] = 1
        self.write("evaluation.json", self.result)
        with self.assertRaisesRegex(ValueError, "performance gate"):
            check_result(self.run_dir, self.evaluation)
        self.write("reload_check.json", {"deterministic_actions_equal": False, "max_abs_error": .01})
        with self.assertRaisesRegex(ValueError, "differ after checkpoint reload"):
            check_result(self.run_dir, self.evaluation)
