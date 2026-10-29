"""StudyPilot — Your Academic Copilot (Streamlit app).

Run with:  python -m streamlit run app.py
"""
import json
import re
import time
from datetime import date

import streamlit as st

import ai_coach
import planner
import storage

st.set_page_config(page_title="StudyPilot", page_icon="⚡", layout="wide")

PRIORITY_ICON = {"Low": "🟦", "Medium": "🟨", "High": "🟥"}


# --------------------------------------------------------------------------- #
# Helpers & Theme Management
# --------------------------------------------------------------------------- #
def today() -> date:
    return date.today()


def esc(text: str) -> str:
    """Escape Markdown so user text can't break the layout."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~$<>])", r"\\\1", str(text))


def flash(message: str, kind: str = "success") -> None:
    st.session_state.flash = (kind, message)


def persist() -> None:
    try:
        storage.save_tasks(st.session_state.tasks)
    except OSError as exc:
        flash(f"Could not save your data: {exc}", "error")


def find_task(task_id: str):
    for task in st.session_state.tasks:
        if task["id"] == task_id:
            return task
    return None


def init_state() -> None:
    ss = st.session_state
    if "tasks" not in ss:
        ss.tasks = storage.load_tasks()
    if "settings" not in ss:
        ss.settings = storage.load_settings()
    for key in ("daily_minutes", "session_len", "horizon_days",
                "ai_base_url", "ai_model", "theme", "tavily_api_key"):
        if key not in ss:
            ss[key] = ss.settings.get(key, storage.DEFAULT_SETTINGS.get(key, ""))
    defaults = {
        "flash": None,
        "pending_complete": None,
        "pending_delete": None,
        "ai_answer": None,
        "focus": {"minutes": 25, "total": 1500, "left": 1500, "end": None,
                  "running": False, "done": False},
    }
    for key, value in defaults.items():
        if key not in ss:
            ss[key] = value

    # Apply professional Theme styling
    if ss.theme == "Dark":
        st.markdown("""
            <style>
            .stApp {
                background-color: #0e1117;
                color: #f0f2f6;
            }
            section[data-testid="stSidebar"] {
                background-color: #161b22;
                color: #f0f2f6;
            }
            h1, h2, h3, h4, h5, h6, .stMarkdown p, span, label {
                color: #f0f2f6 !important;
            }
            header [data-testid="stToolbar"], header [data-testid="stToolbar"] * {
                color: #4a5568 !important;
            }
            .stTextInput input, .stTextArea textarea, .stNumberInput input, .stSelectbox select {
                background-color: #1f242d !important;
                color: #f0f2f6 !important;
                border-color: #30363d !important;
            }
            div[data-testid="stContainer"] {
                background-color: #161b22;
                border: 1px solid #30363d;
            }
            </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
            <style>
            .stApp {
                background-color: #ffffff;
                color: #1f1f1f;
            }
            section[data-testid="stSidebar"] {
                background-color: #f8f9fa;
                color: #1f1f1f;
            }
            </style>
        """, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #
def cb_save_settings() -> None:
    ss = st.session_state
    ss.settings = {k: ss.get(k) for k in storage.DEFAULT_SETTINGS}
    try:
        storage.save_settings(ss.settings)
    except OSError as exc:
        flash(f"Could not save settings: {exc}", "error")


def cb_add_task() -> None:
    ss = st.session_state
    name = (ss.get("new_name") or "").strip()
    subject = (ss.get("new_subject") or "").strip()
    if not name or not subject:
        flash("Please enter both the assignment name and the course.", "warning")
        return
    due = ss.get("new_due") or today()
    duplicate = any(
        not t["completed"] and t["name"].lower() == name.lower()
        and t["subject"].lower() == subject.lower() and t["due_date"] == due.isoformat()
        for t in ss.tasks
    )
    if duplicate:
        flash("That assignment already exists.", "warning")
        return
    ss.tasks.append(planner.new_task(
        name=name,
        subject=subject,
        due_date=due,
        duration=ss.get("new_duration", 60),
        priority=ss.get("new_priority", "Medium"),
        notes=ss.get("new_notes", ""),
        description=ss.get("new_description", ""),
        today=today()
    ))
    persist()
    ss.new_name = ""
    ss.new_notes = ""
    ss.new_description = ""
    if due < today():
        flash("Assignment added — note that its due date is already in the past.", "warning")
    else:
        flash(f"Added “{name}”.")


def cb_request_complete(task_id: str) -> None:
    st.session_state.pending_complete = task_id


def cb_cancel_complete() -> None:
    st.session_state.pending_complete = None


def cb_confirm_complete(task_id: str) -> None:
    task = find_task(task_id)
    if task:
        planner.complete_task(task, today())
        persist()
        flash(f"Completed “{task['name']}” 🎉")
    st.session_state.pending_complete = None


def cb_reopen(task_id: str) -> None:
    task = find_task(task_id)
    if task:
        planner.reopen_task(task)
        persist()
        flash(f"Reopened “{task['name']}”.", "info")


def cb_request_delete(task_id: str) -> None:
    st.session_state.pending_delete = task_id


def cb_cancel_delete() -> None:
    st.session_state.pending_delete = None


def cb_confirm_delete(task_id: str) -> None:
    ss = st.session_state
    ss.tasks = [t for t in ss.tasks if t["id"] != task_id]
    ss.pending_delete = None
    persist()
    flash("Assignment deleted.", "info")


def cb_log(task_id: str, minutes: int) -> None:
    task = find_task(task_id)
    if not task:
        return
    finished = planner.log_minutes(task, minutes, today())
    persist()
    if finished:
        flash(f"Logged {minutes} min — “{task['name']}” is complete! 🎉")
    else:
        flash(f"Logged {minutes} min on “{task['name']}”.")


def cb_save_edit(task_id: str) -> None:
    ss = st.session_state
    task = find_task(task_id)
    if not task:
        return
    name = (ss.get(f"e_name_{task_id}") or "").strip()
    subject = (ss.get(f"e_subject_{task_id}") or "").strip()
    if not name or not subject:
        flash("Name and course can't be empty.", "warning")
        return
    task["name"] = name
    task["subject"] = subject
    task["due_date"] = planner.parse_date(
        ss.get(f"e_due_{task_id}"), today()).isoformat()
    task["duration"] = max(int(ss.get(f"e_duration_{task_id}", task["duration"])), 1)
    task["priority"] = ss.get(f"e_priority_{task_id}", task["priority"])
    task["notes"] = (ss.get(f"e_notes_{task_id}") or "").strip()
    task["description"] = (ss.get(f"e_description_{task_id}") or "").strip()
    if not task["completed"] and task["minutes_done"] >= task["duration"]:
        planner.complete_task(task, today())
    persist()
    flash(f"Saved changes to “{name}”.")


def cb_load_demo() -> None:
    ss = st.session_state
    ss.tasks.extend(planner.demo_tasks(today()))
    persist()
    flash("Demo data loaded.", "info")


def cb_focus_minutes() -> None:
    ss = st.session_state
    minutes = int(ss.get("focus_minutes", 25))
    ss.focus = {"minutes": minutes, "total": minutes * 60, "left": minutes * 60,
                "end": None, "running": False, "done": False}


def cb_focus_start() -> None:
    f = st.session_state.focus
    if f["left"] <= 0:
        f["left"] = f["total"]
    f["end"] = time.time() + f["left"]
    f["running"] = True
    f["done"] = False


def cb_focus_pause() -> None:
    f = st.session_state.focus
    if f["running"]:
        f["left"] = max(f["end"] - time.time(), 0)
        f["running"] = False


def cb_focus_reset() -> None:
    cb_focus_minutes()


def cb_focus_log(task_id: str) -> None:
    minutes = st.session_state.focus["minutes"]
    cb_log(task_id, minutes)
    cb_focus_minutes()


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def render_sidebar() -> None:
    with st.sidebar:
        st.header("⚙️ Settings")
        
        theme_selection = st.selectbox(
            "Appearance",
            ["Light", "Dark"],
            index=0 if st.session_state.theme == "Light" else 1,
            key="theme_selectbox"
        )
        if theme_selection != st.session_state.theme:
            st.session_state.theme = theme_selection
            cb_save_settings()
            st.rerun()

        st.number_input("Study minutes per day", min_value=15, max_value=1440,
                        step=15, key="daily_minutes", on_change=cb_save_settings)
        st.slider("Study block length (min)", min_value=15, max_value=120,
                  step=5, key="session_len", on_change=cb_save_settings,
                  help="Long tasks are split into blocks of this size.")
        st.slider("Planning horizon (days)", min_value=3, max_value=60,
                  key="horizon_days", on_change=cb_save_settings)

        with st.expander("🤖 AI coach & Tavily"):
            st.caption("Nebius Token Factory + Nemotron & Tavily Search.")
            st.text_input("Base URL", key="ai_base_url", on_change=cb_save_settings)
            st.text_input("Model id", key="ai_model", on_change=cb_save_settings,
                          placeholder="Nemotron model ID")
            st.text_input("AI API key", type="password", key="ai_api_key")
            st.text_input("Tavily API key", type="password", key="tavily_api_key", on_change=cb_save_settings,
                          placeholder="tvly-...")

        with st.expander("💾 Data"):
            st.download_button(
                "Download backup (JSON)",
                data=json.dumps(st.session_state.tasks, ensure_ascii=False, indent=2),
                file_name="studypilot-backup.json",
                mime="application/json",
                key="dl_backup",
            )
            if not st.session_state.tasks:
                st.button("Load demo data", key="load_demo", on_click=cb_load_demo)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def render_dashboard(plan: dict) -> None:
    ss = st.session_state
    now = today()
    summary = planner.summarize(ss.tasks, now)

    cols = st.columns(5)
    cols[0].metric("Pending", summary["pending"])
    cols[1].metric("Completed", summary["completed"])
    cols[2].metric("Overdue", summary["overdue"])
    cols[3].metric("Time left", planner.format_minutes(summary["minutes_left"]))
    cols[4].metric("Streak", f"{summary['streak']} 🔥")

    st.progress(min(max(summary["completion_pct"], 0.0), 1.0),
                text=f"Overall progress: {summary['completion_pct']:.0%}")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("💡 Coach")
        for level, text in planner.smart_tips(ss.tasks, plan, now, ss.daily_minutes):
            getattr(st, level)(text)
    with right:
        st.subheader("📅 Today's plan")
        today_plan = plan["days"][0] if plan["days"] else None
        if not today_plan or not today_plan["sessions"]:
            st.caption("Nothing scheduled for today.")
        else:
            for s in today_plan["sessions"]:
                st.write(f"{PRIORITY_ICON[s['priority']]} **{esc(s['name'])}** — "
                         f"{s['minutes']} min")
            st.caption(f"{today_plan['minutes']} of {ss.daily_minutes} min planned")

    st.subheader("📈 Last 7 days")
    week = planner.weekly_minutes(ss.tasks, now)
    labels = [d.isoformat() for d, _ in week]
    values = [m for _, m in week]
    if sum(values) == 0:
        st.caption("Log study time on an assignment or use the Focus timer to see your progress here.")
    else:
        try:
            import pandas as pd
            st.bar_chart(pd.DataFrame({"minutes": values}, index=labels))
        except ImportError:
            st.bar_chart(dict(zip(labels, values)))


# --------------------------------------------------------------------------- #
# Assignments
# --------------------------------------------------------------------------- #
def render_add_form() -> None:
    with st.expander("➕ Add an assignment", expanded=not st.session_state.tasks):
        with st.form("assignment_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            c1.text_input("Assignment name", key="new_name")
            c2.text_input("Course / subject", key="new_subject")
            st.text_area("Task Specifications / Description (Optional)", key="new_description", height=68)
            c3, c4, c5 = st.columns(3)
            c3.date_input("Due date", value=today(), key="new_due")
            c4.number_input("Estimated study time (min)", min_value=1, value=60,
                            step=15, key="new_duration")
            c5.selectbox("Priority", list(planner.PRIORITIES), index=1,
                         key="new_priority")
            st.text_area("Notes (optional)", key="new_notes", height=68)
            st.form_submit_button("Add assignment", type="primary",
                                  on_click=cb_add_task)


def render_filters(tasks: list):
    ss = st.session_state
    subjects = ["All"] + sorted({t["subject"] for t in tasks}, key=str.lower)
    if ss.get("flt_subject") not in subjects:
        ss["flt_subject"] = "All"
    c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 2])
    c1.text_input("🔍 Search", key="flt_query", placeholder="name, course or notes")
    c2.selectbox("Course", subjects, key="flt_subject")
    c3.multiselect("Priority", list(planner.PRIORITIES),
                   default=list(planner.PRIORITIES), key="flt_priority")
    c4.selectbox("Status", list(planner.STATUS_FILTERS), key="flt_status")
    c5.selectbox("Sort by", list(planner.SORT_OPTIONS), key="flt_sort")
    return planner.filter_tasks(
        tasks, today(),
        query=ss.get("flt_query", ""),
        subject=ss.get("flt_subject", "All"),
        priorities=ss.get("flt_priority"),
        status_filter=ss.get("flt_status", "All"),
        sort_by=ss.get("flt_sort", planner.SORT_OPTIONS[0]),
    )


def render_task_card(task: dict) -> None:
    ss = st.session_state
    tid = task["id"]
    now = today()
    emoji, label = planner.STATUS_LABEL[planner.status(task, now)]
    due = planner.parse_date(task["due_date"], now)
    delta = planner.days_until(task, now)
    if task["completed"]:
        when = f"due {due:%d %b %Y}"
    elif delta < 0:
        when = f"{-delta} day(s) overdue"
    elif delta == 0:
        when = "due today"
    else:
        when = f"due in {delta} day(s) ({due:%d %b})"

    with st.container(border=True):
        title = f"~~{esc(task['name'])}~~" if task["completed"] else f"**{esc(task['name'])}**"
        st.markdown(f"{emoji} {title} · {esc(task['subject'])}")
        if task.get("description"):
            st.caption(f"📋 Specifications: {task['description']}")
        st.caption(f"{label} · {when} · {PRIORITY_ICON[task['priority']]} "
                   f"{task['priority']} priority · {task['duration']} min estimated")
        if task["notes"]:
            st.caption(f"📝 {task['notes']}")
        st.progress(planner.progress_fraction(task),
                    text=f"{min(task['minutes_done'], task['duration'])}/"
                         f"{task['duration']} min")

        col_ai1, col_ai2 = st.columns([3, 1])
        with col_ai1:
            if not task.get("ai_plan"):
                if st.button("🤖 Generate AI Study Plan", key=f"ai_plan_btn_{tid}"):
                    api_key = ss.get("ai_api_key") or ai_coach.env_api_key()
                    model = ss.get("ai_model")
                    base_url = ss.get("ai_base_url")
                    
                    if not api_key or not model:
                        flash("Please configure your AI API Key and Model ID in the sidebar first.", "warning")
                    else:
                        prompt = (
                            f"Act as an expert academic advisor. Create a detailed, step-by-step study plan "
                            f"for this assignment:\n"
                            f"- Assignment: {task['name']}\n"
                            f"- Course: {task['subject']}\n"
                            f"- Description/Specifications: {task.get('description', 'None')}\n"
                            f"- Due Date: {task['due_date']}\n"
                            f"- Estimated Total Study Time: {task['duration']} minutes\n"
                            f"- Student Daily Availability: {ss.daily_minutes} minutes per day"
                        )
                        messages = [{"role": "system", "content": "You are StudyPilot, an expert academic study planner."},
                                    {"role": "user", "content": prompt}]
                        try:
                            with st.spinner("Synthesizing plan with Nemotron..."):
                                plan_text = ai_coach.chat(base_url, api_key, model, messages)
                                task["ai_plan"] = plan_text
                                persist()
                                flash(f"AI study plan generated for “{task['name']}”.")
                                st.rerun()
                        except ai_coach.AIError as exc:
                            flash(str(exc), "error")
            else:
                with st.expander("📖 View AI Study Plan"):
                    st.write(task["ai_plan"])
        
        with col_ai2:
            if task.get("ai_plan"):
                if st.button("✕ Cancel", key=f"cancel_ai_{tid}"):
                    task["ai_plan"] = None
                    persist()
                    st.rerun()

        st.divider()

        if task["completed"]:
            col_comp_acts1, col_comp_acts2 = st.columns(2)
            with col_comp_acts1:
                st.button("Reopen assignment", key=f"reopen_{tid}",
                          on_click=cb_reopen, args=(tid,))
            with col_comp_acts2:
                if st.button("🗑️ Delete", key=f"del_comp_{tid}"):
                    cb_request_delete(tid)
                    st.rerun()
            return

        if ss.pending_complete == tid:
            st.warning("Mark this assignment as completed?")
            b1, b2 = st.columns(2)
            b1.button("Confirm", key=f"confirm_{tid}", type="primary",
                      on_click=cb_confirm_complete, args=(tid,))
            b2.button("Cancel", key=f"cancel_{tid}", on_click=cb_cancel_complete)
        elif ss.pending_delete == tid:
            st.error("Delete this assignment permanently?")
            b1, b2 = st.columns(2)
            b1.button("Yes, delete", key=f"del_yes_{tid}", type="primary",
                      on_click=cb_confirm_delete, args=(tid,))
            b2.button("Cancel", key=f"del_no_{tid}", on_click=cb_cancel_delete)
        else:
            b = st.columns(5)
            b[0].button("＋15 min", key=f"l15_{tid}", on_click=cb_log, args=(tid, 15))
            b[1].button("＋30 min", key=f"l30_{tid}", on_click=cb_log, args=(tid, 30))
            b[2].button("＋60 min", key=f"l60_{tid}", on_click=cb_log, args=(tid, 60))
            b[3].button("✅ Complete", key=f"done_{tid}",
                        on_click=cb_request_complete, args=(tid,))
            b[4].button("🗑️ Delete", key=f"del_{tid}",
                        on_click=cb_request_delete, args=(tid,))

        with st.expander("✏️ Edit"):
            with st.form(f"edit_form_{tid}"):
                e1, e2 = st.columns(2)
                e1.text_input("Name", value=task["name"], key=f"e_name_{tid}")
                e2.text_input("Course", value=task["subject"], key=f"e_subject_{tid}")
                st.text_area("Specifications / Description", value=task.get("description", ""), key=f"e_description_{tid}", height=68)
                e3, e4, e5 = st.columns(3)
                e3.date_input("Due date", value=due, key=f"e_due_{tid}")
                e4.number_input("Estimated time (min)", min_value=1,
                                value=task["duration"], step=15,
                                key=f"e_duration_{tid}")
                e5.selectbox("Priority", list(planner.PRIORITIES),
                             index=planner.PRIORITIES.index(task["priority"]),
                             key=f"e_priority_{tid}")
                st.text_area("Notes", value=task["notes"], key=f"e_notes_{tid}",
                             height=68)
                st.form_submit_button("Save changes", on_click=cb_save_edit,
                                      args=(tid,))


def render_assignments() -> None:
    render_add_form()
    st.divider()
    tasks = st.session_state.tasks
    if not tasks:
        st.info("No assignments yet. Add one above, or load the demo data from the sidebar.")
        return
    visible = render_filters(tasks)
    st.caption(f"Showing {len(visible)} of {len(tasks)} assignments")
    if not visible:
        st.info("No assignments match these filters.")
    for task in visible:
        render_task_card(task)


# --------------------------------------------------------------------------- #
# Smart plan
# --------------------------------------------------------------------------- #
def render_plan(plan: dict) -> None:
    ss = st.session_state
    if not any(not t["completed"] for t in ss.tasks):
        st.info("No pending assignments — nothing to plan.")
        return

    for risk in plan["at_risk"]:
        if risk["overdue"]:
            st.error(f"🔴 **{esc(risk['name'])}** is overdue.")
        else:
            st.warning(f"⚠️ **{esc(risk['name'])}** {risk['reason']} "
                       f"(≈{risk['needed_per_day']} min/day needed).")

    c1, c2, _ = st.columns([1, 1, 4])
    c1.download_button("⬇️ Markdown", data=planner.plan_to_markdown(plan, ss.daily_minutes),
                       file_name="studypilot-plan.md", mime="text/markdown", key="dl_md")
    c2.download_button("⬇️ CSV", data=planner.plan_to_csv(plan),
                       file_name="studypilot-plan.csv", mime="text/csv", key="dl_csv")

    shown = 0
    for index, day in enumerate(plan["days"]):
        if not day["sessions"]:
            continue
        shown += 1
        title = ("Today" if index == 0 else "Tomorrow" if index == 1
                 else f"{day['date']:%A %d %b}")
        with st.expander(f"{title} — {day['minutes']} min", expanded=index == 0):
            for s in day["sessions"]:
                line = st.columns([6, 2])
                line[0].markdown(
                    f"{PRIORITY_ICON[s['priority']]} **{esc(s['name'])}** "
                    f"· {esc(s['subject'])} · {s['minutes']} min "
                    f"({s['blocks']} block{'s' if s['blocks'] != 1 else ''})")
                if index == 0:
                    line[1].button(f"✅ Done {s['minutes']} min",
                                   key=f"plan_{s['task_id']}",
                                   on_click=cb_log, args=(s["task_id"], s["minutes"]))
    if not shown:
        st.info("Nothing could be scheduled. Increase your daily availability in the sidebar.")


# --------------------------------------------------------------------------- #
# Calendar View Tab
# --------------------------------------------------------------------------- #
def render_calendar_view() -> None:
    st.title("Calendar Schedule")
    st.write("Chronological overview of all registered coursework.")
    
    status_filter = st.radio("Filter View", ["All", "Pending", "Completed"], horizontal=True, key="cal_status_filter")
    
    indexed_tasks = list(enumerate(st.session_state.tasks))
    
    if status_filter == "Pending":
        indexed_tasks = [(i, t) for i, t in indexed_tasks if not t["completed"]]
    elif status_filter == "Completed":
        indexed_tasks = [(i, t) for i, t in indexed_tasks if t["completed"]]

    sorted_tasks = sorted(indexed_tasks, key=lambda x: str(x[1]['due_date']))

    if not sorted_tasks:
        st.info("No assignments scheduled.")
        
    for index, task in sorted_tasks:
        tid = task["id"]
        status_badge = "✅ Completed" if task["completed"] else "⏳ Pending"
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{task['due_date']}** — {esc(task['name'])} (*{esc(task['subject'])}*)")
                if task.get("description"):
                    st.caption(f"Details: {task['description']}")
                st.caption(f"Priority: {task['priority']} | Duration: {task.get('duration', 60)} mins")
                st.markdown(f"Status: **{status_badge}**")
            with col2:
                if st.button("Delete", key=f"cal_delete_{tid}"):
                    cb_request_delete(tid)
                    st.rerun()


# --------------------------------------------------------------------------- #
# Focus timer
# --------------------------------------------------------------------------- #
def _timer_body() -> None:
    f = st.session_state.focus
    left = max(f["end"] - time.time(), 0) if f["running"] else f["left"]
    if f["running"] and left <= 0:
        f["running"] = False
        f["left"] = 0
        f["done"] = True
        st.rerun()
    minutes, seconds = divmod(int(left + 0.999), 60)
    st.markdown(f"<h1 style='text-align:center;font-size:4rem'>{minutes:02d}:{seconds:02d}</h1>",
                unsafe_allow_html=True)
    st.progress(min(max(1 - left / f["total"], 0.0), 1.0) if f["total"] else 0.0)


def render_timer() -> None:
    running = st.session_state.focus["running"]
    if hasattr(st, "fragment"):
        st.fragment(run_every=1 if running else None)(_timer_body)()
    else:
        _timer_body()


def render_focus() -> None:
    ss = st.session_state
    pending = [t for t in ss.tasks if not t["completed"]]
    if not pending:
        st.info("Add an assignment to start a focus session.")
        return
    ids = [t["id"] for t in pending]
    names = {t["id"]: f"{t['name']} ({t['subject']})" for t in pending}
    if ss.get("focus_task") not in ids:
        ss["focus_task"] = ids[0]
    c1, c2 = st.columns([3, 2])
    c1.selectbox("Assignment", ids, key="focus_task", format_func=lambda i: names[i])
    c2.slider("Session length (min)", 5, 90, 25, step=5, key="focus_minutes",
              on_change=cb_focus_minutes, disabled=ss.focus["running"])

    render_timer()

    f = ss.focus
    b = st.columns(3)
    if f["running"]:
        b[0].button("⏸️ Pause", key="f_pause", on_click=cb_focus_pause)
    else:
        b[0].button("▶️ Start" if not f["done"] else "▶️ Restart", key="f_start",
                    type="primary", on_click=cb_focus_start)
    b[1].button("🔄 Reset", key="f_reset", on_click=cb_focus_reset)

    if f["done"]:
        st.success(f"Session complete! Log {f['minutes']} minutes on this assignment?")
        st.button(f"Log {f['minutes']} min", key="f_log", type="primary",
                  on_click=cb_focus_log, args=(ss.focus_task,))
        if not ss.get("celebrated"):
            st.balloons()
            ss.celebrated = True
    else:
        ss.celebrated = False
    st.caption("Tip: work in focused blocks, then take a 5–10 minute break.")


# --------------------------------------------------------------------------- #
# Coach (with Tavily Web Search support)
# --------------------------------------------------------------------------- #
def render_coach(plan: dict) -> None:
    ss = st.session_state
    st.subheader("🧭 Smart tips")
    for level, text in planner.smart_tips(ss.tasks, plan, today(), ss.daily_minutes):
        getattr(st, level)(text)

    st.subheader("🤖 Ask the AI coach & Web Search")
    api_key = ss.get("ai_api_key") or ai_coach.env_api_key()
    if not api_key or not (ss.get("ai_model") or "").strip():
        st.info("To enable the AI coach, configure your AI API Key and Model ID in the sidebar.")
        return
        
    use_web = st.checkbox("Search the web with Tavily for this question", value=False)
    st.text_input("Question (optional)", key="ai_question",
                  placeholder="What should I focus on? Or ask a study question...")
                  
    if st.button("Ask coach", key="ask_ai", type="primary"):
        tavily_key = ss.get("tavily_api_key") or ai_coach.env_tavily_key()
        web_snippets = ""
        question_text = ss.get("ai_question", "")
        
        if use_web and tavily_key and question_text:
            with st.spinner("Searching the web via Tavily..."):
                web_snippets = ai_coach.search_web(question_text, tavily_key)
                
        context = ai_coach.build_context(ss.tasks, plan, today(), ss.daily_minutes, web_context=web_snippets)
        messages = ai_coach.build_messages(context, question_text)
        try:
            with st.spinner("Thinking with Nemotron..."):
                ss.ai_answer = ai_coach.chat(ss.ai_base_url, api_key, ss.ai_model, messages)
        except ai_coach.AIError as exc:
            ss.ai_answer = None
            st.error(str(exc))
    if ss.ai_answer:
        st.markdown(ss.ai_answer)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    init_state()
    ss = st.session_state

    st.title("🎓 StudyPilot")
    st.caption("Your Academic Copilot — organize assignments, plan your studies and beat procrastination.")

    if ss.flash:
        kind, message = ss.flash
        ss.flash = None
        getattr(st, kind if kind in ("success", "info", "warning", "error") else "info")(message)

    render_sidebar()
    plan = planner.build_plan(
        ss.tasks, ss.daily_minutes, today(), ss.horizon_days, ss.session_len)

    tabs = st.tabs(["📊 Dashboard", "📝 Assignments", "🗓️ Smart plan",
                    "📅 Calendar View", "⏱️ Focus", "🤖 Coach"])
    with tabs[0]:
        render_dashboard(plan)
    with tabs[1]:
        render_assignments()
    with tabs[2]:
        render_plan(plan)
    with tabs[3]:
        render_calendar_view()
    with tabs[4]:
        render_focus()
    with tabs[5]:
        render_coach(plan)


main()