import csv
import io
import random
import unittest
from datetime import date, timedelta

import planner

TODAY = date(2026, 10, 25)


def mk(name="A", days=3, minutes=60, prio="Medium", subject="Math", done=0):
    t = planner.new_task(name, subject, TODAY + timedelta(days=days), minutes, prio, today=TODAY)
    t["minutes_done"] = done
    return t


class DateAndNormalizeTests(unittest.TestCase):
    def test_parse_date_variants(self):
        self.assertEqual(planner.parse_date("2026-10-25"), TODAY)
        self.assertEqual(planner.parse_date("2026-10-25T10:00:00"), TODAY)
        self.assertEqual(planner.parse_date(TODAY), TODAY)
        self.assertIsNone(planner.parse_date("not a date"))
        self.assertEqual(planner.parse_date(None, TODAY), TODAY)

    def test_normalize_legacy_prototype_task(self):
        legacy = {"name": " Essay ", "subject": "Lit", "due_date": "2026-11-01",
                  "priority": "High", "completed": True}
        t = planner.normalize_task(legacy, TODAY)
        self.assertEqual(t["name"], "Essay")
        self.assertEqual(t["duration"], 60)
        self.assertEqual(t["minutes_done"], 60)  # completed => fully done
        self.assertTrue(t["id"])
        self.assertEqual(t["log"], [])

    def test_normalize_rejects_garbage_but_repairs_fields(self):
        self.assertIsNone(planner.normalize_task("x"))
        self.assertIsNone(planner.normalize_task({"name": "  "}))
        t = planner.normalize_task({"name": "x", "duration": "abc", "priority": "??",
                                    "due_date": "bad", "log": [{"date": "bad", "minutes": 5}, 3]}, TODAY)
        self.assertEqual(t["duration"], 60)
        self.assertEqual(t["priority"], "Medium")
        self.assertEqual(t["due_date"], TODAY.isoformat())
        self.assertEqual(t["log"], [])


class TaskLogicTests(unittest.TestCase):
    def test_log_minutes_auto_completes_and_merges_same_day(self):
        t = mk(minutes=60)
        self.assertFalse(planner.log_minutes(t, 30, TODAY))
        self.assertFalse(planner.log_minutes(t, 15, TODAY))
        self.assertEqual(t["log"], [{"date": TODAY.isoformat(), "minutes": 45}])
        self.assertTrue(planner.log_minutes(t, 30, TODAY))
        self.assertTrue(t["completed"])
        self.assertEqual(planner.remaining_minutes(t), 0)
        self.assertFalse(planner.log_minutes(t, 10, TODAY))  # already completed
        self.assertFalse(planner.log_minutes(mk(), -5, TODAY))

    def test_reopen_resets_full_progress(self):
        t = mk(minutes=60)
        planner.complete_task(t, TODAY)
        planner.reopen_task(t)
        self.assertFalse(t["completed"])
        self.assertEqual(t["minutes_done"], 0)
        self.assertEqual(planner.remaining_minutes(t), 60)

    def test_status_and_urgency_order(self):
        overdue, today_, soon, later = mk(days=-2), mk(days=0), mk(days=2), mk(days=10)
        self.assertEqual([planner.status(t, TODAY) for t in (overdue, today_, soon, later)],
                         ["overdue", "today", "soon", "ok"])
        scores = [planner.urgency_score(t, TODAY) for t in (overdue, today_, soon, later)]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertGreater(planner.urgency_score(mk(prio="High"), TODAY),
                           planner.urgency_score(mk(prio="Low"), TODAY))

    def test_streak_and_weekly(self):
        t = mk(minutes=999)
        planner.log_minutes(t, 10, TODAY - timedelta(days=2))
        planner.log_minutes(t, 10, TODAY - timedelta(days=1))
        self.assertEqual(planner.study_streak([t], TODAY), 2)  # today not yet studied
        planner.log_minutes(t, 5, TODAY)
        self.assertEqual(planner.study_streak([t], TODAY), 3)
        self.assertEqual(planner.study_streak([], TODAY), 0)
        week = planner.weekly_minutes([t], TODAY)
        self.assertEqual(len(week), 7)
        self.assertEqual(week[-1], (TODAY, 5))
        self.assertEqual(sum(m for _, m in week), 25)

    def test_summarize(self):
        a, b = mk(days=-1, minutes=60), mk(days=0, minutes=40)
        planner.complete_task(b, TODAY)
        s = planner.summarize([a, b], TODAY)
        self.assertEqual((s["pending"], s["completed"], s["overdue"]), (1, 1, 1))
        self.assertEqual(s["minutes_left"], 60)
        self.assertAlmostEqual(s["completion_pct"], 0.4)
        self.assertEqual(planner.summarize([], TODAY)["completion_pct"], 0.0)

    def test_format_minutes(self):
        self.assertEqual([planner.format_minutes(m) for m in (0, 45, 60, 135)],
                         ["0m", "45m", "1h", "2h 15m"])


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.a = mk("Calculus", 5, subject="Math", prio="High")
        self.b = mk("Essay", 1, subject="Lit", prio="Low")
        self.c = mk("Lab", 3, subject="Chem", prio="Medium")
        planner.complete_task(self.c, TODAY)
        self.tasks = [self.a, self.b, self.c]

    def names(self, **kw):
        return [t["name"] for t in planner.filter_tasks(self.tasks, TODAY, **kw)]

    def test_filters(self):
        self.assertEqual(self.names(query="calc"), ["Calculus"])
        self.assertEqual(self.names(subject="Lit"), ["Essay"])
        self.assertEqual(self.names(status_filter="Completed"), ["Lab"])
        self.assertEqual(self.names(status_filter="Pending", priorities=["High"]), ["Calculus"])
        self.assertEqual(len(self.names(priorities=[])), 3)  # empty selection = no filter

    def test_sorting(self):
        self.assertEqual(self.names(sort_by="Due date"), ["Essay", "Calculus", "Lab"])
        self.assertEqual(self.names(sort_by="Priority"), ["Calculus", "Essay", "Lab"])
        self.assertEqual(self.names(sort_by="Course"), ["Lab", "Essay", "Calculus"])
        self.assertEqual(self.names(sort_by="Newest"), ["Lab", "Essay", "Calculus"])
        self.assertEqual(self.names()[-1], "Lab")  # completed always last in smart sort


