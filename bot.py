from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from keyboards import (
    ALERT_DEFAULT_SELECTION,
    ALERT_OPTIONS,
    CalendarMonth,
    alerts_keyboard,
    cancel_keyboard,
    calendar_keyboard,
    daily_plan_items_keyboard,
    daily_plan_menu_keyboard,
    hours_keyboard,
    main_menu_keyboard,
    minutes_keyboard,
    notes_list_keyboard,
    notes_menu_keyboard,
    reminder_actions_keyboard,
    reminder_date_choice_keyboard,
    reminders_menu_keyboard,
    review_confirm_keyboard,
    review_mit_keyboard,
    review_mood_keyboard,
    review_prompt_keyboard,
    ritual_schedule_keyboard,
    rituals_menu_keyboard,
    shopping_item_actions_keyboard,
    shopping_menu_keyboard,
    simple_back_keyboard,
    task_item_actions_keyboard,
    tasks_menu_keyboard,
)
from scheduler import SchedulerManager
from storage import (
    DBManager,
    DailyPlanItem,
    Reminder,
    UTC,
)
from meta import get_version_line
from routers.version import version_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mentor.db"
KYIV_TZ = ZoneInfo("Europe/Kyiv")
MAX_PLAN_ITEMS = 3


@dataclass(slots=True)
class ReminderDraft:
    target_date: Optional[date] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    alerts: set[str] = None

    def __post_init__(self) -> None:
        if self.alerts is None:
            self.alerts = set(ALERT_DEFAULT_SELECTION)

    @property
    def is_complete(self) -> bool:
        return (
            self.target_date is not None
            and self.hour is not None
            and self.minute is not None
            and bool(self.alerts)
        )

    def build_event_datetime(self) -> datetime:
        if not self.is_complete:
            raise ValueError("Draft is not complete")
        local_dt = datetime.combine(
            self.target_date,
            time(self.hour, self.minute),
            tzinfo=KYIV_TZ,
        )
        return local_dt.astimezone(UTC)


@dataclass(slots=True)
class RitualPreset:
    key: str
    title: str
    steps: str
    summary: str
    hour: int
    minute: int


RITUAL_PRESETS: dict[str, RitualPreset] = {
    "sunrise_focus": RitualPreset(
        key="sunrise_focus",
        title="Утренний фокус",
        steps="Дыхание 4×4×4 → журнал благодарностей (3 пункта) → первый шаг к цели",
        summary="20 минут, заряд энергии и ясность",
        hour=7,
        minute=0,
    ),
    "midday_reset": RitualPreset(
        key="midday_reset",
        title="Полуденный ресет",
        steps="10 глубоких вдохов → проверка MIT → короткая запись итога",
        summary="5 минут, помогает перезагрузиться",
        hour=13,
        minute=0,
    ),
    "evening_anchor": RitualPreset(
        key="evening_anchor",
        title="Вечерний якорь",
        steps="Тёплая музыка → 3 благодарности → визуализация успеха",
        summary="10 минут, снижает стресс и улучшает сон",
        hour=21,
        minute=30,
    ),
}


class ReminderCreation(StatesGroup):
    choosing_date = State()
    choosing_custom_date = State()
    choosing_hour = State()
    choosing_minute = State()
    choosing_alerts = State()
    entering_text = State()


class TaskCreation(StatesGroup):
    entering_text = State()


class ShoppingCreation(StatesGroup):
    entering_text = State()


class DailyPlanStates(StatesGroup):
    entering_item = State()


class NoteStates(StatesGroup):
    entering_text = State()


class DailyReviewStates(StatesGroup):
    choosing_mit = State()
    choosing_mood = State()
    entering_gratitude = State()
    entering_notes = State()
    confirming = State()


router = Router()
db_manager = DBManager(DB_PATH)
scheduler: SchedulerManager | None = None


