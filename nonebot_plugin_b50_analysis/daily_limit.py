from __future__ import annotations

import json
from datetime import date

from .paths import DATA_DIR

_LIMIT_FILE = DATA_DIR / "daily_usage.json"


def _load() -> dict:
    if not _LIMIT_FILE.exists():
        return {}
    try:
        data = json.loads(_LIMIT_FILE.read_text("utf-8"))
    except Exception:
        return {}
    today = date.today().isoformat()
    if today in data:
        return data
    return {}


def _save(data: dict) -> None:
    _LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LIMIT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def get_today_usage(user_id: str) -> int:
    data = _load()
    today = date.today().isoformat()
    day_data = data.get(today, {})
    return int(day_data.get(str(user_id), 0))


def increment_usage(user_id: str) -> int:
    data = _load()
    today = date.today().isoformat()
    if today not in data:
        data[today] = {}
    day_data = data[today]
    uid = str(user_id)
    day_data[uid] = int(day_data.get(uid, 0)) + 1
    _save(data)
    return day_data[uid]


def reset_user(user_id: str) -> None:
    data = _load()
    today = date.today().isoformat()
    if today in data:
        data[today].pop(str(user_id), None)
        _save(data)
