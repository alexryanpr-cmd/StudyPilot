"""Persistence for StudyPilot: tasks.json and settings.json.

- Atomic writes (temp file + os.replace) so a crash can't corrupt data.
- A corrupt file is moved aside (*.corrupt-<timestamp>) instead of crashing the app.
- Old prototype tasks (no id / no progress fields) are migrated on load.
- API keys are never written to disk.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import planner

DEFAULT_SETTINGS = {
    "daily_minutes": 120,
    "session_len": 45,
    "horizon_days": 14,
    "ai_base_url": "https://api.tokenfactory.nebius.com/v1",
    "ai_model": "",
    "theme": "Light",
}


def data_dir() -> Path:
    path = Path(os.environ.get("STUDYPILOT_DATA_DIR") or ".")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(name: str, default: Any) -> Any:
    path = data_dir() / name
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path.rename(path.with_name(f"{path.name}.corrupt-{stamp}"))
        except OSError:
            pass
        return default


def _write_json(name: str, payload: Any) -> None:
    directory = data_dir()
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, directory / name)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_tasks() -> list:
    raw = _read_json("tasks.json", [])
    if not isinstance(raw, list):
        return []
    tasks = [planner.normalize_task(item) for item in raw]
    return [t for t in tasks if t is not None]


def save_tasks(tasks: list) -> None:
    _write_json("tasks.json", tasks)


def load_settings() -> dict:
    raw = _read_json("settings.json", {})
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key, default in DEFAULT_SETTINGS.items():
            value = raw.get(key, default)
            if isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
            elif not isinstance(value, str):
                value = default
            settings[key] = value
    settings["daily_minutes"] = min(max(settings["daily_minutes"], 15), 1440)
    settings["session_len"] = min(max(settings["session_len"], 15), 120)
    settings["horizon_days"] = min(max(settings["horizon_days"], 3), 60)
    return settings


def save_settings(settings: dict) -> None:
    _write_json("settings.json", {k: settings.get(k, v)
                                  for k, v in DEFAULT_SETTINGS.items()})