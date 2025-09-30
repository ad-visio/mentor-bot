from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import aiosqlite
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")


@dataclass(slots=True)
class Reminder:
    id: int
    chat_id: int
    user_id: int
    text: str
    event_ts_utc: datetime
    created_utc: datetime
    archived: int

@dataclass(slots=True)
class Alert:
    id: int
    reminder_id: int
    fire_ts_utc: datetime
    fired: int

@dataclass(slots=True)
class Task:
    id: int
    chat_id: int
    user_id: int
    text: str
    created_utc: datetime
    archived: int

@dataclass(slots=True)
class ShoppingItem:
    id: int
    chat_id: int
    user_id: int
    text: str
    created_utc: datetime
    archived: int

@dataclass(slots=True)
class Ritual:
    id: int
    chat_id: int
    user_id: int
    text: str
    created_utc: datetime


class DBManager:
    def __init__(self, db_path: Path):
        self.db_path = str(db_path)

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS reminders(
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    user_id INTEGER,
                    text TEXT,
                    event_ts_utc TEXT,
                    created_utc TEXT,
                    archived INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS alerts(
                    id INTEGER PRIMARY KEY,
                    reminder_id INTEGER REFERENCES reminders(id) ON DELETE CASCADE,
                    fire_ts_utc TEXT,
                    fired INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS tasks(
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    user_id INTEGER,
                    text TEXT,
                    created_utc TEXT,
                    archived INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS shopping(
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    user_id INTEGER,
                    text TEXT,
                    created_utc TEXT,
                    archived INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS rituals(
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    user_id INTEGER,
                    text TEXT,
                    created_utc TEXT
                );
                """
            )
            await db.commit()

    # -------- reminders
    async def create_reminder(
        self,
        chat_id: int,
        user_id: int,
        text: str,
        event_ts_utc: datetime,
        created_utc: datetime,
        alert_times_utc: Sequence[datetime],
    ) -> Tuple[Reminder, List[Alert]]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO reminders(chat_id,user_id,text,event_ts_utc,created_utc)
                VALUES(?,?,?,?,?)
                """,
                (chat_id, user_id, text, event_ts_utc.isoformat(), created_utc.isoformat()),
            )
            reminder_id = cur.lastrowid
            await cur.close()

            alerts: List[Alert] = []
            for t in alert_times_utc:
                c = await db.execute(
                    "INSERT INTO alerts(reminder_id, fire_ts_utc) VALUES(?,?)",
                    (reminder_id, t.isoformat()),
                )
                alerts.append(
                    Alert(id=c.lastrowid, reminder_id=reminder_id, fire_ts_utc=t, fired=0)
                )
                await c.close()

            await db.commit()

            r = Reminder(
                id=reminder_id,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                event_ts_utc=event_ts_utc,
                created_utc=created_utc,
                archived=0,
            )
            return r, alerts

    async def get_reminders_for_range(
        self,
        chat_id: int,
        user_id: int,
        start_utc: Optional[datetime],
        end_utc: Optional[datetime],
        archived: bool,
    ) -> List[Reminder]:
        q = "SELECT id, chat_id, user_id, text, event_ts_utc, created_utc, archived FROM reminders WHERE chat_id=? AND user_id=? AND archived=?"
        params: list = [chat_id, user_id, 1 if archived else 0]
        if start_utc is not None:
            q += " AND event_ts_utc >= ?"
            params.append(start_utc.isoformat())
        if end_utc is not None:
            q += " AND event_ts_utc < ?"
            params.append(end_utc.isoformat())
        q += " ORDER BY event_ts_utc ASC"

        out: List[Reminder] = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(q, params) as cur:
                async for row in cur:
                    out.append(
                        Reminder(
                            id=row[0],
                            chat_id=row[1],
                            user_id=row[2],
                            text=row[3],
                            event_ts_utc=datetime.fromisoformat(row[4]).replace(tzinfo=UTC),
                            created_utc=datetime.fromisoformat(row[5]).replace(tzinfo=UTC),
                            archived=row[6],
                        )
                    )
        return out
    async def get_pending_alerts(self, now_utc: datetime) -> list[Alert]:
        """
        Вернёт все НЕотправленные алерты (alerts.fired=0), которые ещё впереди (ts_utc > now_utc).
        """
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """
            SELECT a.id, a.reminder_id, a.ts_utc, a.fired
            FROM alerts a
            JOIN reminders r ON r.id = a.reminder_id
            WHERE a.fired = 0
              AND a.ts_utc > ?
            ORDER BY a.ts_utc ASC
            """,
            (now_utc.isoformat(),),
        )
        result: list[Alert] = []
        for row in rows:
            result.append(
                Alert(
                    id=row["id"],
                    reminder_id=row["reminder_id"],
                    ts_utc=datetime.fromisoformat(row["ts_utc"]).replace(tzinfo=UTC),
                    fired=bool(row["fired"]),
                )
            )
        return result

    async def get_tasks(self, chat_id: int, user_id: int, limit: int = 50) -> list[dict]:
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """
            SELECT id, text, created_utc, archived
            FROM tasks
            WHERE chat_id = ? AND user_id = ? AND archived = 0
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, user_id, limit),
        )
        return [dict(row) for row in rows]

    async def get_shopping_list(self, chat_id: int, user_id: int, limit: int = 100) -> list[dict]:
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """
            SELECT id, text, created_utc, archived
            FROM shopping
            WHERE chat_id = ? AND user_id = ? AND archived = 0
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, user_id, limit),
        )
        return [dict(row) for row in rows]

    async def archive_shopping_item(self, item_id: int) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE shopping SET archived = 1 WHERE id = ?",
            (item_id,),
        )
        await self._db.commit()

    async def get_rituals(self, chat_id: int, user_id: int, limit: int = 50) -> list[dict]:
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """
            SELECT id, text, created_utc
            FROM rituals
            WHERE chat_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, user_id, limit),
        )
        return [dict(row) for row in rows]

    async def get_reminder(self, reminder_id: int) -> Optional[Reminder]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, chat_id, user_id, text, event_ts_utc, created_utc, archived FROM reminders WHERE id=?",
                (reminder_id,),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return Reminder(
                    id=row[0],
                    chat_id=row[1],
                    user_id=row[2],
                    text=row[3],
                    event_ts_utc=datetime.fromisoformat(row[4]).replace(tzinfo=UTC),
                    created_utc=datetime.fromisoformat(row[5]).replace(tzinfo=UTC),
                    archived=row[6],
                )

    async def archive_reminder(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE reminders SET archived=1 WHERE id=?", (reminder_id,))
            await db.commit()

    async def add_alerts(self, reminder_id: int, when_list_utc: Sequence[datetime]) -> List[Alert]:
        alerts: List[Alert] = []
        async with aiosqlite.connect(self.db_path) as db:
            for t in when_list_utc:
                cur = await db.execute(
                    "INSERT INTO alerts(reminder_id, fire_ts_utc) VALUES(?,?)",
                    (reminder_id, t.isoformat()),
                )
                alerts.append(Alert(id=cur.lastrowid, reminder_id=reminder_id, fire_ts_utc=t, fired=0))
                await cur.close()
            await db.commit()
        return alerts

    async def due_alerts(self, now_utc: datetime) -> List[Alert]:
        res: List[Alert] = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, reminder_id, fire_ts_utc, fired FROM alerts WHERE fired=0 AND fire_ts_utc <= ?",
                (now_utc.isoformat(),),
            ) as cur:
                async for row in cur:
                    res.append(Alert(id=row[0], reminder_id=row[1], fire_ts_utc=datetime.fromisoformat(row[2]).replace(tzinfo=UTC), fired=row[3]))
        return res

    async def mark_alert_fired(self, alert_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE alerts SET fired=1 WHERE id=?", (alert_id,))
            await db.commit()

    # -------- tasks
    async def create_task(self, chat_id: int, user_id: int, text: str, created_utc: datetime) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO tasks(chat_id, user_id, text, created_utc, archived)
            VALUES (?, ?, ?, ?, 0)
            """,
            (chat_id, user_id, text, created_utc.isoformat()),
        )
        await self._db.commit()

    async def get_tasks(self, chat_id: int, user_id: int, limit: int = 100) -> list[dict]:
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """
            SELECT id, text, created_utc
            FROM tasks
            WHERE chat_id=? AND user_id=? AND archived=0
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, user_id, limit),
        )
        return [{"id": r["id"], "text": r["text"], "created_utc": r["created_utc"]} for r in rows]

    async def list_tasks(self, chat_id: int, user_id: int, archived: bool) -> List[Task]:
        out: List[Task] = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, chat_id, user_id, text, created_utc, archived FROM tasks WHERE chat_id=? AND user_id=? AND archived=? ORDER BY id DESC",
                (chat_id, user_id, 1 if archived else 0),
            ) as cur:
                async for row in cur:
                    out.append(
                        Task(
                            id=row[0],
                            chat_id=row[1],
                            user_id=row[2],
                            text=row[3],
                            created_utc=datetime.fromisoformat(row[4]).replace(tzinfo=UTC),
                            archived=row[5],
                        )
                    )
        return out

    async def archive_task(self, task_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE tasks SET archived=1 WHERE id=?", (task_id,))
            await db.commit()

    async def delete_task(self, task_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            await db.commit()

    # -------- shopping
    async def create_shopping_item(self, chat_id: int, user_id: int, text: str, created_utc: datetime) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO shopping(chat_id, user_id, text, created_utc, archived, bought)
            VALUES (?, ?, ?, ?, 0, 0)
            """,
            (chat_id, user_id, text, created_utc.isoformat()),
        )
        await self._db.commit()

    async def get_shopping_items(self, chat_id: int, user_id: int, include_bought: bool = False) -> list[dict]:
        assert self._db is not None
        if include_bought:
            rows = await self._db.execute_fetchall(
                """
                SELECT id, text, created_utc, bought
                FROM shopping
                WHERE chat_id=? AND user_id=? AND archived=0
                ORDER BY id DESC
                """,
                (chat_id, user_id),
            )
        else:
            rows = await self._db.execute_fetchall(
                """
                SELECT id, text, created_utc, bought
                FROM shopping
                WHERE chat_id=? AND user_id=? AND archived=0 AND bought=0
                ORDER BY id DESC
                """,
                (chat_id, user_id),
            )
        return [{"id": r["id"], "text": r["text"], "created_utc": r["created_utc"], "bought": r["bought"]} for r in rows]

    async def mark_shopping_bought(self, item_id: int) -> None:
        assert self._db is not None
        await self._db.execute("UPDATE shopping SET bought=1 WHERE id=?", (item_id,))
        await self._db.commit()

    async def delete_shopping_item(self, item_id: int) -> None:
        assert self._db is not None
        await self._db.execute("UPDATE shopping SET archived=1 WHERE id=?", (item_id,))
        await self._db.commit()

    async def create_shopping_item(self, chat_id: int, user_id: int, text: str, created_utc: datetime) -> ShoppingItem:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO shopping(chat_id,user_id,text,created_utc) VALUES(?,?,?,?)",
                (chat_id, user_id, text, created_utc.isoformat()),
            )
            item_id = cur.lastrowid
            await cur.close()
            await db.commit()
        return ShoppingItem(id=item_id, chat_id=chat_id, user_id=user_id, text=text, created_utc=created_utc, archived=0)

    async def list_shopping(self, chat_id: int, user_id: int, archived: bool) -> List[ShoppingItem]:
        out: List[ShoppingItem] = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, chat_id, user_id, text, created_utc, archived FROM shopping WHERE chat_id=? AND user_id=? AND archived=? ORDER BY id DESC",
                (chat_id, user_id, 1 if archived else 0),
            ) as cur:
                async for row in cur:
                    out.append(
                        ShoppingItem(
                            id=row[0],
                            chat_id=row[1],
                            user_id=row[2],
                            text=row[3],
                            created_utc=datetime.fromisoformat(row[4]).replace(tzinfo=UTC),
                            archived=row[5],
                        )
                    )
        return out

    async def archive_shopping(self, item_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE shopping SET archived=1 WHERE id=?", (item_id,))
            await db.commit()

    async def delete_shopping(self, item_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM shopping WHERE id=?", (item_id,))
            await db.commit()

    # -------- rituals
    async def create_ritual(self, chat_id: int, user_id: int, text: str, created_utc: datetime) -> Ritual:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO rituals(chat_id,user_id,text,created_utc) VALUES(?,?,?,?)",
                (chat_id, user_id, text, created_utc.isoformat()),
            )
            r_id = cur.lastrowid
            await cur.close()
            await db.commit()
        return Ritual(id=r_id, chat_id=chat_id, user_id=user_id, text=text, created_utc=created_utc)

    async def list_rituals(self, chat_id: int, user_id: int) -> List[Ritual]:
        out: List[Ritual] = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, chat_id, user_id, text, created_utc FROM rituals WHERE chat_id=? AND user_id=? ORDER BY id DESC",
                (chat_id, user_id),
            ) as cur:
                async for row in cur:
                    out.append(
                        Ritual(
                            id=row[0],
                            chat_id=row[1],
                            user_id=row[2],
                            text=row[3],
                            created_utc=datetime.fromisoformat(row[4]).replace(tzinfo=UTC),
                        )
                    )
        return out

