"""Pure planning logic for StudyPilot.

Nothing in this module imports Streamlit, so every function can be unit-tested
and reused (CLI, API, other front-ends). Dates are stored in tasks as ISO
strings ("YYYY-MM-DD") so tasks.json stays human-readable and backwards
compatible with the first prototype.
"""
from __future__ import annotations

import csv
import io
import math
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

PRIORITIES = ("Low", "Medium", "High")
PRIORITY_WEIGHT = {"Low": 1, "Medium": 2, "High": 3}
SORT_OPTIONS = ("Smart (urgency)", "Due date", "Priority", "Course", "Newest")
STATUS_FILTERS = ("All", "Pending", "Completed", "Overdue")
STATUS_LABEL = {
    "completed": ("✅", "Completed"),
    "overdue": ("🔴", "Overdue"),
    "today": ("🟠", "Due today"),
    "soon": ("🟡", "Due soon"),
    "ok": ("🟢", "On track"),
}


# --------------------------------------------------------------------------- #
# Dates & task construction
# --------------------------------------------------------------------------- #
def parse_date(value: Any, default: Optional[date] = None) -> Optional[date]:
    """Parse a date / datetime / ISO string. Returns `default` if impossible."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return default
    return default


def new_task(
    name: str,
    subject: str,
    due_date: Any,
    duration: int,
    priority: str,
    notes: str = "",
    description: str = "",
    today: Optional[date] = None,
) -> dict:
    today = today or date.today()
    due = parse_date(due_date, today)
    return {
        "id": uuid.uuid4().hex,
        "name": name.strip(),
        "subject": subject.strip(),
        "due_date": due.isoformat(),
        "duration": max(int(duration), 1),
        "priority": priority if priority in PRIORITIES else "Medium",
        "notes": (notes or "").strip(),
        "description": (description or "").strip(),
        "completed": False,
        "minutes_done": 0,
        "log": [],
        "created": today.isoformat(),
        "completed_on": None,
        "ai_plan": None,
    }


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_task(raw: Any, today: Optional[date] = None) -> Optional[dict]:
    """Migrate/validate a stored task (including the old prototype format).

    Returns None only when the record is unusable (not a dict / no name).
    """
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    today = today or date.today()
    completed = bool(raw.get("completed", False))
    duration = max(_to_int(raw.get("duration"), 60), 1)
    minutes_done = max(
        _to_int(raw.get("minutes_done"), duration if completed else 0), 0
    )
    log = []
    for entry in raw.get("log") or []:
        if not isinstance(entry, dict):
            continue
        d = parse_date(entry.get("date"))
        m = _to_int(entry.get("minutes"), 0)
        if d and m > 0:
            log.append({"date": d.isoformat(), "minutes": m})
    priority = raw.get("priority")
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": name,
        "subject": str(raw.get("subject") or "General").strip() or "General",
        "due_date": parse_date(raw.get("due_date"), today).isoformat(),
        "duration": duration,
        "priority": priority if priority in PRIORITIES else "Medium",
        "notes": str(raw.get("notes") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "completed": completed,
        "minutes_done": minutes_done,
        "log": log,
        "created": parse_date(raw.get("created"), today).isoformat(),
        "completed_on": (
            parse_date(raw.get("completed_on")).isoformat()
            if parse_date(raw.get("completed_on"))
            else None
        ),
        "ai_plan": raw.get("ai_plan"),
    }


# --------------------------------------------------------------------------- #
# Per-task helpers
# --------------------------------------------------------------------------- #
def remaining_minutes(task: dict) -> int:
    if task["completed"]:
        return 0
    return max(task["duration"] - task["minutes_done"], 0)


def progress_fraction(task: dict) -> float:
    if task["completed"]:
        return 1.0
    return min(task["minutes_done"] / task["duration"], 1.0)


def days_until(task: dict, today: date) -> int:
    return (parse_date(task["due_date"], today) - today).days


def status(task: dict, today: date) -> str:
    if task["completed"]:
        return "completed"
    d = days_until(task, today)
    if d < 0:
        return "overdue"
    if d == 0:
        return "today"
    if d <= 2:
        return "soon"
    return "ok"


def urgency_score(task: dict, today: date) -> float:
    """Higher = should be studied sooner. Mixes priority and deadline pressure."""
    d = days_until(task, today)
    score = PRIORITY_WEIGHT[task["priority"]] * 10 + 30 / (max(d, 0) + 1)
    if d < 0:
        score += 100 + min(-d, 30)
    return score


def complete_task(task: dict, today: date) -> None:
    task["completed"] = True
    task["minutes_done"] = max(task["minutes_done"], task["duration"])
    task["completed_on"] = today.isoformat()


def reopen_task(task: dict) -> None:
    task["completed"] = False
    task["completed_on"] = None
    if task["minutes_done"] >= task["duration"]:
        task["minutes_done"] = 0


def log_minutes(task: dict, minutes: int, today: date) -> bool:
    """Record study time. Returns True if this log completed the task."""
    minutes = int(minutes)
    if minutes <= 0 or task["completed"]:
        return False
    task["minutes_done"] += minutes
    iso = today.isoformat()
    if task["log"] and task["log"][-1]["date"] == iso:
        task["log"][-1]["minutes"] += minutes
    else:
        task["log"].append({"date": iso, "minutes": minutes})
    if task["minutes_done"] >= task["duration"]:
        complete_task(task, today)
        return True
    return False


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #
def _minutes_by_day(tasks: Iterable[dict]) -> dict:
    totals: dict = {}
    for t in tasks:
        for entry in t["log"]:
            d = parse_date(entry["date"])
            if d:
                totals[d] = totals.get(d, 0) + entry["minutes"]
    return totals


def weekly_minutes(tasks: Iterable[dict], today: date, days: int = 7) -> list:
    totals = _minutes_by_day(tasks)
    return [
        (today - timedelta(days=i), totals.get(today - timedelta(days=i), 0))
        for i in range(days - 1, -1, -1)
    ]


def study_streak(tasks: Iterable[dict], today: date) -> int:
    """Consecutive days with logged study time (today may still be pending)."""
    studied = set(_minutes_by_day(tasks))
    cursor = today if today in studied else today - timedelta(days=1)
    streak = 0
    while cursor in studied:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def summarize(tasks: list, today: date) -> dict:
    pending = [t for t in tasks if not t["completed"]]
    total_minutes = sum(t["duration"] for t in tasks)
    done_minutes = sum(min(t["minutes_done"], t["duration"]) for t in tasks)
    return {
        "total": len(tasks),
        "pending": len(pending),
        "completed": len(tasks) - len(pending),
        "overdue": sum(1 for t in pending if days_until(t, today) < 0),
        "due_today": sum(1 for t in pending if days_until(t, today) == 0),
        "minutes_left": sum(remaining_minutes(t) for t in pending),
        "completion_pct": (done_minutes / total_minutes) if total_minutes else 0.0,
        "streak": study_streak(tasks, today),
    }


def format_minutes(minutes: int) -> str:
    h, m = divmod(max(int(minutes), 0), 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


# --------------------------------------------------------------------------- #
# Filtering / sorting
# --------------------------------------------------------------------------- #
def filter_tasks(
    tasks: list,
    today: date,
    query: str = "",
    subject: str = "All",
    priorities: Optional[Iterable[str]] = None,
    status_filter: str = "All",
    sort_by: str = "Smart (urgency)",
) -> list:
    q = (query or "").strip().lower()
    prios = set(priorities) if priorities else set(PRIORITIES)
    result = []
    for idx, t in enumerate(tasks):
        if q and q not in t["name"].lower() and q not in t["subject"].lower() \
                and q not in t["notes"].lower() and q not in t.get("description", "").lower():
            continue
        if subject != "All" and t["subject"] != subject:
            continue
        if t["priority"] not in prios:
            continue
        st = status(t, today)
        if status_filter == "Pending" and t["completed"]:
            continue
        if status_filter == "Completed" and not t["completed"]:
            continue
        if status_filter == "Overdue" and st != "overdue":
            continue
        result.append((idx, t))

    def due(t):
        return parse_date(t["due_date"], today)

    if sort_by == "Due date":
        result.sort(key=lambda p: (p[1]["completed"], due(p[1]), p[0]))
    elif sort_by == "Priority":
        result.sort(key=lambda p: (p[1]["completed"],
                                   -PRIORITY_WEIGHT[p[1]["priority"]],
                                   due(p[1]), p[0]))
    elif sort_by == "Course":
        result.sort(key=lambda p: (p[1]["subject"].lower(), p[1]["completed"],
                                   due(p[1]), p[0]))
    elif sort_by == "Newest":
        result.sort(key=lambda p: (-p[0]))
    else:  # Smart (urgency)
        result.sort(key=lambda p: (p[1]["completed"],
                                   -urgency_score(p[1], today), p[0]))
    return [t for _, t in result]


# --------------------------------------------------------------------------- #
# Smart plan
# --------------------------------------------------------------------------- #
def build_plan(
    tasks: list,
    daily_minutes: int,
    start: Optional[date] = None,
    horizon_days: int = 14,
    session_len: int = 45,
) -> dict:
    start = start or date.today()
    daily_minutes = max(int(daily_minutes), 0)
    session_len = max(int(session_len), 5)
    horizon_days = max(int(horizon_days), 1)

    pending = [t for t in tasks if remaining_minutes(t) > 0]
    remaining = {t["id"]: remaining_minutes(t) for t in pending}
    finish: dict = {}
    days = []

    for offset in range(horizon_days):
        day = start + timedelta(days=offset)
        left = daily_minutes
        alloc: dict = {}
        order = sorted(
            (t for t in pending if remaining[t["id"]] > 0),
            key=lambda t: (-urgency_score(t, day),
                           parse_date(t["due_date"], day), t["name"].lower()),
        )
        progressed = True
        while left > 0 and progressed:
            progressed = False
            for t in order:
                tid = t["id"]
                if remaining[tid] <= 0 or left <= 0:
                    continue
                chunk = min(session_len, remaining[tid], left)
                alloc[tid] = alloc.get(tid, 0) + chunk
                remaining[tid] -= chunk
                left -= chunk
                progressed = True
                if remaining[tid] == 0:
                    finish[tid] = day
        by_id = {t["id"]: t for t in pending}
        sessions = []
        for tid, minutes in alloc.items():
            t = by_id[tid]
            sessions.append({
                "task_id": tid,
                "name": t["name"],
                "subject": t["subject"],
                "priority": t["priority"],
                "due_date": t["due_date"],
                "minutes": minutes,
                "blocks": math.ceil(minutes / session_len),
            })
        days.append({
            "date": day,
            "sessions": sessions,
            "minutes": daily_minutes - left,
            "free": left,
        })

    at_risk = []
    for t in pending:
        due = parse_date(t["due_date"], start)
        fin = finish.get(t["id"])
        if due < start:
            reason = "overdue"
        elif fin is None:
            reason = f"won't be finished within the next {horizon_days} days"
        elif fin > due:
            reason = f"would finish on {fin.isoformat()}, after its due date"
        else:
            continue
        span = max((due - start).days + 1, 1)
        at_risk.append({
            "task_id": t["id"],
            "name": t["name"],
            "reason": reason,
            "overdue": due < start,
            "needed_per_day": math.ceil(remaining_minutes(t) / span),
        })
    return {
        "days": days,
        "at_risk": at_risk,
        "unscheduled_minutes": sum(remaining.values()),
    }


def smart_tips(tasks: list, plan: dict, today: date, daily_minutes: int) -> list:
    tips = []
    pending = [t for t in tasks if not t["completed"]]
    if not tasks:
        return [("info", "Add your first assignment (or load the demo data) and "
                         "I'll build a study plan for you.")]
    if not pending:
        return [("success", "All assignments are completed. Enjoy the break — "
                            "you've earned it! 🎉")]

    overdue = [t for t in pending if days_until(t, today) < 0]
    if overdue:
        names = ", ".join(t["name"] for t in overdue[:3])
        tips.append(("error", f"{len(overdue)} overdue: {names}. "
                              "Tackle these first, even for just one short session."))
    due_today = [t for t in pending if days_until(t, today) == 0]
    if due_today:
        tips.append(("warning", "Due today: " +
                     ", ".join(t["name"] for t in due_today[:3]) + "."))
    risky = [r for r in plan["at_risk"] if not r["overdue"]]
    for r in risky[:3]:
        tips.append(("warning",
                     f"“{r['name']}” {r['reason']}. You'd need about "
                     f"{r['needed_per_day']} min/day on it to stay on schedule — "
                     "consider raising your daily availability."))
    today_plan = plan["days"][0] if plan["days"] else None
    if today_plan and today_plan["sessions"]:
        first = today_plan["sessions"][0]
        tips.append(("info", f"Start today with “{first['name']}” "
                             f"({first['minutes']} min) — it's your most urgent task."))
        if today_plan["free"] > 0 and plan["unscheduled_minutes"] == 0:
            tips.append(("info", f"Everything fits and you still have "
                                 f"{today_plan['free']} free minutes today: "
                                 "a good moment to get ahead or review."))
    elif daily_minutes <= 0:
        tips.append(("warning", "Your daily availability is 0 minutes."))
    streak = study_streak(tasks, today)
    if streak >= 1:
        tips.append(("success", f"🔥 {streak}-day study streak. Keep it going!"))
    elif any(t["log"] for t in tasks):
        tips.append(("info", "Log a session today to start a new streak."))
    return tips


# --------------------------------------------------------------------------- #
# Plan export
# --------------------------------------------------------------------------- #
def plan_to_markdown(plan: dict, daily_minutes: int) -> str:
    lines = ["# StudyPilot — Study Plan", "",
             f"Availability: {daily_minutes} min/day", ""]
    for day in plan["days"]:
        if not day["sessions"]:
            continue
        lines.append(f"## {day['date']:%A, %d %B %Y} ({day['minutes']} min)")
        for s in day["sessions"]:
            lines.append(f"- [ ] {s['name']} ({s['subject']}) — {s['minutes']} min, "
                         f"priority {s['priority']}, due {s['due_date']}")
        lines.append("")
    if plan["at_risk"]:
        lines.append("## At risk")
        for r in plan["at_risk"]:
            lines.append(f"- {r['name']}: {r['reason']}")
    return "\n".join(lines).rstrip() + "\n"


def plan_to_csv(plan: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "assignment", "course", "minutes", "priority", "due_date"])
    for day in plan["days"]:
        for s in day["sessions"]:
            writer.writerow([day["date"].isoformat(), s["name"], s["subject"],
                             s["minutes"], s["priority"], s["due_date"]])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Demo data
# --------------------------------------------------------------------------- #
def demo_tasks(today: Optional[date] = None) -> list:
    today = today or date.today()
    rows = [
        ("Calculus problem set 5", "Mathematics", -1, 90, "High"),
        ("Lab report: titration", "Chemistry", 2, 120, "High"),
        ("Read chapters 3–4", "History", 4, 60, "Medium"),
        ("Essay draft", "Literature", 6, 150, "Medium"),
        ("Vocabulary review", "Spanish", 3, 30, "Low"),
        ("Midterm revision", "Physics", 9, 240, "High"),
    ]
    tasks = [new_task(n, s, today + timedelta(days=d), m, p, today=today)
             for n, s, d, m, p in rows]
    log_minutes(tasks[2], 20, today - timedelta(days=1))
    log_minutes(tasks[3], 40, today - timedelta(days=2))
    log_minutes(tasks[1], 30, today)
    return tasks