class PlanTests(unittest.TestCase):
    def test_never_exceeds_daily_minutes_and_allocates_everything(self):
        tasks = [mk("A", 5, 100, "High"), mk("B", 2, 80, "Low"), mk("C", 9, 200, "Medium")]
        plan = planner.build_plan(tasks, 90, TODAY, horizon_days=14, session_len=45)
        self.assertTrue(all(d["minutes"] <= 90 for d in plan["days"]))
        self.assertEqual(sum(d["minutes"] for d in plan["days"]), 380)
        self.assertEqual(plan["unscheduled_minutes"], 0)
        for d in plan["days"]:
            self.assertEqual(d["minutes"], sum(s["minutes"] for s in d["sessions"]))
            self.assertEqual(d["minutes"] + d["free"], 90)

    def test_most_urgent_first_and_round_robin(self):
        urgent = mk("Urgent", 0, 120, "High")
        other = mk("Other", 7, 120, "Low")
        plan = planner.build_plan([other, urgent], 90, TODAY, 7, 30)
        first = plan["days"][0]["sessions"]
        self.assertEqual(first[0]["name"], "Urgent")
        self.assertEqual({s["name"] for s in first}, {"Urgent", "Other"})  # shared, not hogged
        self.assertGreaterEqual(first[0]["minutes"], first[1]["minutes"])

    def test_overdue_scheduled_first_and_flagged(self):
        late = mk("Late", -3, 30, "Low")
        fine = mk("Fine", 5, 30, "High")
        plan = planner.build_plan([fine, late], 30, TODAY)
        self.assertEqual(plan["days"][0]["sessions"][0]["name"], "Late")
        risk = {r["name"]: r for r in plan["at_risk"]}
        self.assertTrue(risk["Late"]["overdue"])
        self.assertNotIn("Fine", risk)

    def test_at_risk_when_capacity_too_small(self):
        t = mk("Big", 1, 600, "High")  # needs 10h, due tomorrow, 60 min/day
        plan = planner.build_plan([t], 60, TODAY, horizon_days=5)
        self.assertEqual(len(plan["at_risk"]), 1)
        self.assertGreater(plan["at_risk"][0]["needed_per_day"], 60)
        self.assertGreater(plan["unscheduled_minutes"], 0)

    def test_edge_cases(self):
        self.assertEqual(planner.build_plan([], 60, TODAY)["at_risk"], [])
        plan = planner.build_plan([mk()], 0, TODAY, horizon_days=3)
        self.assertTrue(all(not d["sessions"] for d in plan["days"]))
        done = mk()
        planner.complete_task(done, TODAY)
        self.assertTrue(all(not d["sessions"] for d in planner.build_plan([done], 60, TODAY)["days"]))
        partial = mk(minutes=60, done=45)
        plan = planner.build_plan([partial], 120, TODAY)
        self.assertEqual(plan["days"][0]["sessions"][0]["minutes"], 15)
        self.assertEqual(len(planner.build_plan([mk()], 60, TODAY, horizon_days=0)["days"]), 1)

    def test_blocks(self):
        plan = planner.build_plan([mk(minutes=100, days=9)], 100, TODAY, session_len=30)
        s = plan["days"][0]["sessions"][0]
        self.assertEqual((s["minutes"], s["blocks"]), (100, 4))

    def test_random_invariants(self):
        rng = random.Random(7)
        for _ in range(200):
            tasks = [mk(f"T{i}", rng.randint(-3, 20), rng.randint(5, 400),
                        rng.choice(planner.PRIORITIES), done=rng.choice([0, 0, 10]))
                     for i in range(rng.randint(0, 8))]
            daily = rng.choice([0, 15, 45, 120, 480])
            horizon = rng.randint(1, 30)
            plan = planner.build_plan(tasks, daily, TODAY, horizon, rng.choice([15, 45, 90]))
            self.assertEqual(len(plan["days"]), horizon)
            per_task = {}
            for d in plan["days"]:
                self.assertLessEqual(d["minutes"], daily)
                for s in d["sessions"]:
                    per_task[s["task_id"]] = per_task.get(s["task_id"], 0) + s["minutes"]
            for t in tasks:
                self.assertLessEqual(per_task.get(t["id"], 0), planner.remaining_minutes(t))
            total_rem = sum(planner.remaining_minutes(t) for t in tasks)
            self.assertEqual(sum(per_task.values()) + plan["unscheduled_minutes"], total_rem)


