
import json
import streamlit as st

st.set_page_config(
    page_title="StudyPilot",
    page_icon="🎓",
    layout="centered",
)

def load_tasks():
    try:
        with open("tasks.json", "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return []


def save_tasks():
    with open("tasks.json", "w", encoding="utf-8") as file:
        json.dump(
            st.session_state.tasks,
            file,
            ensure_ascii=False,
            indent=4,
            default=str,
        )

def load_settings():
    try:
        with open("settings.json", "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {"daily_minutes": 120}


def save_settings(settings):
    with open("settings.json", "w", encoding="utf-8") as file:
        json.dump(
            settings,
            file,
            ensure_ascii=False,
            indent=4,
        )

def save_daily_availability():
    save_settings({
        "daily_minutes": st.session_state.daily_minutes
    })

if "tasks" not in st.session_state:
    st.session_state.tasks = load_tasks()

if "settings" not in st.session_state:
    st.session_state.settings = load_settings()

if "daily_minutes" not in st.session_state:
    st.session_state.daily_minutes = st.session_state.settings.get(
        "daily_minutes", 120
    )

if "pending_confirmation" not in st.session_state:
    st.session_state.pending_confirmation = None

st.title("🎓 StudyPilot")
st.subheader("Your Academic Copilot")

st.divider()
st.header("🕒 Study Availability")

daily_minutes = st.number_input(
    "How many minutes can you study per day?",
    min_value=15,
    max_value=1440,
    step=15,
    key="daily_minutes",
    on_change=save_daily_availability,
    )

st.write(
    "Organize your assignments, overcome procrastination, "
    "and plan your studies with the help of AI."
)

st.divider()
st.header("📝 Add an Assignment")

with st.form("assignment_form", clear_on_submit=True):
    name = st.text_input("Assignment Name")
    subject = st.text_input("Course / Subject")
    due_date = st.date_input("Due Date")
    duration = st.number_input(
        "Estimated Study Time (minutes)",
        min_value=1,
        value=60,
        step=15,
        )
    priority = st.selectbox(
        "Priority",
        ["Low", "Medium", "High"],
    )

    submitted = st.form_submit_button("Add Assignment")

if submitted:
    if name.strip() and subject.strip():
        st.session_state.tasks.append({
            "name": name.strip(),
            "subject": subject.strip(),
            "due_date": due_date,
            "duration": duration,
            "priority": priority,
            "completed": False,
        })

        save_tasks()

        st.success("Assignment added successfully!")
    else:
        st.warning(
            "Please enter both the assignment name and the course."
        )

st.divider()
st.header("📚 My Assignments")

pending_tasks = [
    (i, task)
    for i, task in enumerate(st.session_state.tasks)
    if not task["completed"]
]

completed_tasks = [
    (i, task)
    for i, task in enumerate(st.session_state.tasks)
    if task["completed"]
]

st.subheader(f"⏳ Pending ({len(pending_tasks)})")

if not pending_tasks:
    st.info("No pending assignments. Great job!")

for index, task in pending_tasks:
    with st.container(border=True):
        st.write(f"**{task['name']}**")
        st.write(f"Course: {task['subject']}")
        st.write(f"Due date: {task['due_date']}")
        st.write(f"Estimated study time: {task.get('duration', 'Not specified')} minutes")
        st.write(f"Priority: {task['priority']}")

        if st.session_state.pending_confirmation == index:
            st.warning(
                "Are you sure you want to mark this assignment "
                "as completed?"
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button(
                    "Confirm",
                    key=f"confirm_{index}",
                    type="primary",
                ):
                    task["completed"] = True
                    save_tasks()
                    st.session_state.pending_confirmation = None
                    st.rerun()

            with col2:
                if st.button("Cancel", key=f"cancel_{index}"):
                    st.session_state.pending_confirmation = None
                    st.rerun()

        else:
            if st.button(
                "Mark as Completed",
                key=f"complete_{index}",
            ):
                st.session_state.pending_confirmation = index
                st.rerun()

st.divider()
st.subheader(f"✅ Completed ({len(completed_tasks)})")

if not completed_tasks:
    st.caption("Completed assignments will appear here.")

for index, task in completed_tasks:
    with st.container(border=True):
        st.write(f"~~{task['name']}~~")
        st.write(f"Course: {task['subject']}")
        st.write(f"Due date: {task['due_date']}")
        st.write(f"Estimated study time: {task.get('duration', 'Not specified')} minutes")
        st.write(f"Priority: {task['priority']}")

        if st.button("Reopen Assignment", key=f"reopen_{index}"):
            task["completed"] = False
            save_tasks()
            st.rerun()
