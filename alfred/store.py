"""SQLite storage: preferences/memory, conversation history, proposals, shopping list, seen items, audit log."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY, member_id TEXT, category TEXT, fact TEXT, source TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY, member_id TEXT, role TEXT, text TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, summary TEXT, status TEXT,
    proposed_to TEXT, created TEXT, decided_by TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS shopping (
    id INTEGER PRIMARY KEY, item TEXT, shop TEXT, note TEXT, done INTEGER DEFAULT 0, created TEXT
);
CREATE TABLE IF NOT EXISTS seen (
    key TEXT PRIMARY KEY, created TEXT
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, value TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, actor TEXT, action TEXT, detail TEXT, ok INTEGER, created TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # ---- memory / preferences -------------------------------------------------
    def remember(self, member_id: str, category: str, fact: str, source: str = "chat") -> int:
        return self._exec(
            "INSERT INTO memory (member_id, category, fact, source, created) VALUES (?,?,?,?,?)",
            (member_id, category, fact, source, _now()),
        ).lastrowid

    def recall(self, member_id: str | None = None, query: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM memory WHERE 1=1", []
        if member_id:
            sql += " AND (member_id = ? OR member_id = 'family')"
            args.append(member_id)
        if query:
            sql += " AND (fact LIKE ? OR category LIKE ?)"
            args += [f"%{query}%", f"%{query}%"]
        return self._all(sql + " ORDER BY id", tuple(args))

    def forget(self, fact_id: int, member_id: str) -> bool:
        cur = self._exec("DELETE FROM memory WHERE id = ? AND (member_id = ? OR member_id = 'family')",
                         (fact_id, member_id))
        return cur.rowcount > 0

    # ---- conversation history (plain text only) -------------------------------
    def add_history(self, member_id: str, role: str, text: str) -> None:
        self._exec("INSERT INTO history (member_id, role, text, created) VALUES (?,?,?,?)",
                   (member_id, role, text, _now()))

    def history(self, member_id: str, limit: int = 12) -> list[dict]:
        rows = self._all("SELECT role, text FROM history WHERE member_id = ? ORDER BY id DESC LIMIT ?",
                         (member_id, limit))
        return list(reversed(rows))

    # ---- proposals (things that need a family member's "yes") -----------------
    def add_proposal(self, kind: str, payload: dict, summary: str, proposed_to: str = "family") -> int:
        return self._exec(
            "INSERT INTO proposals (kind, payload, summary, status, proposed_to, created) VALUES (?,?,?,?,?,?)",
            (kind, json.dumps(payload), summary, "pending", proposed_to, _now()),
        ).lastrowid

    def pending_proposals(self, max_age_hours: int = 72) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        rows = self._all("SELECT * FROM proposals WHERE status = 'pending' AND created >= ? ORDER BY id",
                         (cutoff,))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def decide_proposal(self, proposal_id: int, status: str, member_id: str) -> None:
        self._exec("UPDATE proposals SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                   (status, member_id, _now(), proposal_id))

    # ---- shopping list -------------------------------------------------------
    def add_shopping(self, item: str, shop: str | None = None, note: str | None = None) -> int:
        return self._exec("INSERT INTO shopping (item, shop, note, created) VALUES (?,?,?,?)",
                          (item, shop or "", note or "", _now())).lastrowid

    def shopping_list(self) -> list[dict]:
        return self._all("SELECT id, item, shop, note FROM shopping WHERE done = 0 ORDER BY shop, id")

    def tick_off(self, ids: list[int]) -> int:
        n = 0
        for i in ids:
            n += self._exec("UPDATE shopping SET done = 1 WHERE id = ?", (i,)).rowcount
        return n

    # ---- seen items (dedupe alerts) & cache ----------------------------------
    def seen_before(self, key: str) -> bool:
        """Returns True if key was already seen; otherwise records it and returns False."""
        with self._lock:
            row = self.db.execute("SELECT 1 FROM seen WHERE key = ?", (key,)).fetchone()
            if row:
                return True
            self.db.execute("INSERT INTO seen (key, created) VALUES (?, ?)", (key, _now()))
            self.db.commit()
            return False

    def cache_get(self, key: str, max_age_hours: float) -> object | None:
        rows = self._all("SELECT value, created FROM cache WHERE key = ?", (key,))
        if not rows:
            return None
        if datetime.fromisoformat(rows[0]["created"]) < datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
            return None
        return json.loads(rows[0]["value"])

    def cache_set(self, key: str, value: object) -> None:
        self._exec("INSERT OR REPLACE INTO cache (key, value, created) VALUES (?,?,?)",
                   (key, json.dumps(value), _now()))

    # ---- audit log -----------------------------------------------------------
    def audit(self, actor: str, action: str, detail: str, ok: bool = True) -> None:
        self._exec("INSERT INTO audit (actor, action, detail, ok, created) VALUES (?,?,?,?,?)",
                   (actor, action, detail[:2000], int(ok), _now()))

    def audit_since(self, hours: int = 24) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        return self._all("SELECT actor, action, detail, ok, created FROM audit WHERE created >= ? ORDER BY id",
                         (cutoff,))

    def purge_old(self, days: int = 90) -> None:
        """Retention: drop old conversation text and audit details."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        self._exec("DELETE FROM history WHERE created < ?", (cutoff,))
        self._exec("DELETE FROM audit WHERE created < ?", (cutoff,))
        self._exec("DELETE FROM cache WHERE created < ?", (cutoff,))
