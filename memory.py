"""
Herald — Persistent Memory
Ashborne / ashborne.dev

Stores and retrieves memories across sessions.
Triggered explicitly by the user saying "remember that..."
Memories persist until explicitly deleted.

Storage: memories.json in the Herald directory
"""

import os
import json
import threading
from datetime import datetime
from pathlib import Path


MEMORY_FILE = Path(__file__).parent / "memories.json"
_lock       = threading.Lock()


# ── Core storage ───────────────────────────────────────────────────────────────
def _load() -> dict:
    if not MEMORY_FILE.exists():
        return {"memories": []}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"memories": []}


def _save(data: dict):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Public API ─────────────────────────────────────────────────────────────────
def add_memory(content: str) -> str:
    with _lock:
        data = _load()
        entry = {
            "id":         len(data["memories"]) + 1,
            "content":    content,
            "created_at": datetime.now().isoformat(),
        }
        data["memories"].append(entry)
        _save(data)
    return f"Remembered: {content}"


def get_all_memories() -> list:
    with _lock:
        return _load().get("memories", [])


def forget_memory(query: str) -> str:
    """Remove memories matching the query."""
    with _lock:
        data  = _load()
        mems  = data.get("memories", [])
        query = query.lower().strip()

        if query in ("all", "everything"):
            data["memories"] = []
            _save(data)
            return "All memories cleared."

        original_len = len(mems)
        data["memories"] = [
            m for m in mems
            if query not in m["content"].lower()
        ]
        removed = original_len - len(data["memories"])
        _save(data)

        if removed:
            return f"Forgot {removed} memory entry."
        return f"No memories found matching '{query}'."


def format_memories_for_prompt() -> str:
    """Return memories as a block to inject into Claude's system prompt."""
    mems = get_all_memories()
    if not mems:
        return ""
    lines = ["The following are things the user has explicitly asked you to remember:"]
    for m in mems:
        lines.append(f"- {m['content']}")
    return "\n".join(lines)
