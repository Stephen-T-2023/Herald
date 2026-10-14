"""
Herald — Daily Briefing
Ashborne / ashborne.dev

Triggered by: "good morning", "morning briefing", "daily briefing"
Covers: time/date, weather (multiple cities), reminders, news headlines
"""

import os
import json
import threading
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REMINDERS_FILE = Path(__file__).parent / "reminders.json"
_lock          = threading.Lock()

# ── Reminders storage ──────────────────────────────────────────────────────────
def _load_reminders() -> list:
    if not REMINDERS_FILE.exists():
        return []
    try:
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_reminders(reminders: list):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, indent=2, ensure_ascii=False)

def add_reminder(text: str, remind_date: str) -> str:
    """Add a reminder for a specific date. remind_date format: YYYY-MM-DD"""
    with _lock:
        reminders = _load_reminders()
        reminders.append({
            "text":        text,
            "date":        remind_date,
            "created_at":  datetime.now().isoformat(),
        })
        _save_reminders(reminders)
    return f"Reminder set for {remind_date}: {text}"

def get_todays_reminders() -> list:
    """Return reminders due today or overdue."""
    with _lock:
        reminders  = _load_reminders()
        today      = date.today().isoformat()
        due        = [r for r in reminders if r["date"] <= today]
        remaining  = [r for r in reminders if r["date"] > today]
        _save_reminders(remaining)  # remove due ones
        return due

def list_reminders() -> list:
    with _lock:
        return _load_reminders()

def delete_reminder(query: str) -> str:
    with _lock:
        reminders = _load_reminders()
        query_l   = query.lower()
        filtered  = [r for r in reminders if query_l not in r["text"].lower()]
        removed   = len(reminders) - len(filtered)
        _save_reminders(filtered)
        return f"Removed {removed} reminder(s)." if removed else f"No reminders matching '{query}'."


# ── Weather ────────────────────────────────────────────────────────────────────
def get_weather(city: str) -> str:
    api_key = os.getenv("OPENWEATHER_API_KEY", "")
    if not api_key:
        return "Weather unavailable — OPENWEATHER_API_KEY not set."
    try:
        encoded = urllib.parse.quote(city)
        url     = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={encoded}&appid={api_key}&units=metric"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            data    = json.loads(resp.read())
        desc    = data["weather"][0]["description"].capitalize()
        temp    = data["main"]["temp"]
        feels   = data["main"]["feels_like"]
        humidity= data["main"]["humidity"]
        city_name = data["name"]
        return (
            f"{city_name}: {desc}, {temp:.0f}°C "
            f"(feels like {feels:.0f}°C), humidity {humidity}%"
        )
    except Exception as e:
        return f"Weather unavailable for {city}: {e}"


def get_all_weather() -> str:
    cities_raw = os.getenv("WEATHER_CITIES", "London,UK")
    cities     = [c.strip() for c in cities_raw.split(";") if c.strip()]
    results    = [get_weather(c) for c in cities]
    return "\n".join(results)


# ── News headlines ─────────────────────────────────────────────────────────────
def get_news_headlines(max_headlines: int = 5) -> str:
    try:
        import xml.etree.ElementTree as ET
        url = "https://feeds.bbci.co.uk/news/rss.xml"
        req = urllib.request.Request(url, headers={"User-Agent": "Herald/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            tree  = ET.parse(resp)
            root  = tree.getroot()
            items = root.findall(".//item")[:max_headlines]
            headlines = []
            for item in items:
                title = item.find("title")
                if title is not None and title.text:
                    headlines.append(f"- {title.text.strip()}")
        if not headlines:
            return "No headlines available."
        return "\n".join(headlines)
    except Exception as e:
        return f"News unavailable: {e}"


# ── Full briefing ──────────────────────────────────────────────────────────────
def get_briefing() -> str:
    now      = datetime.now()
    time_str = now.strftime("%I:%M %p").lstrip("0")
    date_str = now.strftime("%A, %B %d %Y")

    sections = []

    # Time and date
    sections.append(f"Good morning. It is {time_str} on {date_str}.")

    # Weather
    weather = get_all_weather()
    sections.append(f"Weather:\n{weather}")

    # Reminders due today
    due = get_todays_reminders()
    if due:
        reminder_lines = "\n".join(f"- {r['text']}" for r in due)
        sections.append(f"Reminders due today:\n{reminder_lines}")
    else:
        sections.append("No reminders due today.")

    # News
    headlines = get_news_headlines()
    sections.append(f"Top headlines:\n{headlines}")

    return "\n\n".join(sections)
