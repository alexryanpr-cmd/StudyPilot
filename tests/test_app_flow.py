"""End-to-end flows of app.py executed against the fake Streamlit harness."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import ai_coach
import planner
from tests.fake_streamlit import AppRunner

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STUDYPILOT_DATA_DIR"] = self.tmp.name
        os.environ.pop("STUDYPILOT_AI_API_KEY", None)
        os.environ.pop("NEBIUS_API_KEY", None)
        self.dir = Path(self.tmp.name)
        self.app = AppRunner(APP).run()

    def tearDown(self):
        os.environ.pop("STUDYPILOT_DATA_DIR", None)
        sys.modules.pop("streamlit", None)
        self.tmp.cleanup()

    def stored(self):
        return json.loads((self.dir / "tasks.json").read_text(encoding="utf-8"))

    def add(self, name="Report", subject="Bio", due=None, minutes=60, prio="Medium"):
        self.app.set_many({"new_name": name, "new_subject": subject,
                           "new_due": due or date.today() + timedelta(days=3),
                           "new_duration": minutes, "new_priority": prio})
        return self.app.press("assignment_form:Add assignment")

    # ------------------------------------------------------------------ #
    def test_first_run_empty_state(self):
        self.assertTrue(self.app.has_text("StudyPilot"))
        self.assertTrue(self.app.has_text("No assignments yet", "info"))
        self.assertTrue(self.app.has_text("Add your first assignment", "info"))
        self.assertIn("load_demo", self.app.st.registered)

    def test_demo_data_renders_every_tab(self):
        self.app.press("load_demo")
        self.assertEqual(len(self.app.tasks), 6)
        self.assertTrue(self.app.has_text("Demo data loaded", "info"))
        self.assertTrue(self.app.has_text("overdue", "error"))        # coach alert
        self.assertTrue(self.app.has_text("Showing 6 of 6"))
        self.assertTrue(any(k.startswith("plan_") for k in self.app.st.registered))
        self.assertEqual(len(self.stored()), 6)
        self.assertNotIn("load_demo", self.app.st.registered)         # only on empty

    def test_add_validation_and_duplicates(self):
        self.add(name="  ", subject="Bio")
        self.assertTrue(self.app.has_text("enter both", "warning"))
        self.assertEqual(self.app.tasks, [])
        self.add()
        self.assertEqual(len(self.app.tasks), 1)
        self.assertTrue(self.app.has_text("Added", "success"))
        self.assertEqual(self.app.st.session_state.new_name, "")      # form cleared on success
        self.add()                                                    # same name/course/due
        self.assertEqual(len(self.app.tasks), 1)
        self.assertTrue(self.app.has_text("already exists", "warning"))
        self.add(name="Old", due=date.today() - timedelta(days=2))
        self.assertTrue(self.app.has_text("in the past", "warning"))
        self.assertEqual(len(self.stored()), 2)

    def test_log_complete_reopen_delete_edit(self):
        self.add(minutes=60)
        tid = self.app.tasks[0]["id"]
        self.app.press(f"l30_{tid}")
        self.assertEqual(self.app.tasks[0]["minutes_done"], 30)
        self.assertEqual(self.stored()[0]["minutes_done"], 30)
        self.app.press(f"l30_{tid}")                                   # reaches 60 -> auto-complete
        self.assertTrue(self.app.tasks[0]["completed"])
        self.assertTrue(self.app.has_text("is complete", "success"))
        self.app.press(f"reopen_{tid}")
        self.assertFalse(self.app.tasks[0]["completed"])
        # two-step complete confirmation
        self.app.press(f"done_{tid}")
        self.assertTrue(self.app.has_text("Mark this assignment", "warning"))
        self.app.press(f"cancel_{tid}")
        self.assertFalse(self.app.tasks[0]["completed"])
        self.app.press(f"done_{tid}")
        self.app.press(f"confirm_{tid}")
        self.assertTrue(self.app.tasks[0]["completed"])
        self.app.press(f"reopen_{tid}")
        # edit
        self.app.set_many({f"e_name_{tid}": "Renamed", f"e_duration_{tid}": 90,
                           f"e_priority_{tid}": "High", f"e_subject_{tid}": "Chem"})
        self.app.press(f"edit_form_{tid}:Save changes")
        self.assertEqual((self.app.tasks[0]["name"], self.app.tasks[0]["duration"],
                          self.app.tasks[0]["priority"]), ("Renamed", 90, "High"))
        self.app.set_many({f"e_name_{tid}": " "})
        self.app.press(f"edit_form_{tid}:Save changes")
        self.assertEqual(self.app.tasks[0]["name"], "Renamed")        # empty name rejected
        self.assertTrue(self.app.has_text("can't be empty", "warning"))
        # delete with confirmation
        self.app.press(f"del_{tid}")
        self.assertTrue(self.app.has_text("Delete this assignment", "error"))
        self.app.press(f"del_no_{tid}")
        self.assertEqual(len(self.app.tasks), 1)
        self.app.press(f"del_{tid}")
        self.app.press(f"del_yes_{tid}")
        self.assertEqual(self.app.tasks, [])
        self.assertEqual(self.stored(), [])

    def test_filters_and_stale_filter_value(self):
        self.app.press("load_demo")
        self.app.set("flt_query", "calculus")
        self.assertTrue(self.app.has_text("Showing 1 of 6"))
        self.app.set("flt_query", "zzz")
        self.assertTrue(self.app.has_text("No assignments match", "info"))
        self.app.set("flt_query", "")
        self.app.set("flt_subject", "Chemistry")
        chem = next(t for t in self.app.tasks if t["subject"] == "Chemistry")
        self.app.press(f"del_{chem['id']}")
        self.app.press(f"del_yes_{chem['id']}")                        # selected course vanished
        self.assertEqual(self.app.st.session_state.flt_subject, "All")
        for sort in planner.SORT_OPTIONS:
            self.app.set("flt_sort", sort)
        self.app.set("flt_status", "Completed")
        self.assertTrue(self.app.has_text("Showing 0 of 5"))

    def test_settings_persist_and_cap_the_plan(self):
        self.app.press("load_demo")
        self.app.set("daily_minutes", 45)
        saved = json.loads((self.dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["daily_minutes"], 45)
        self.assertNotIn("ai_api_key", saved)
        fresh = AppRunner(APP).run()                                   # new browser session
        self.assertEqual(fresh.st.session_state.daily_minutes, 45)
        self.assertEqual(len(fresh.tasks), 6)
        self.assertTrue(fresh.has_text("45 min planned") or fresh.has_text("of 45 min"))

    def test_plan_log_button_logs_session(self):
        self.add(minutes=120, due=date.today() + timedelta(days=5))
        tid = self.app.tasks[0]["id"]
        before = self.app.tasks[0]["minutes_done"]
        self.app.press(f"plan_{tid}")
        self.assertGreater(self.app.tasks[0]["minutes_done"], before)

    def test_focus_timer_flow(self):
        self.assertTrue(self.app.has_text("Add an assignment to start", "info"))
        self.add(minutes=120, due=date.today() + timedelta(days=5))
        tid = self.app.tasks[0]["id"]
        self.app.set("focus_minutes", 10)
        self.assertEqual(self.app.st.session_state.focus["total"], 600)
        self.app.press("f_start")
        f = self.app.st.session_state.focus
        self.assertTrue(f["running"])
        self.app.press("f_pause")
        self.assertFalse(self.app.st.session_state.focus["running"])
        self.assertGreater(self.app.st.session_state.focus["left"], 590)
        self.app.press("f_start")
        self.app.st.session_state.focus["end"] = time.time() - 1       # time passes
        self.app.run()
        f = self.app.st.session_state.focus
        self.assertTrue(f["done"] and not f["running"])
        self.assertTrue(self.app.has_text("Session complete", "success"))
        self.assertIn("balloons", [n for n, _ in self.app.st.out])
        self.app.press("f_log")
        self.assertEqual(self.app.tasks[0]["minutes_done"], 10)
        self.assertFalse(self.app.st.session_state.focus["done"])
        self.app.press("f_start")
        self.app.press("f_reset")
        self.assertEqual(self.app.st.session_state.focus["left"], 600)

    def test_ai_coach_states(self):
        self.app.press("load_demo")
        self.assertTrue(self.app.has_text("To enable the AI coach", "info"))
        self.app.set_many({"ai_api_key": "k", "ai_model": "some/model"})
        self.app.run()
        self.assertIn("ask_ai", self.app.st.registered)
        self.app.st.session_state.ai_question = "Plan my week"
        with mock.patch.object(ai_coach, "chat", return_value="Study calculus first.") as chat:
            self.app.press("ask_ai")
        self.assertTrue(self.app.has_text("Study calculus first."))
        self.assertIn("Plan my week", chat.call_args[0][3][1]["content"])
        self.app.st.session_state.ai_answer = None
        with mock.patch.object(ai_coach, "chat", side_effect=ai_coach.AIError("HTTP 401")):
            self.app.press("ask_ai")
        self.assertTrue(self.app.has_text("HTTP 401", "error"))

    def test_survives_hostile_text_and_legacy_data(self):
        (self.dir / "tasks.json").write_text(json.dumps([
            {"name": "**bold** _x_ $$ <b>", "subject": "a|b", "due_date": "2026-12-01",
             "priority": "High", "completed": False, "duration": 30}]), encoding="utf-8")
        app = AppRunner(APP).run()
        self.assertEqual(len(app.tasks), 1)
        self.assertTrue(app.has_text(r"\*\*bold\*\*"))                 # Markdown escaped

    def test_extreme_settings_do_not_crash(self):
        self.app.press("load_demo")
        for minutes in (15, 1440):
            self.app.set("daily_minutes", minutes)
        self.app.set("horizon_days", 3)
        self.app.set("session_len", 120)


if __name__ == "__main__":
    unittest.main()
