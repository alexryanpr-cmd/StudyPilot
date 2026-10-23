# StudyPilot 🎓

**Your Academic Copilot**

StudyPilot is a project in development designed to help university students organize assignments, plan their studies, and overcome procrastination.

## 🎯 Project Goal

Help students manage their academic workload through organized planning, smaller study sessions, and progress tracking.

## 🛠️ Technologies

- Python
- Streamlit
- NVIDIA Nemotron (planned integration)
- Nebius Token Factory (planned integration)

## ✅ Current Features

- Initial web interface in English.
- Assignment creation form.
- Assignment name, course, due date, and priority fields.
- Form fields clear after submission.
- Pending and completed assignments displayed separately.
- Confirmation before marking an assignment as completed.
- Option to reopen completed assignments.

## 🚧 Current Status

StudyPilot currently has a functional prototype for creating and managing assignments during an active Streamlit session.

**Note:** Assignments are not yet saved permanently. Data persistence, intelligent study planning, progress tracking, and AI integration remain future development goals.

## ▶️ Run Locally

1. Clone the repository.
2. Create a virtual environment:

   `python -m venv .venv`

3. Activate the environment on Windows PowerShell:

   `.\.venv\Scripts\Activate.ps1`

   If PowerShell blocks script execution, run the application directly through the virtual environment's Python executable instead.

4. Install Streamlit:

   `python -m pip install streamlit`

5. Start the application:

   `python -m streamlit run app.py`

## 📌 Project Context

StudyPilot is being developed as part of a hackathon project. Features and technologies will be added incrementally as development progresses.