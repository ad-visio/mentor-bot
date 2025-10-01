from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

from storage import Alert, DBManager, Reminder

UTC = ZoneInfo("UTC")
KYIV = ZoneInfo("Europe/Kyiv")
logger = logging.getLogger(__name__)


class SchedulerManager:
    def __init__(self, db: DBManager, bot: Bot) -> None:
        self._db = db
        self._bot = bot
        self._scheduler = AsyncIOScheduler(timezone=UTC)
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._scheduler.start()
        self._started = True
        await self.reschedule_all()

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False

    async def reschedule_all(self) -> None:
        now_utc = datetime.now(tz=UTC)
        alerts = await self._db.get_pending_alerts(now_utc)
        for alert, reminder in alerts:
            await self._schedule_alert(alert, reminder)

    async def schedule_alerts(self, alerts: Sequence[Alert]) -> None:
        for alert in alerts:
            reminder = await self._db.get_reminder(alert.reminder_id)
            if reminder is None:
                continue
            await self._schedule_alert(alert, reminder)

    async def remove_alerts_for_reminder(self, reminder_id: int) -> None:
        active_alerts = await self._db.get_active_alerts_for_reminder(reminder_id)
        for alert in active_alerts:
            job_id = self._job_id(alert.id)
            job = self._scheduler.get_job(job_id)
            if job:
                job.remove()

    async def _schedule_alert(self, alert: Alert, reminder: Reminder) -> None:
        if alert.fired:
            return
        job_id = self._job_id(alert.id)
        if self._scheduler.get_job(job_id):
            return
        run_date = alert.fire_ts_utc.astimezone(UTC)
        if run_date <= datetime.now(tz=UTC):
            return
        self._scheduler.add_job(
            self._fire_alert,
            trigger="date",
            run_date=run_date,
            args=[alert.id],
            id=job_id,
            replace_existing=False,
        )
        logger.debug(
            "Scheduled alert %s for reminder %s at %s", alert.id, reminder.id, run_date
        )

    @staticmethod
    def _job_id(alert_id: int) -> str:
        return f"alert:{alert_id}"

    async def _fire_alert(self, alert_id: int) -> None:
        data = await self._db.get_alert_with_reminder(alert_id)
        if not data:
            return
        alert, reminder = data
        if reminder.archived:
            await self._db.mark_alert_fired(alert.id)
            return
        local_time = reminder.event_ts_utc.astimezone(KYIV)
        try:
            await self._bot.send_message(
                chat_id=reminder.chat_id,
                text=(
                    "<b>Напоминание</b>\n"
                    f"{reminder.text}\n"
                    f"🕒 {local_time.strftime('%d.%m.%Y %H:%M')}"
                ),
            )
        except Exception:  # pragma: no cover - logging only
            logger.exception("Failed to deliver alert %s", alert.id)
        finally:
            await self._db.mark_alert_fired(alert.id)


__all__ = ["SchedulerManager"]
