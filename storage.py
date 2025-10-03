from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import aiosqlite
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
logger = logging.getLogger(__name__)


# --- dataclasses ----------------------------------------------------------------


@dataclass(slots=True)
class Reminder:
    id: int
    chat_id: int
    user_id: int
    text: str
    event_ts_utc: datetime
    created_utc: datetime
    archived: bool


@dataclass(slots=True)
class Alert:
    id: int
    reminder_id: int
    fire_ts_utc: datetime
    fired: bool


@dataclass(slots=True)
class Task:
    id: int
    chat_id: int
    user_id: int
    text: str
    created_utc: datetime
    archived: bool


@dataclass(slots=True)
class ShoppingItem:
    id: int
    chat_id: int
    user_id: int
    text: str
    created_utc: datetime
    archived: bool


@dataclass(slots=True)
class Ritual:
    id: int
    chat_id: int
    user_id: int
    text: str
    preset_key: Optional[str]
    created_utc: datetime


@dataclass(slots=True)
class DailyPlanItem:
    id: int
    chat_id: int
    user_id: int
    date_ymd: str
    item: str
    done: bool
    done_ts_utc: Optional[datetime]


@dataclass(slots=True)
class DailyReview:
    id: int
    chat_id: int
    user_id: int
    date_ymd: str
    mit_done: str
    mood: int
    gratitude: str
    notes: str
    created_ts_utc: datetime


@dataclass(slots=True)
class Note:
    id: int
    chat_id: int
    user_id: int
    text: str
    created_ts_utc: datetime


@dataclass(slots=True)
class KnownUser:
    chat_id: int
    user_id: int
    timezone: ZoneInfo


# --- helpers --------------------------------------------------------------------


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _to_iso(dt: datetime) -> str:
    return _ensure_tz(dt).isoformat()


def _to_epoch(dt: datetime) -> int:
    return int(_ensure_tz(dt).timestamp())


def _from_storage_timestamp(value: object) -> datetime:
    if value is None:
        raise ValueError("timestamp value is None")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), tz=UTC)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty timestamp value")
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return datetime.fromtimestamp(int(text), tz=UTC)
        try:
            return datetime.fromisoformat(text).replace(tzinfo=UTC)
        except ValueError:
            pass
        try:
            return datetime.fromtimestamp(int(float(text)), tz=UTC)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Cannot parse timestamp value: {value!r}") from exc
    raise TypeError(f"Unsupported timestamp type: {type(value)!r}")


# --- database manager -----------------------------------------------------------


