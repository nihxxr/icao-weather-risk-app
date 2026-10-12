"""Tiny JSON file user store. Fine for a demo; swap for a database in production."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

HISTORY_LIMIT = 12
_lock = threading.Lock()


class UserStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text() or "{}")
        # Older versions stored {username: password_hash}
        return {u: (v if isinstance(v, dict) else {"password": v, "history": []}) for u, v in data.items()}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.path)

    def create(self, username: str, password: str) -> bool:
        with _lock:
            data = self._load()
            if username in data:
                return False
            data[username] = {"password": generate_password_hash(password), "history": []}
            self._save(data)
            return True

    def verify(self, username: str, password: str) -> bool:
        user = self._load().get(username)
        return bool(user) and check_password_hash(user["password"], password)

    def history(self, username: str) -> list:
        return (self._load().get(username) or {}).get("history", [])

    def record(self, username: str, station: str, level: str, category: str) -> None:
        with _lock:
            data = self._load()
            user = data.get(username)
            if not user:
                return
            entry = {"station": station, "level": level, "category": category,
                     "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")}
            hist = [h for h in user.get("history", []) if h["station"] != station]
            user["history"] = [entry, *hist][:HISTORY_LIMIT]
            self._save(data)
