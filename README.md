# StudyPilot 🎓

**Your Academic Copilot** — organize assignments, build a realistic study plan and beat procrastination.

## ✨ Features

- **Dashboard**: pending / completed / overdue counters, time left, study streak 🔥, overall progress, last-7-days chart and coach alerts.
- **Assignments**: add, edit, delete (with confirmation), complete / reopen, per-assignment progress, quick **＋15/30/60 min** study logging (auto-completes when the estimate is reached), notes, duplicate and past-date warnings.
- **Search, filter & sort**: by text, course, priority, status; sort by urgency, due date, priority, course or newest.
- **Smart plan**: a day-by-day schedule that ranks tasks by urgency (priority + deadline), splits long work into blocks, **never exceeds your daily minutes**, flags tasks that are at risk of missing their deadline, logs a session with one click and exports to Markdown / CSV.
- **Focus timer**: live countdown (Pomodoro style) tied to an assignment; log the session when it ends.
- **Coach**: offline tips that always work, plus an optional **AI coach** (any OpenAI-compatible endpoint — built for Nebius Token Factory + NVIDIA Nemotron).
- **Persistent & safe storage**: `tasks.json` / `settings.json` (atomic writes, corrupt-file recovery, automatic migration of data from the first prototype). Backup download in the sidebar.

## ▶️ Run locally

```bash
python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Click **Load demo data** in the sidebar to see everything working right away.

## 🤖 Optional AI coach

The app works fully without it. To enable it, open **🤖 AI coach** in the sidebar (or set environment variables):

| Variable | Meaning |
| --- | --- |
| `STUDYPILOT_AI_API_KEY` (or `NEBIUS_API_KEY`) | API key — never written to disk |
| `STUDYPILOT_AI_BASE_URL` | default `https://api.tokenfactory.nebius.com/v1` |
| `STUDYPILOT_AI_MODEL` | model id exactly as shown in your provider's catalog (e.g. a Nemotron model) |

## 🧪 Tests

```bash
python -m unittest discover -v
```

Covers the planner (including randomized invariants), storage, the AI client (mocked) and full user flows of `app.py`. `tests/test_app_streamlit.py` runs the app on the real Streamlit runtime (`AppTest`) and is skipped if Streamlit isn't installed.

## 🗂️ Structure

| File | Role |
| --- | --- |
| `app.py` | Streamlit UI |
| `planner.py` | Pure logic: urgency, plan, filters, stats, exports |
| `storage.py` | JSON persistence and migration |
| `ai_coach.py` | Optional AI client (standard library only) |
| `tests/` | Unit and flow tests |

## 🚧 Roadmap

Calendar (.ics) export, PDF/slides import to generate assignments, spaced-repetition reviews, multi-user accounts.

*Hackathon project — built with Python, Streamlit, NVIDIA Nemotron and Nebius Token Factory.*