class DBManager:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    event_ts_utc TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY,
                    reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
                    fire_ts_utc TEXT NOT NULL,
                    fired INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS shopping (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS rituals (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_utc TEXT NOT NULL
                );
                """
                INSERT OR IGNORE INTO user_profiles (chat_id, user_id, timezone)
                VALUES (?, ?, 'Europe/Kyiv')
                """,
                (chat_id, user_id),
            )
            await db.commit()
            inserted = cur.rowcount > 0
            await cur.close()
        return inserted

    async def get_known_users(self) -> List[KnownUser]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM user_profiles") as cursor:
                rows = await cursor.fetchall()
        result: List[KnownUser] = []
        for row in rows:
            try:
                tz = ZoneInfo(row["timezone"])
            except Exception:  # pragma: no cover - fallback
                tz = ZoneInfo("Europe/Kyiv")
            result.append(KnownUser(chat_id=row["chat_id"], user_id=row["user_id"], timezone=tz))
        return result

    # --- reminders ----------------------------------------------------------------

    # --- helpers -----------------------------------------------------------------

    @staticmethod
    def _row_to_reminder(row: aiosqlite.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            text=row["text"],
            event_ts_utc=datetime.fromisoformat(row["event_ts_utc"]).replace(tzinfo=UTC),
            created_utc=datetime.fromisoformat(row["created_utc"]).replace(tzinfo=UTC),
            archived=bool(row["archived"]),
        )

    @staticmethod
    def _row_to_alert(row: aiosqlite.Row) -> Alert:
        return Alert(
            id=row["id"],
            reminder_id=row["reminder_id"],
            fire_ts_utc=datetime.fromisoformat(row["fire_ts_utc"]).replace(tzinfo=UTC),
            fired=bool(row["fired"]),
        )

    # --- reminders ----------------------------------------------------------------

    async def create_reminder(
        self,
        *,
        chat_id: int,
        user_id: int,
        text: str,
        event_ts_utc: datetime,
        created_utc: datetime,
        alert_times_utc: Sequence[datetime],
    ) -> Tuple[Reminder, List[Alert]]:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                """
                INSERT INTO reminders (chat_id, user_id, text, event_ts_utc, created_utc)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, text, _to_iso(event_ts_utc), _to_iso(created_utc)),
            )
            reminder_id = cur.lastrowid
            await cur.close()

            alerts: List[Alert] = []
            for fire_ts in alert_times_utc:
                alert_cur = await db.execute(
                    "INSERT INTO alerts (reminder_id, fire_ts_utc) VALUES (?, ?)",
                    (reminder_id, fire_ts.isoformat()),
                )
                alerts.append(
                    Alert(
                        id=alert_cur.lastrowid,
                        reminder_id=reminder_id,
                        fire_ts_utc=fire_ts,
                        fired=False,
                    )
                )
                await alert_cur.close()

            await db.commit()

        reminder = Reminder(
            id=reminder_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            event_ts_utc=event_ts_utc,
            created_utc=created_utc,
            archived=False,
        )
        return reminder, alerts

    async def get_reminder(self, reminder_id: int) -> Optional[Reminder]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM reminders WHERE id = ?",
                (reminder_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_reminder(row)

    async def get_reminders_for_range(
        self,
        *,
        chat_id: int,
        user_id: int,
        start_utc: Optional[datetime],
        end_utc: Optional[datetime],
        archived: bool,
    ) -> List[Reminder]:
        clauses = ["chat_id = ?", "user_id = ?", "archived = ?"]
        params: List[object] = [chat_id, user_id, 1 if archived else 0]
        if start_utc is not None:
            clauses.append("event_ts_utc >= ?")
            params.append(start_utc.isoformat())
        if end_utc is not None:
            clauses.append("event_ts_utc < ?")
            params.append(end_utc.isoformat())
        where = " AND ".join(clauses)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM reminders WHERE {where} ORDER BY event_ts_utc",
                params,
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_reminder(row) for row in rows]

    async def archive_reminder(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE reminders SET archived = 1 WHERE id = ?",
                (reminder_id,),
            )
            await db.commit()

    async def delete_reminder(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            await db.commit()

    async def add_alerts(self, reminder_id: int, fire_times: Sequence[datetime]) -> List[Alert]:
        alerts: List[Alert] = []
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            for fire_ts in fire_times:
                cur = await db.execute(
                    "INSERT INTO alerts (reminder_id, fire_ts_utc) VALUES (?, ?)",
                    (reminder_id, fire_ts.isoformat()),
                )
                alerts.append(
                    Alert(
                        id=cur.lastrowid,
                        reminder_id=reminder_id,
                        fire_ts_utc=fire_ts,
                        fired=False,
                    )
                )
                await cur.close()
            await db.commit()
        return alerts

    async def get_alert_with_reminder(self, alert_id: int) -> Optional[Tuple[Alert, Reminder]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT a.id as a_id, a.reminder_id, a.fire_ts_utc, a.fired,
                       r.id as r_id, r.chat_id, r.user_id, r.text, r.event_ts_utc, r.created_utc, r.archived
                FROM alerts a
                JOIN reminders r ON r.id = a.reminder_id
                WHERE a.id = ?
                """,
                (alert_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        alert = Alert(
            id=row["a_id"],
            reminder_id=row["reminder_id"],
            fire_ts_utc=datetime.fromisoformat(row["fire_ts_utc"]).replace(tzinfo=UTC),
            fired=bool(row["fired"]),
        )
        reminder = Reminder(
            id=row["r_id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            text=row["text"],
            event_ts_utc=datetime.fromisoformat(row["event_ts_utc"]).replace(tzinfo=UTC),
            created_utc=datetime.fromisoformat(row["created_utc"]).replace(tzinfo=UTC),
            archived=bool(row["archived"]),
        )
        return alert, reminder

    async def get_pending_alerts(self, now_utc: datetime) -> List[Tuple[Alert, Reminder]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT a.id as a_id, a.reminder_id, a.fire_ts_utc, a.fired,
                       r.id as r_id, r.chat_id, r.user_id, r.text, r.event_ts_utc, r.created_utc, r.archived
                FROM alerts a
                JOIN reminders r ON r.id = a.reminder_id
                WHERE a.fired = 0 AND datetime(a.fire_ts_utc) > ?
                ORDER BY a.fire_ts_utc ASC
                """,
                (now_utc.isoformat(),),
            ) as cursor:
                rows = await cursor.fetchall()
        result: List[Tuple[Alert, Reminder]] = []
        for row in rows:
            alert = Alert(
                id=row["a_id"],
                reminder_id=row["reminder_id"],
                fire_ts_utc=datetime.fromisoformat(row["fire_ts_utc"]).replace(tzinfo=UTC),
                fired=False,
            )
            reminder = Reminder(
                id=row["r_id"],
                chat_id=row["chat_id"],
                user_id=row["user_id"],
                text=row["text"],
                event_ts_utc=datetime.fromisoformat(row["event_ts_utc"]).replace(tzinfo=UTC),
                created_utc=datetime.fromisoformat(row["created_utc"]).replace(tzinfo=UTC),
                archived=bool(row["archived"]),
            )
            result.append((alert, reminder))
        return result

    async def get_active_alerts_for_reminder(self, reminder_id: int) -> List[Alert]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM alerts WHERE reminder_id = ? AND fired = 0",
                (reminder_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_alert(row) for row in rows]

    async def mark_alert_fired(self, alert_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE alerts SET fired = 1 WHERE id = ?",
                (alert_id,),
            )
            await db.commit()

    async def mark_alerts_fired_for_reminder(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE alerts SET fired = 1 WHERE reminder_id = ?",
                (reminder_id,),
            )
            await db.commit()

    # --- tasks --------------------------------------------------------------------

    async def create_task(
        self, *, chat_id: int, user_id: int, text: str, created_utc: datetime
    ) -> Task:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO tasks (chat_id, user_id, text, created_utc)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, user_id, text, created_utc.isoformat()),
            )
            await db.commit()
            task_id = cur.lastrowid
            await cur.close()
        return Task(
            id=task_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            created_utc=created_utc,
            archived=False,
        )

    async def list_tasks(self, *, chat_id: int, user_id: int, archived: bool) -> List[Task]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM tasks
                WHERE chat_id = ? AND user_id = ? AND archived = ?
                ORDER BY id DESC
                """,
                (chat_id, user_id, 1 if archived else 0),
            ) as cursor:
                rows = await cursor.fetchall()
        tasks: List[Task] = []
        for row in rows:
            tasks.append(
                Task(
                    id=row["id"],
                    chat_id=row["chat_id"],
                    user_id=row["user_id"],
                    text=row["text"],
                    created_utc=datetime.fromisoformat(row["created_utc"]).replace(tzinfo=UTC),
                    archived=bool(row["archived"]),
                )
            )
        return tasks

    async def archive_task(self, task_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("UPDATE tasks SET archived = 1 WHERE id = ?", (task_id,))
            await db.commit()

    async def delete_task(self, task_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await db.commit()

    # --- shopping -----------------------------------------------------------------

    async def create_shopping_item(
        self, *, chat_id: int, user_id: int, text: str, created_utc: datetime
    ) -> ShoppingItem:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO shopping (chat_id, user_id, text, created_utc)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, user_id, text, created_utc.isoformat()),
            )
            await db.commit()
            item_id = cur.lastrowid
            await cur.close()
        return ShoppingItem(
            id=item_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            created_utc=created_utc,
            archived=False,
        )

    async def list_shopping(
        self, *, chat_id: int, user_id: int, archived: bool
    ) -> List[ShoppingItem]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM shopping
                WHERE chat_id = ? AND user_id = ? AND archived = ?
                ORDER BY id DESC
                """,
                (chat_id, user_id, 1 if archived else 0),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            ShoppingItem(
                id=row["id"],
                chat_id=row["chat_id"],
                user_id=row["user_id"],
                text=row["text"],
                created_utc=datetime.fromisoformat(row["created_utc"]).replace(tzinfo=UTC),
                archived=bool(row["archived"]),
            )
            for row in rows
        ]

    async def archive_shopping_item(self, item_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("UPDATE shopping SET archived = 1 WHERE id = ?", (item_id,))
            await db.commit()

    async def delete_shopping_item(self, item_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM shopping WHERE id = ?", (item_id,))
            await db.commit()
        return DailyReview(
            id=0,
            chat_id=chat_id,
            user_id=user_id,
            date_ymd=date_ymd,
            mit_done=mit_done,
            mood=mood,
            gratitude=gratitude,
            notes=notes,
            created_ts_utc=_ensure_tz(created_ts_utc),
        )

    # --- notes --------------------------------------------------------------------

    # --- rituals ------------------------------------------------------------------

    async def create_ritual(
        self, *, chat_id: int, user_id: int, text: str, created_utc: datetime
    ) -> Ritual:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO rituals (chat_id, user_id, text, created_utc)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, user_id, text, created_utc.isoformat()),
            )
            await db.commit()
            ritual_id = cur.lastrowid
            await cur.close()
        return Ritual(
            id=ritual_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            created_utc=created_utc,
        )

    async def list_rituals(self, *, chat_id: int, user_id: int, limit: int = 100) -> List[Ritual]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM rituals
                WHERE chat_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            Ritual(
                id=row["id"],
                chat_id=row["chat_id"],
                user_id=row["user_id"],
                text=row["text"],
                created_utc=datetime.fromisoformat(row["created_utc"]).replace(tzinfo=UTC),
            )
            for row in rows
        ]

    async def delete_ritual(self, ritual_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM rituals WHERE id = ?", (ritual_id,))
            await db.commit()


__all__ = [
    "Alert",
    "DBManager",
    "Reminder",
    "Ritual",
    "ShoppingItem",
    "Task",
    "UTC",
]