class TipsAndExportTests(unittest.TestCase):
    def test_tips(self):
        self.assertEqual(planner.smart_tips([], planner.build_plan([], 60, TODAY), TODAY, 60)[0][0], "info")
        done = mk(); planner.complete_task(done, TODAY)
        self.assertEqual(planner.smart_tips([done], planner.build_plan([done], 60, TODAY), TODAY, 60)[0][0], "success")
        tasks = [mk("Late", -1), mk("Now", 0), mk("Huge", 1, 900, "High")]
        plan = planner.build_plan(tasks, 60, TODAY)
        tips = planner.smart_tips(tasks, plan, TODAY, 60)
        levels = [l for l, _ in tips]
        self.assertIn("error", levels)
        self.assertIn("warning", levels)
        joined = " ".join(t for _, t in tips)
        self.assertIn("Late", joined)
        self.assertIn("Huge", joined)

    def test_exports(self):
        tasks = [mk("A, with comma", 2, 60)]
        plan = planner.build_plan(tasks, 60, TODAY, 3)
        md = planner.plan_to_markdown(plan, 60)
        self.assertIn("A, with comma", md)
        rows = list(csv.reader(io.StringIO(planner.plan_to_csv(plan))))
        self.assertEqual(rows[0][0], "date")
        self.assertEqual(rows[1][1], "A, with comma")

    def test_demo_tasks(self):
        tasks = planner.demo_tasks(TODAY)
        self.assertEqual(len(tasks), 6)
        self.assertEqual(len({t["id"] for t in tasks}), 6)
        self.assertTrue(any(planner.status(t, TODAY) == "overdue" for t in tasks))
        self.assertGreaterEqual(planner.study_streak(tasks, TODAY), 1)


if __name__ == "__main__":
    unittest.main()
