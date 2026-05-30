"""
Memory — Persistent user & session context
JSON-backed, survives restarts. No amnesia.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("memory")

DATA_DIR = Path("~/.cin_agent").expanduser()
MEMORY_FILE = DATA_DIR / "memory.json"
MAX_HISTORY = 50  # messages per user


def _load() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            logger.warning("Memory file corrupted, starting fresh")
    return {"users": {}, "globals": {}}


def _save(data: dict):
    MEMORY_FILE.write_text(json.dumps(data, indent=2, default=str))


# ── Public API ─────────────────────────────────────────────────────────────

def remember(user_id: int | str, key: str, value: Any):
    """Store a fact about a user."""
    data = _load()
    uid = str(user_id)
    data["users"].setdefault(uid, {"facts": {}, "history": []})
    data["users"][uid]["facts"][key] = value
    _save(data)


def recall(user_id: int | str, key: str, default=None) -> Any:
    """Retrieve a stored fact about a user."""
    data = _load()
    uid = str(user_id)
    return data["users"].get(uid, {}).get("facts", {}).get(key, default)


def add_history(user_id: int | str, role: str, content: str):
    """Append a message to user's conversation history."""
    data = _load()
    uid = str(user_id)
    data["users"].setdefault(uid, {"facts": {}, "history": []})
    history = data["users"][uid]["history"]
    history.append({
        "role": role,
        "content": content,
        "ts": datetime.now().isoformat(),
    })
    # Trim to max
    if len(history) > MAX_HISTORY:
        data["users"][uid]["history"] = history[-MAX_HISTORY:]
    _save(data)


def get_history(user_id: int | str, n: int = 10) -> list[dict]:
    """Get last n messages for a user (without timestamps, for LLM context)."""
    data = _load()
    uid = str(user_id)
    history = data["users"].get(uid, {}).get("history", [])
    return [{"role": h["role"], "content": h["content"]} for h in history[-n:]]


def get_user_profile(user_id: int | str) -> dict:
    """Get everything known about a user."""
    data = _load()
    uid = str(user_id)
    return data["users"].get(uid, {"facts": {}, "history": []})


def set_global(key: str, value: Any):
    data = _load()
    data["globals"][key] = value
    _save(data)


def get_global(key: str, default=None) -> Any:
    data = _load()
    return data["globals"].get(key, default)


def clear_user_history(user_id: int | str):
    data = _load()
    uid = str(user_id)
    if uid in data["users"]:
        data["users"][uid]["history"] = []
    _save(data)
