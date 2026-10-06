"""Historial de conversaciones e idempotencia en SQLite."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_messages (
    id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    wa_id TEXT PRIMARY KEY,
    name TEXT,
    handoff INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    body TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_wa ON messages (wa_id, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    """Acceso a SQLite; abre una conexión corta por operación."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def claim_message(self, message_id: str) -> bool:
        """True si es la primera vez que se ve este id (idempotencia)."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO processed_messages (id, received_at) VALUES (?, ?)",
                (message_id, _now()),
            )
            return cur.rowcount == 1

    def add_message(
        self,
        wa_id: str,
        direction: str,
        body: str,
        source: str | None = None,
        name: str | None = None,
    ) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO conversations (wa_id, name) VALUES (?, ?) "
                "ON CONFLICT(wa_id) DO UPDATE SET name = COALESCE(excluded.name, name)",
                (wa_id, name),
            )
            conn.execute(
                "INSERT INTO messages (wa_id, direction, body, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (wa_id, direction, body, source, _now()),
            )

    def set_handoff(self, wa_id: str, value: bool = True) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE conversations SET handoff = ? WHERE wa_id = ?", (int(value), wa_id)
            )

    def is_handoff(self, wa_id: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT handoff FROM conversations WHERE wa_id = ?", (wa_id,)
            ).fetchone()
        return bool(row and row["handoff"])

    def history(self, wa_id: str, limit: int = 10) -> list[dict[str, str]]:
        """Últimos mensajes en formato de chat (role/content), del más viejo al más nuevo."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT direction, body FROM messages WHERE wa_id = ? ORDER BY id DESC LIMIT ?",
                (wa_id, limit),
            ).fetchall()
        return [
            {"role": "user" if r["direction"] == "in" else "assistant", "content": r["body"]}
            for r in reversed(rows)
        ]

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT c.wa_id, c.name, c.handoff, COUNT(m.id) AS message_count, "
                "MAX(m.created_at) AS last_message_at "
                "FROM conversations c LEFT JOIN messages m ON m.wa_id = c.wa_id "
                "GROUP BY c.wa_id ORDER BY MAX(m.id) DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [{**dict(r), "handoff": bool(r["handoff"])} for r in rows]

    def conversation_messages(self, wa_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT direction, body, source, created_at FROM messages "
                "WHERE wa_id = ? ORDER BY id",
                (wa_id,),
            ).fetchall()
        return [dict(r) for r in rows]
