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
    archived_ts_utc: Optional[datetime]


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
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("PRAGMA journal_mode = WAL;")
            await self._ensure_schema(db)
            await db.commit()

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        await db.executescript(
            """
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
                fire_ts_utc INTEGER,
                fired INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_ts_utc TEXT
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
                preset_key TEXT,
                created_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Europe/Kyiv',
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS daily_plan (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date_ymd TEXT NOT NULL,
                item TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                done_ts_utc TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_review (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date_ymd TEXT NOT NULL,
                mit_done TEXT NOT NULL,
                mood INTEGER NOT NULL,
                gratitude TEXT NOT NULL,
                notes TEXT NOT NULL,
                created_ts_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_ts_utc TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_rituals_preset
                ON rituals(chat_id, user_id, COALESCE(preset_key, ''));

            CREATE INDEX IF NOT EXISTS idx_daily_plan_date
                ON daily_plan(chat_id, user_id, date_ymd);

            CREATE INDEX IF NOT EXISTS idx_daily_review_date
                ON daily_review(chat_id, user_id, date_ymd);

            CREATE INDEX IF NOT EXISTS idx_tasks_archived_ts
                ON tasks(chat_id, user_id, archived_ts_utc);
            """
        )

        column_cache: dict[str, List[str]] = {}
        applied: list[str] = []

        async def get_columns(table: str) -> List[str]:
            if table not in column_cache:
                db.row_factory = aiosqlite.Row
                async with db.execute(f"PRAGMA table_info({table})") as cursor:
                    rows = await cursor.fetchall()
                column_cache[table] = [row["name"] for row in rows]
            return column_cache[table]

        async def ensure_column(table: str, column: str, definition: str) -> bool:
            columns = await get_columns(table)
            if column in columns:
                return False
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            column_cache.pop(table, None)
            applied.append(f"{table}.{column}")
            return True

        await ensure_column("alerts", "fired", "INTEGER NOT NULL DEFAULT 0")
        if await ensure_column("alerts", "fire_ts_utc", "INTEGER"):
            await self._backfill_alert_fire_ts(db)
        await ensure_column("reminders", "archived", "INTEGER NOT NULL DEFAULT 0")
        await ensure_column("tasks", "archived", "INTEGER NOT NULL DEFAULT 0")
        await ensure_column("tasks", "archived_ts_utc", "TEXT")
        await ensure_column("shopping", "archived", "INTEGER NOT NULL DEFAULT 0")
        await ensure_column("rituals", "preset_key", "TEXT")
        await ensure_column("rituals", "created_utc", "TEXT NOT NULL DEFAULT ''")

        if applied:
            for item in applied:
                if item == "alerts.fire_ts_utc":
                    logger.info("applied sqlite migration: add alerts.fire_ts_utc")
                else:
                    logger.info("DB migrate: added %s", item)

    async def _backfill_alert_fire_ts(self, db: aiosqlite.Connection) -> None:
        columns = []
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(alerts)") as cursor:
            rows = await cursor.fetchall()
        columns = [row["name"] for row in rows]
        source_column = None
        for candidate in ("ts_utc", "fire_ts"):
            if candidate in columns:
                source_column = candidate
                break
        if not source_column:
            return
        async with db.execute(f"SELECT id, {source_column} FROM alerts") as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            raw = row[source_column]
            if raw is None:
                continue
            try:
                fire_dt = _from_storage_timestamp(raw)
            except Exception:  # pragma: no cover - defensive
                continue
            await db.execute(
                "UPDATE alerts SET fire_ts_utc = ? WHERE id = ?",
                (_to_epoch(fire_dt), row["id"]),
            )

    # --- user profiles -----------------------------------------------------------

    async def register_user(self, chat_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
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
                    (reminder_id, _to_epoch(fire_ts)),
                )
                alerts.append(
                    Alert(
                        id=alert_cur.lastrowid,
                        reminder_id=reminder_id,
                        fire_ts_utc=_ensure_tz(fire_ts),
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
            event_ts_utc=_ensure_tz(event_ts_utc),
            created_utc=_ensure_tz(created_utc),
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
        return Reminder(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            text=row["text"],
            event_ts_utc=_from_storage_timestamp(row["event_ts_utc"]),
            created_utc=_from_storage_timestamp(row["created_utc"]),
            archived=bool(row["archived"]),
        )

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
            params.append(_to_iso(start_utc))
        if end_utc is not None:
            clauses.append("event_ts_utc < ?")
            params.append(_to_iso(end_utc))
        where = " AND ".join(clauses)
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM reminders WHERE {where} ORDER BY event_ts_utc",
                params,
            ) as cursor:
                rows = await cursor.fetchall()
        reminders: List[Reminder] = []
        for row in rows:
            reminders.append(
                Reminder(
                    id=row["id"],
                    chat_id=row["chat_id"],
                    user_id=row["user_id"],
                    text=row["text"],
                    event_ts_utc=_from_storage_timestamp(row["event_ts_utc"]),
                    created_utc=_from_storage_timestamp(row["created_utc"]),
                    archived=bool(row["archived"]),
                )
            )
        return reminders

    async def delete_reminder(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            await db.commit()

    async def archive_reminder(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("UPDATE reminders SET archived = 1 WHERE id = ?", (reminder_id,))
            await db.commit()

    async def add_alerts(
        self, reminder_id: int, fire_times: Sequence[datetime]
    ) -> List[Alert]:
        alerts: List[Alert] = []
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            for fire_ts in fire_times:
                cur = await db.execute(
                    "INSERT INTO alerts (reminder_id, fire_ts_utc) VALUES (?, ?)",
                    (reminder_id, _to_epoch(fire_ts)),
                )
                alerts.append(
                    Alert(
                        id=cur.lastrowid,
                        reminder_id=reminder_id,
                        fire_ts_utc=_ensure_tz(fire_ts),
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
            fire_ts_utc=_from_storage_timestamp(row["fire_ts_utc"]),
            fired=bool(row["fired"]),
        )
        reminder = Reminder(
            id=row["r_id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            text=row["text"],
            event_ts_utc=_from_storage_timestamp(row["event_ts_utc"]),
            created_utc=_from_storage_timestamp(row["created_utc"]),
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
                WHERE a.fired = 0 AND CAST(a.fire_ts_utc AS INTEGER) > ?
                ORDER BY CAST(a.fire_ts_utc AS INTEGER) ASC
                """,
                (_to_epoch(now_utc),),
            ) as cursor:
                rows = await cursor.fetchall()
        result: List[Tuple[Alert, Reminder]] = []
        for row in rows:
            alert = Alert(
                id=row["a_id"],
                reminder_id=row["reminder_id"],
                fire_ts_utc=_from_storage_timestamp(row["fire_ts_utc"]),
                fired=bool(row["fired"]),
            )
            reminder = Reminder(
                id=row["r_id"],
                chat_id=row["chat_id"],
                user_id=row["user_id"],
                text=row["text"],
                event_ts_utc=_from_storage_timestamp(row["event_ts_utc"]),
                created_utc=_from_storage_timestamp(row["created_utc"]),
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
        alerts: List[Alert] = []
        for row in rows:
            alerts.append(
                Alert(
                    id=row["id"],
                    reminder_id=row["reminder_id"],
                    fire_ts_utc=_from_storage_timestamp(row["fire_ts_utc"]),
                    fired=bool(row["fired"]),
                )
            )
        return alerts

    async def mark_alert_fired(self, alert_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("UPDATE alerts SET fired = 1 WHERE id = ?", (alert_id,))
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
                (chat_id, user_id, text, _to_iso(created_utc)),
            )
            await db.commit()
            task_id = cur.lastrowid
            await cur.close()
        return Task(
            id=task_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            created_utc=_ensure_tz(created_utc),
            archived=False,
            archived_ts_utc=None,
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
            archived_ts = row["archived_ts_utc"]
            tasks.append(
                Task(
                    id=row["id"],
                    chat_id=row["chat_id"],
                    user_id=row["user_id"],
                    text=row["text"],
                    created_utc=_from_storage_timestamp(row["created_utc"]),
                    archived=bool(row["archived"]),
                    archived_ts_utc=_from_storage_timestamp(archived_ts)
                    if archived_ts
                    else None,
                )
            )
        return tasks

    async def archive_task(self, task_id: int, archived_ts: datetime) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE tasks SET archived = 1, archived_ts_utc = ? WHERE id = ?",
                (_to_iso(archived_ts), task_id),
            )
            await db.commit()

    async def delete_task(self, task_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await db.commit()

    async def count_completed_tasks(
        self, *, chat_id: int, user_id: int, since: datetime
    ) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(*) FROM tasks
                WHERE chat_id = ? AND user_id = ? AND archived = 1
                  AND archived_ts_utc IS NOT NULL AND archived_ts_utc >= ?
                """,
                (chat_id, user_id, _to_iso(since)),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

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
                (chat_id, user_id, text, _to_iso(created_utc)),
            )
            await db.commit()
            item_id = cur.lastrowid
            await cur.close()
        return ShoppingItem(
            id=item_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            created_utc=_ensure_tz(created_utc),
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
        items: List[ShoppingItem] = []
        for row in rows:
            items.append(
                ShoppingItem(
                    id=row["id"],
                    chat_id=row["chat_id"],
                    user_id=row["user_id"],
                    text=row["text"],
                    created_utc=_from_storage_timestamp(row["created_utc"]),
                    archived=bool(row["archived"]),
                )
            )
        return items

    async def archive_shopping_item(self, item_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("UPDATE shopping SET archived = 1 WHERE id = ?", (item_id,))
            await db.commit()

    async def delete_shopping_item(self, item_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM shopping WHERE id = ?", (item_id,))
            await db.commit()

    # --- rituals ------------------------------------------------------------------

    async def list_ritual_presets(self, *, chat_id: int, user_id: int) -> List[str]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT preset_key FROM rituals WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row["preset_key"] for row in rows if row["preset_key"]]

    async def mark_ritual_added(
        self,
        *,
        chat_id: int,
        user_id: int,
        preset_key: str,
        text: str,
        created_utc: datetime,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO rituals (chat_id, user_id, text, preset_key, created_utc)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id, preset_key) DO UPDATE SET text = excluded.text
                """,
                (chat_id, user_id, text, preset_key, _to_iso(created_utc)),
            )
            await db.commit()

    # --- daily plan ----------------------------------------------------------------

    async def add_plan_item(
        self,
        *,
        chat_id: int,
        user_id: int,
        date_ymd: str,
        item: str,
        created_utc: datetime,
    ) -> DailyPlanItem:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO daily_plan (chat_id, user_id, date_ymd, item)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, user_id, date_ymd, item),
            )
            await db.commit()
            item_id = cur.lastrowid
            await cur.close()
        return DailyPlanItem(
            id=item_id,
            chat_id=chat_id,
            user_id=user_id,
            date_ymd=date_ymd,
            item=item,
            done=False,
            done_ts_utc=None,
        )

    async def list_plan_items(
        self, *, chat_id: int, user_id: int, date_ymd: str
    ) -> List[DailyPlanItem]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM daily_plan
                WHERE chat_id = ? AND user_id = ? AND date_ymd = ?
                ORDER BY id ASC
                """,
                (chat_id, user_id, date_ymd),
            ) as cursor:
                rows = await cursor.fetchall()
        items: List[DailyPlanItem] = []
        for row in rows:
            done_ts = row["done_ts_utc"]
            items.append(
                DailyPlanItem(
                    id=row["id"],
                    chat_id=row["chat_id"],
                    user_id=row["user_id"],
                    date_ymd=row["date_ymd"],
                    item=row["item"],
                    done=bool(row["done"]),
                    done_ts_utc=_from_storage_timestamp(done_ts) if done_ts else None,
                )
            )
        return items

    async def mark_plan_done(self, item_id: int, done_ts: datetime) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE daily_plan SET done = 1, done_ts_utc = ? WHERE id = ?",
                (_to_iso(done_ts), item_id),
            )
            await db.commit()

    async def plan_items_count(self, *, chat_id: int, user_id: int, date_ymd: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM daily_plan WHERE chat_id = ? AND user_id = ? AND date_ymd = ?",
                (chat_id, user_id, date_ymd),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def plan_stats_for_period(
        self,
        *,
        chat_id: int,
        user_id: int,
        start_date: date,
        end_date: date,
    ) -> Tuple[int, int]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """
                SELECT done, COUNT(*) as cnt
                FROM daily_plan
                WHERE chat_id = ? AND user_id = ? AND date_ymd BETWEEN ? AND ?
                GROUP BY done
                """,
                (
                    chat_id,
                    user_id,
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            ) as cursor:
                rows = await cursor.fetchall()
        total = 0
        done = 0
        for row in rows:
            count = int(row["cnt"])
            total += count
            if int(row["done"]):
                done += count
        return done, total

    async def review_streak(self, *, chat_id: int, user_id: int, today: date) -> int:
        streak = 0
        check_date = today
        async with aiosqlite.connect(self._db_path) as db:
            while True:
                async with db.execute(
                    "SELECT 1 FROM daily_review WHERE chat_id = ? AND user_id = ? AND date_ymd = ?",
                    (chat_id, user_id, check_date.isoformat()),
                ) as cursor:
                    row = await cursor.fetchone()
                if not row:
                    break
                streak += 1
                check_date -= timedelta(days=1)
        return streak

    # --- daily review -------------------------------------------------------------

    async def get_review_for_date(
        self, *, chat_id: int, user_id: int, date_ymd: str
    ) -> Optional[DailyReview]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM daily_review
                WHERE chat_id = ? AND user_id = ? AND date_ymd = ?
                ORDER BY id DESC LIMIT 1
                """,
                (chat_id, user_id, date_ymd),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return DailyReview(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            date_ymd=row["date_ymd"],
            mit_done=row["mit_done"],
            mood=int(row["mood"]),
            gratitude=row["gratitude"],
            notes=row["notes"],
            created_ts_utc=_from_storage_timestamp(row["created_ts_utc"]),
        )

    async def upsert_daily_review(
        self,
        *,
        chat_id: int,
        user_id: int,
        date_ymd: str,
        mit_done: str,
        mood: int,
        gratitude: str,
        notes: str,
        created_ts_utc: datetime,
    ) -> DailyReview:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO daily_review (chat_id, user_id, date_ymd, mit_done, mood, gratitude, notes, created_ts_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id, date_ymd)
                DO UPDATE SET mit_done=excluded.mit_done,
                              mood=excluded.mood,
                              gratitude=excluded.gratitude,
                              notes=excluded.notes,
                              created_ts_utc=excluded.created_ts_utc
                """,
                (
                    chat_id,
                    user_id,
                    date_ymd,
                    mit_done,
                    mood,
                    gratitude,
                    notes,
                    _to_iso(created_ts_utc),
                ),
            )
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

    async def add_note(
        self, *, chat_id: int, user_id: int, text: str, created_ts: datetime
    ) -> Note:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO notes (chat_id, user_id, text, created_ts_utc)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, user_id, text, _to_iso(created_ts)),
            )
            await db.commit()
            note_id = cur.lastrowid
            await cur.close()
        return Note(
            id=note_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            created_ts_utc=_ensure_tz(created_ts),
        )

    async def list_notes(self, *, chat_id: int, user_id: int, limit: int = 10) -> List[Note]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM notes
                WHERE chat_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        notes: List[Note] = []
        for row in rows:
            notes.append(
                Note(
                    id=row["id"],
                    chat_id=row["chat_id"],
                    user_id=row["user_id"],
                    text=row["text"],
                    created_ts_utc=_from_storage_timestamp(row["created_ts_utc"]),
                )
            )
        return notes

    async def delete_note(self, note_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            await db.commit()

    # --- reports ------------------------------------------------------------------

    async def weekly_report(
        self,
        *,
        chat_id: int,
        user_id: int,
        today: date,
    ) -> Tuple[int, int, int, int]:
        start = today - timedelta(days=6)
        done_mit, total_mit = await self.plan_stats_for_period(
            chat_id=chat_id,
            user_id=user_id,
            start_date=start,
            end_date=today,
        )
        streak = await self.review_streak(chat_id=chat_id, user_id=user_id, today=today)
        tasks_done = await self.count_completed_tasks(
            chat_id=chat_id,
            user_id=user_id,
            since=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        )
        return done_mit, total_mit, streak, tasks_done


__all__ = [
    "Alert",
    "DBManager",
    "DailyPlanItem",
    "DailyReview",
    "KnownUser",
    "Note",
    "Reminder",
    "Ritual",
    "ShoppingItem",
    "Task",
    "UTC",
]
