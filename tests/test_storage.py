import json
import os
import tempfile
import unittest
from pathlib import Path

import planner
import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STUDYPILOT_DATA_DIR"] = self.tmp.name
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        os.environ.pop("STUDYPILOT_DATA_DIR", None)
        self.tmp.cleanup()

    def test_roundtrip_and_no_temp_files(self):
        tasks = planner.demo_tasks()
        storage.save_tasks(tasks)
        self.assertEqual(storage.load_tasks(), tasks)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["tasks.json"])

    def test_missing_files_give_defaults(self):
        self.assertEqual(storage.load_tasks(), [])
        self.assertEqual(storage.load_settings(), storage.DEFAULT_SETTINGS)

    def test_legacy_prototype_file_is_migrated(self):
        (self.dir / "tasks.json").write_text(json.dumps([
            {"name": "Old", "subject": "S", "due_date": "2026-01-02", "duration": 30,
             "priority": "Low", "completed": False}, "junk", {"name": ""}]), encoding="utf-8")
        tasks = storage.load_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0]["id"])
        self.assertEqual(tasks[0]["minutes_done"], 0)

    def test_corrupt_file_is_quarantined_not_fatal(self):
        (self.dir / "tasks.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(storage.load_tasks(), [])
        names = [p.name for p in self.dir.iterdir()]
        self.assertTrue(any(n.startswith("tasks.json.corrupt-") for n in names))
        (self.dir / "tasks.json").write_text('{"a": 1}', encoding="utf-8")  # wrong shape
        self.assertEqual(storage.load_tasks(), [])

    def test_settings_validated_and_clamped(self):
        (self.dir / "settings.json").write_text(json.dumps(
            {"daily_minutes": "9999", "session_len": "abc", "horizon_days": 1,
             "ai_model": 5}), encoding="utf-8")
        s = storage.load_settings()
        self.assertEqual(s["daily_minutes"], 1440)
        self.assertEqual(s["session_len"], storage.DEFAULT_SETTINGS["session_len"])
        self.assertEqual(s["horizon_days"], 3)
        self.assertEqual(s["ai_model"], "")
        storage.save_settings({**s, "daily_minutes": 90, "api_key": "SECRET"})
        raw = (self.dir / "settings.json").read_text(encoding="utf-8")
        self.assertNotIn("SECRET", raw)
        self.assertEqual(storage.load_settings()["daily_minutes"], 90)

    def test_old_settings_format(self):
        (self.dir / "settings.json").write_text('{"daily_minutes": 120}', encoding="utf-8")
        self.assertEqual(storage.load_settings()["daily_minutes"], 120)


if __name__ == "__main__":
    unittest.main()
