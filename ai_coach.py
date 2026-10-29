"""Optional AI coach for StudyPilot with Tavily web search integration.

Talks to any OpenAI-compatible /chat/completions endpoint (e.g. Nebius Token
Factory serving an NVIDIA Nemotron model) and integrates Tavily for live web research.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from typing import Callable, Optional

from tavily import TavilyClient
import planner

SYSTEM_PROMPT = (
    "You are StudyPilot, a concise, encouraging academic coach for university "
    "students. Use the assignment data and any web search results provided. "
    "Give a short, concrete, prioritised action plan or explanation (max ~200 words). "
    "Do not invent assignments or deadlines. Reply in the language of the student's question."
)


class AIError(Exception):
    """Raised for any problem talking to the AI provider (message is user-safe)."""


def env_api_key() -> str:
    return os.environ.get("STUDYPILOT_AI_API_KEY") or os.environ.get("NEBIUS_API_KEY") or ""


def env_tavily_key() -> str:
    return os.environ.get("TAVILY_API_KEY") or ""


def search_web(query: str, tavily_key: str) -> str:
    """Perform a live web search using Tavily API to assist with coursework."""
    if not tavily_key:
        return ""
    try:
        client = TavilyClient(api_key=tavily_key)
        response = client.search(query=query, max_results=3)
        results = response.get("results", [])
        snippets = [f"- {r.get('title')}: {r.get('content')} ({r.get('url')})" for r in results]
        return "\n".join(snippets)
    except Exception:
        return ""


def build_context(tasks: list, plan: dict, today: date, daily_minutes: int, web_context: str = "") -> str:
    lines = [f"Today: {today.isoformat()}", f"Daily study availability: {daily_minutes} min", ""]
    pending = [t for t in tasks if not t["completed"]]
    if not pending:
        lines.append("No pending assignments.")
    for t in sorted(pending, key=lambda x: -planner.urgency_score(x, today))[:15]:
        lines.append(
            f"- {t['name']} | course: {t['subject']} | due: {t['due_date']} "
            f"({planner.days_until(t, today)} days) | priority: {t['priority']} | "
            f"remaining: {planner.remaining_minutes(t)} of {t['duration']} min"
        )
    if plan["at_risk"]:
        lines.append("")
        lines.append("At risk: " + "; ".join(f"{r['name']} ({r['reason']})" for r in plan["at_risk"][:5]))
    
    if web_context:
        lines.append("\nLive Web Search Results (via Tavily):")
        lines.append(web_context)
        
    return "\n".join(lines)


def build_messages(context: str, question: str = "") -> list:
    question = (question or "").strip() or "What should I focus on today and this week?"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{context}\n\nStudent question: {question[:500]}"},
    ]


def chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list,
    timeout: int = 45,
    max_tokens: int = 700,
    opener: Optional[Callable] = None,
) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url.startswith(("https://", "http://")):
        raise AIError("The AI base URL must start with https:// (or http://).")
    if not api_key:
        raise AIError("No API key configured.")
    if not (model or "").strip():
        raise AIError("No model id configured. Copy it from your provider's model catalog.")

    body = json.dumps({
        "model": model.strip(),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
    )
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        hint = {401: "invalid API key", 403: "access denied", 404: "model or URL not found",
                429: "rate limit reached"}.get(exc.code, "request failed")
        raise AIError(f"AI provider returned HTTP {exc.code} ({hint}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AIError("Could not reach the AI provider (network error or timeout).") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AIError("The AI provider returned an unreadable response.") from None

    try:
        text = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise AIError("The AI provider response had an unexpected format.") from None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if not text:
        raise AIError("The AI provider returned an empty answer.")
    return text