async def reset_state(state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()


async def show_main_menu(message: Message) -> None:
    await message.answer(
        "Привет! Я твой бот-наставник. Чем займёмся?",
        reply_markup=main_menu_keyboard(),
    )


async def ensure_user_registered(chat_id: int, user_id: int) -> None:
    inserted = await db_manager.register_user(chat_id, user_id)
    if inserted and scheduler:
        await scheduler.reschedule_all()


def format_reminder_card(reminder: Reminder) -> str:
    local_dt = reminder.event_ts_utc.astimezone(KYIV_TZ)
    return (
        f"<b>{local_dt.strftime('%d.%m.%Y')} · {local_dt.strftime('%H:%M')}</b>\n"
        f"{reminder.text}"
    )


def compute_alert_datetimes(event_dt_utc: datetime, selected: Iterable[str]) -> list[datetime]:
    now_utc = datetime.now(tz=UTC)
    alerts: list[datetime] = []
    for _label, value in ALERT_OPTIONS:
        if value not in selected:
            continue
        delta = timedelta(minutes=int(value))
        fire_dt = event_dt_utc - delta
        if fire_dt > now_utc:
            alerts.append(fire_dt)
    return alerts


def shift_month(month: CalendarMonth, delta: int) -> CalendarMonth:
    new_month = month.month + delta
    year = month.year
    while new_month < 1:
        new_month += 12
        year -= 1
    while new_month > 12:
        new_month -= 12
        year += 1
    return CalendarMonth(year=year, month=new_month)


def today_local() -> date:
    return datetime.now(tz=KYIV_TZ).date()


# --- main and navigation --------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await ensure_user_registered(message.chat.id, message.from_user.id)
    await show_main_menu(message)


@router.message(Command("review_now"))
async def cmd_review_now(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await ensure_user_registered(message.chat.id, message.from_user.id)
    await start_daily_review(message, state, today_local().isoformat())


@router.message(F.text == "🏠 На главную")
async def go_home(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await show_main_menu(message)


@router.message(F.text == "⬅️ Назад")
async def go_back(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await show_main_menu(message)


@router.message(F.text == "❌ Отмена")
async def cancel_flow(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await message.answer("Отмена. Выберите следующий шаг.", reply_markup=main_menu_keyboard())


# --- reminders -----------------------------------------------------------------


@router.message(F.text == "⏰ Напоминания")
async def reminders_menu(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await ensure_user_registered(message.chat.id, message.from_user.id)
    await message.answer("Раздел «Напоминания».", reply_markup=reminders_menu_keyboard())


@router.message(F.text == "➕ Создать")
async def reminder_create(message: Message, state: FSMContext) -> None:
    if message.text != "➕ Создать":
        return
    await state.set_state(ReminderCreation.choosing_date)
    await state.update_data(reminder=ReminderDraft())
    await message.answer(
        "Когда напомнить?",
        reply_markup=reminder_date_choice_keyboard(),
    )


@router.callback_query(ReminderCreation.choosing_date, F.data.startswith("date:"))
async def reminder_choose_date(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "today":
        target = today_local()
        draft = ReminderDraft(target_date=target)
        await state.update_data(reminder=draft)
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text("Выберите час", reply_markup=hours_keyboard())
    elif action == "tomorrow":
        target = today_local() + timedelta(days=1)
        draft = ReminderDraft(target_date=target)
        await state.update_data(reminder=draft)
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text("Выберите час", reply_markup=hours_keyboard())
    elif action == "calendar":
        today_month = today_local()
        month = CalendarMonth(year=today_month.year, month=today_month.month)
        await state.update_data(calendar_month=month)
        await state.set_state(ReminderCreation.choosing_custom_date)
        await callback.message.edit_text(
            "Выберите дату", reply_markup=calendar_keyboard(month)
        )
    await callback.answer()


@router.callback_query(ReminderCreation.choosing_custom_date)
async def reminder_choose_custom_date(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    month: CalendarMonth = data.get("calendar_month")
    if callback.data == "cal:prev":
        month = shift_month(month, -1)
        await state.update_data(calendar_month=month)
        await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(month))
    elif callback.data == "cal:next":
        month = shift_month(month, 1)
        await state.update_data(calendar_month=month)
        await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(month))
    elif callback.data.startswith("cal:select:"):
        _, _year, _month, _day = callback.data.split(":")
        target = date(int(_year), int(_month), int(_day))
        draft = ReminderDraft(target_date=target)
        await state.update_data(reminder=draft)
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text("Выберите час", reply_markup=hours_keyboard())
    await callback.answer()


@router.callback_query(ReminderCreation.choosing_hour, F.data.startswith("hour:"))
async def reminder_choose_hour(callback: CallbackQuery, state: FSMContext) -> None:
    hour = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    draft: ReminderDraft = data["reminder"]
    draft.hour = hour
    await state.update_data(reminder=draft)
    await state.set_state(ReminderCreation.choosing_minute)
    await callback.message.edit_text("Выберите минуты", reply_markup=minutes_keyboard())
    await callback.answer()


@router.callback_query(ReminderCreation.choosing_minute, F.data.startswith("minute:"))
async def reminder_choose_minute(callback: CallbackQuery, state: FSMContext) -> None:
    minute = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    draft: ReminderDraft = data["reminder"]
    draft.minute = minute
    await state.update_data(reminder=draft)
    await state.set_state(ReminderCreation.choosing_alerts)
    await callback.message.edit_text(
        "За сколько напомнить дополнительно?",
        reply_markup=alerts_keyboard(draft.alerts),
    )
    await callback.answer()


@router.callback_query(ReminderCreation.choosing_alerts, F.data.startswith("alert:"))
async def reminder_choose_alerts(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    draft: ReminderDraft = data["reminder"]
    if value == "done":
        if not draft.is_complete:
            await callback.answer("Укажите время и дату", show_alert=True)
            return
        await state.set_state(ReminderCreation.entering_text)
        await callback.message.edit_text(
            "Что напомнить?", reply_markup=None
        )
    else:
        if value in draft.alerts:
            draft.alerts.remove(value)
        else:
            draft.alerts.add(value)
        await state.update_data(reminder=draft)
        await callback.message.edit_reply_markup(reply_markup=alerts_keyboard(draft.alerts))
    await callback.answer()


@router.message(ReminderCreation.entering_text)
async def reminder_enter_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft: ReminderDraft = data["reminder"]
    if not draft.is_complete:
        await message.answer("Не хватает данных для напоминания.")
        return
    event_dt = draft.build_event_datetime()
    alerts = compute_alert_datetimes(event_dt, draft.alerts)
    now_utc = datetime.now(tz=UTC)
    reminder, alert_objs = await db_manager.create_reminder(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
        event_ts_utc=event_dt,
        created_utc=now_utc,
        alert_times_utc=alerts,
    )
    if scheduler:
        await scheduler.schedule_alerts(alert_objs)
    await state.clear()
    await message.answer(
        "Готово! Напоминание создано.",
        reply_markup=reminders_menu_keyboard(),
    )


async def list_reminders(
    message: Message,
    *,
    start: Optional[datetime],
    end: Optional[datetime],
    archived: bool,
) -> None:
    reminders = await db_manager.get_reminders_for_range(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        start_utc=start,
        end_utc=end,
        archived=archived,
    )
    if not reminders:
        await message.answer("Ничего не найдено.")
        return
    for reminder in reminders:
        await message.answer(
            format_reminder_card(reminder),
            reply_markup=None if archived else reminder_actions_keyboard(reminder.id),
        )


@router.message(F.text == "📅 На сегодня")
async def reminders_today(message: Message) -> None:
    local_today = today_local()
    start = datetime.combine(local_today, time(0, 0), tzinfo=KYIV_TZ).astimezone(UTC)
    end = start + timedelta(days=1)
    await list_reminders(message, start=start, end=end, archived=False)


@router.message(F.text == "📆 На завтра")
async def reminders_tomorrow(message: Message) -> None:
    local_today = today_local() + timedelta(days=1)
    start = datetime.combine(local_today, time(0, 0), tzinfo=KYIV_TZ).astimezone(UTC)
    end = start + timedelta(days=1)
    await list_reminders(message, start=start, end=end, archived=False)


@router.message(F.text == "📋 Все")
async def reminders_all(message: Message) -> None:
    await list_reminders(message, start=datetime.now(tz=UTC), end=None, archived=False)


@router.message(F.text == "📦 Архив")
async def reminders_archived(message: Message) -> None:
    await list_reminders(message, start=None, end=None, archived=True)


@router.callback_query(F.data.startswith("rem:delete:"))
async def reminder_delete(callback: CallbackQuery) -> None:
    reminder_id = int(callback.data.split(":")[2])
    await db_manager.delete_reminder(reminder_id)
    if scheduler:
        await scheduler.remove_alerts_for_reminder(reminder_id)
    await callback.message.edit_text("Напоминание удалено.")
    await callback.answer()


# --- tasks ---------------------------------------------------------------------


@router.message(F.text == "✅ Задачи")
async def tasks_menu(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await ensure_user_registered(message.chat.id, message.from_user.id)
    await message.answer("Раздел «Задачи».", reply_markup=tasks_menu_keyboard())


@router.message(TaskCreation.entering_text)
async def task_text_entered(message: Message, state: FSMContext) -> None:
    task = await db_manager.create_task(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
        created_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer(
        f"Задача добавлена: {task.text}", reply_markup=tasks_menu_keyboard()
    )


@router.message(F.text == "➕ Создать задачу")
async def task_create(message: Message, state: FSMContext) -> None:
    await state.set_state(TaskCreation.entering_text)
    await message.answer("Введите текст задачи", reply_markup=cancel_keyboard())


@router.message(F.text == "📋 Все задачи")
async def task_list(message: Message) -> None:
    tasks = await db_manager.list_tasks(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        archived=False,
    )
    if not tasks:
        await message.answer("Пока задач нет. Добавьте первую!")
        return
    for task in tasks:
        await message.answer(
            f"• {task.text}",
            reply_markup=task_item_actions_keyboard(task.id),
        )


@router.callback_query(F.data.startswith("task:"))
async def task_actions(callback: CallbackQuery) -> None:
    _, action, raw_id = callback.data.split(":")
    task_id = int(raw_id)
    if action == "done":
        await db_manager.archive_task(task_id, datetime.now(tz=UTC))
        await callback.message.edit_text("Задача выполнена ✅")
    elif action == "del":
        await db_manager.delete_task(task_id)
        await callback.message.edit_text("Задача удалена.")
    await callback.answer()


# --- shopping ------------------------------------------------------------------


@router.message(F.text == "🛒 Покупки")
async def shopping_menu(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await ensure_user_registered(message.chat.id, message.from_user.id)
    await message.answer("Раздел «Список покупок».", reply_markup=shopping_menu_keyboard())


@router.message(ShoppingCreation.entering_text)
async def shopping_text(message: Message, state: FSMContext) -> None:
    await db_manager.create_shopping_item(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
        created_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer("Добавлено в список.", reply_markup=shopping_menu_keyboard())


@router.message(F.text == "➕ Добавить позицию")
async def shopping_add(message: Message, state: FSMContext) -> None:
    await state.set_state(ShoppingCreation.entering_text)
    await message.answer("Что купить?", reply_markup=cancel_keyboard())


@router.message(F.text == "📋 Посмотреть список")
async def shopping_list(message: Message) -> None:
    items = await db_manager.list_shopping(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        archived=False,
    )
    if not items:
        await message.answer("Список пуст.")
        return
    for item in items:
        await message.answer(
            f"• {item.text}",
            reply_markup=shopping_item_actions_keyboard(item.id),
        )


@router.message(F.text == "📦 История")
async def shopping_archive(message: Message) -> None:
    items = await db_manager.list_shopping(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        archived=True,
    )
    if not items:
        await message.answer("Архив пуст.")
        return
    text = "\n".join(f"• {item.text}" for item in items)
    await message.answer(text)


@router.callback_query(F.data.startswith("shop:"))
async def shopping_actions(callback: CallbackQuery) -> None:
    _, action, raw_id = callback.data.split(":")
    item_id = int(raw_id)
    if action == "done":
        await db_manager.archive_shopping_item(item_id)
        await callback.message.edit_text("Перенесено в купленные ✅")
    elif action == "del":
        await db_manager.delete_shopping_item(item_id)
        await callback.message.edit_text("Удалено из списка.")
    await callback.answer()


# --- rituals -------------------------------------------------------------------


@router.message(F.text == "🧘 Ритуалы")
async def rituals_menu(message: Message) -> None:
    await ensure_user_registered(message.chat.id, message.from_user.id)
    presets_added = await db_manager.list_ritual_presets(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await message.answer(
        "🧘 Мои ритуалы. Выберите, что добавить в напоминания:",
        reply_markup=rituals_menu_keyboard(presets_added),
    )


@router.callback_query(F.data.startswith("rit:preset:"))
async def ritual_show(callback: CallbackQuery) -> None:
    preset_key = callback.data.split(":")[2]
    preset = RITUAL_PRESETS.get(preset_key)
    if not preset:
        await callback.answer("Неизвестный ритуал", show_alert=True)
        return
    text = (
        f"<b>{preset.title}</b>\n"
        f"{preset.summary}\n\n"
        f"Как выполнять: {preset.steps}\n\n"
        "Добавить напоминание на сегодня или завтра?"
    )
    await callback.message.edit_text(
        text,
        reply_markup=ritual_schedule_keyboard(preset.key),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rit:schedule:"))
async def ritual_schedule(callback: CallbackQuery) -> None:
    _, _, preset_key, day = callback.data.split(":")
    preset = RITUAL_PRESETS.get(preset_key)
    if not preset:
        await callback.answer("Неизвестный пресет", show_alert=True)
        return
    base_date = today_local()
    if day == "tomorrow":
        base_date += timedelta(days=1)
    event_local = datetime.combine(base_date, time(preset.hour, preset.minute), tzinfo=KYIV_TZ)
    reminder_text = f"{preset.title}: {preset.steps}"
    reminder, alerts = await db_manager.create_reminder(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        text=reminder_text,
        event_ts_utc=event_local.astimezone(UTC),
        created_utc=datetime.now(tz=UTC),
        alert_times_utc=compute_alert_datetimes(event_local.astimezone(UTC), {"15", "0"}),
    )
    await db_manager.mark_ritual_added(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        preset_key=preset.key,
        text=reminder_text,
        created_utc=datetime.now(tz=UTC),
    )
    if scheduler:
        await scheduler.schedule_alerts(alerts)
    await callback.message.edit_text(
        "Ритуал добавлен в напоминания!",
        reply_markup=reminder_actions_keyboard(reminder.id),
    )
    await callback.answer()


# --- daily plan ----------------------------------------------------------------


@router.message(F.text == "🗓 План дня")
async def daily_plan_menu(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await ensure_user_registered(message.chat.id, message.from_user.id)
    await message.answer(
        "План дня на сегодня.",
        reply_markup=daily_plan_menu_keyboard(),
    )


@router.message(DailyPlanStates.entering_item)
async def daily_plan_item_text(message: Message, state: FSMContext) -> None:
    today_code = today_local().isoformat()
    count = await db_manager.plan_items_count(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        date_ymd=today_code,
    )
    if count >= MAX_PLAN_ITEMS:
        await state.clear()
        await message.answer(
            "Уже есть три MIT на сегодня. Посмотрите список.",
            reply_markup=daily_plan_menu_keyboard(),
        )
        return
    await db_manager.add_plan_item(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        date_ymd=today_code,
        item=message.text,
        created_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer(
        "MIT добавлен.", reply_markup=daily_plan_menu_keyboard()
    )


@router.message(F.text == "➕ Добавить пункт")
async def daily_plan_add(message: Message, state: FSMContext) -> None:
    today_code = today_local().isoformat()
    count = await db_manager.plan_items_count(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        date_ymd=today_code,
    )
    if count >= MAX_PLAN_ITEMS:
        await message.answer("Уже есть 3 MIT. Закрывайте их!")
        return
    await state.set_state(DailyPlanStates.entering_item)
    await message.answer("Какой MIT добавить?", reply_markup=cancel_keyboard())


def format_plan_items(items: Sequence[DailyPlanItem]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        prefix = "✅" if item.done else "▫️"
        lines.append(f"{prefix} {idx}. {item.item}")
    return "\n".join(lines)


@router.message(F.text == "📋 Показать план")
async def daily_plan_show(message: Message) -> None:
    items = await db_manager.list_plan_items(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        date_ymd=today_local().isoformat(),
    )
    if not items:
        await message.answer("План пуст. Добавьте 1–3 MIT.")
        return
    await message.answer(format_plan_items(items))


@router.message(F.text == "✅ Отметить выполнено")
async def daily_plan_mark(message: Message) -> None:
    items = await db_manager.list_plan_items(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        date_ymd=today_local().isoformat(),
    )
    pending = [(item.id, item.item[:40]) for item in items if not item.done]
    await message.answer(
        "Что готово?",
        reply_markup=daily_plan_items_keyboard(pending),
    )


@router.callback_query(F.data.startswith("plan:done:"))
async def daily_plan_done(callback: CallbackQuery) -> None:
    item_id = int(callback.data.split(":")[2])
    await db_manager.mark_plan_done(item_id, datetime.now(tz=UTC))
    await callback.message.edit_text("Отлично! MIT отмечен выполненным.")
    await callback.answer()


# --- notes ---------------------------------------------------------------------


@router.message(F.text == "🗒 Заметки")
async def notes_menu(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await ensure_user_registered(message.chat.id, message.from_user.id)
    await message.answer("Раздел заметок.", reply_markup=notes_menu_keyboard())


@router.message(NoteStates.entering_text)
async def note_enter(message: Message, state: FSMContext) -> None:
    await db_manager.add_note(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
        created_ts=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer("Заметка сохранена.", reply_markup=notes_menu_keyboard())


@router.message(F.text == "🗒 Заметка")
async def note_add(message: Message, state: FSMContext) -> None:
    await state.set_state(NoteStates.entering_text)
    await message.answer("Напишите заметку одним сообщением.", reply_markup=cancel_keyboard())


@router.message(F.text == "📋 Мои заметки")
async def note_list(message: Message) -> None:
    notes = await db_manager.list_notes(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        limit=10,
    )
    keyboard = notes_list_keyboard([(note.id, note.text[:40]) for note in notes])
    lines = ["Ваши заметки:"]
    for note in notes:
        lines.append(f"• {note.text}")
    if not notes:
        lines = ["Заметок пока нет."]
    await message.answer("\n".join(lines), reply_markup=keyboard)


@router.callback_query(F.data.startswith("note:del:"))
async def note_delete(callback: CallbackQuery) -> None:
    note_id = int(callback.data.split(":")[2])
    await db_manager.delete_note(note_id)
    await callback.message.edit_text("Заметка удалена.")
    await callback.answer()


# --- daily review --------------------------------------------------------------


async def start_daily_review(message: Message, state: FSMContext, date_code: str) -> None:
    await state.set_state(DailyReviewStates.choosing_mit)
    await state.update_data(review_date=date_code)
    await message.answer(
        "Сделал ли MIT'ы сегодня?",
        reply_markup=review_mit_keyboard(),
    )


@router.callback_query(F.data.startswith("review:start:"))
async def review_start(callback: CallbackQuery, state: FSMContext) -> None:
    date_code = callback.data.split(":")[2]
    await start_daily_review(callback.message, state, date_code)
    await callback.answer()


@router.callback_query(F.data.startswith("review:skip:"))
async def review_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Ок, напомню завтра.")
    await callback.answer()


@router.callback_query(DailyReviewStates.choosing_mit, F.data.startswith("review:mit:"))
async def review_choose_mit(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":")[2]
    await state.update_data(review_mit=choice)
    await state.set_state(DailyReviewStates.choosing_mood)
    await callback.message.edit_text(
        "Оцени день по шкале 1–5", reply_markup=review_mood_keyboard()
    )
    await callback.answer()


@router.callback_query(DailyReviewStates.choosing_mood, F.data.startswith("review:mood:"))
async def review_choose_mood(callback: CallbackQuery, state: FSMContext) -> None:
    mood = int(callback.data.split(":")[2])
    await state.update_data(review_mood=mood)
    await state.set_state(DailyReviewStates.entering_gratitude)
    await callback.message.edit_text(
        "За что благодарен сегодня?", reply_markup=cancel_keyboard()
    )
    await callback.answer()


@router.message(DailyReviewStates.entering_gratitude)
async def review_gratitude(message: Message, state: FSMContext) -> None:
    await state.update_data(review_gratitude=message.text)
    await state.set_state(DailyReviewStates.entering_notes)
    await message.answer("Какие заметки или выводы?", reply_markup=cancel_keyboard())


@router.message(DailyReviewStates.entering_notes)
async def review_notes(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    date_code: str = data.get("review_date")
    summary = (
        "Готово. Проверьте запись:\n"
        f"MIT: {data.get('review_mit')}\n"
        f"Оценка: {data.get('review_mood')}\n"
        f"Благодарность: {data.get('review_gratitude')}\n"
        f"Заметки: {message.text}"
    )
    await state.update_data(review_notes=message.text)
    await state.set_state(DailyReviewStates.confirming)
    await message.answer(
        summary,
        reply_markup=review_confirm_keyboard(date_code),
    )


@router.callback_query(DailyReviewStates.confirming, F.data.startswith("review:save:"))
async def review_save(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    date_code = callback.data.split(":")[2]
    await db_manager.upsert_daily_review(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        date_ymd=date_code,
        mit_done=data.get("review_mit", ""),
        mood=int(data.get("review_mood", 0)),
        gratitude=data.get("review_gratitude", ""),
        notes=data.get("review_notes", ""),
        created_ts_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await callback.message.edit_text("Чекпоинт сохранён. Отличная работа!")
    await callback.answer()


@router.callback_query(DailyReviewStates.confirming, F.data.startswith("review:cancel:"))
async def review_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Чекпоинт пропущен. До завтра!")
    await callback.answer()


# --- report --------------------------------------------------------------------


@router.message(F.text == "📈 Отчёт")
async def show_report(message: Message) -> None:
    await ensure_user_registered(message.chat.id, message.from_user.id)
    done_mit, total_mit, streak, tasks_done = await db_manager.weekly_report(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        today=today_local(),
    )
    report_lines = [
        "📈 Отчёт за неделю:",
        f"• Сделано MIT: {done_mit}/{total_mit}",
        f"• Стабильность чекпоинтов: {streak} дн.",
        f"• Завершено задач: {tasks_done}",
    ]
    await message.answer("\n".join(report_lines))


# --- application ----------------------------------------------------------------


async def main() -> None:
    await db_manager.init()
    logger.info(get_version_line())

    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set")
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    global scheduler
    scheduler = SchedulerManager(db_manager, bot)
    dp = Dispatcher(storage=MemoryStorage())
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="version", description="Показать версию бота"),
        ]
    )
    dp.include_router(version_router)
    dp.include_router(router)

    async def on_startup() -> None:
        await scheduler.start()
        logger.info("Scheduler started")

    async def on_shutdown() -> None:
        if scheduler:
            await scheduler.shutdown()
        await bot.session.close()

    await dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown)


if __name__ == "__main__":
    asyncio.run(main())
