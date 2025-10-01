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
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
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
    calendar_keyboard,
    hours_keyboard,
    main_menu_keyboard,
    minutes_keyboard,
    reminder_actions_keyboard,
    reminder_date_choice_keyboard,
    reminders_menu_keyboard,
    rituals_list_item_keyboard,
    rituals_menu_keyboard,
    shopping_item_actions_keyboard,
    shopping_menu_keyboard,
    simple_back_keyboard,
    task_item_actions_keyboard,
    tasks_menu_keyboard,
)
from scheduler import SchedulerManager
from storage import DBManager, Reminder, UTC

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mentor.db"
KYIV_TZ = ZoneInfo("Europe/Kyiv")


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


class ReminderCreation(StatesGroup):
    choosing_date = State()
    choosing_custom_date = State()
    choosing_hour = State()
    choosing_minute = State()
    choosing_alerts = State()
    entering_text = State()


class SimpleTextState(StatesGroup):
    awaiting_task_text = State()
    awaiting_ritual_text = State()
    awaiting_shopping_text = State()


router = Router()
db_manager = DBManager(DB_PATH)
scheduler: SchedulerManager | None = None

RITUAL_PRESETS: Sequence[tuple[str, str, str]] = (
    (
        "Утренний фокус (20 минут)",
        "Дыхание 4×4×4 → Журнал изобилия (3 пункта) → один шаг к цели",
        "Заряжает энергией и задаёт тон дню.",
    ),
    (
        "Полуденный ресет (5 минут)",
        "10 глубоких вдохов → проверить фокус дня → короткая запись итога",
        "Помогает сохранить темп и перезагрузиться.",
    ),
    (
        "Вечерний якорь (10 минут)",
        "Тёплая музыка → 3 благодарности → визуализация успеха",
        "Снижает стресс и улучшает сон.",
    ),
)


async def show_main_menu(message: Message) -> None:
    await message.answer(
        "Привет! Я твой бот-наставник. Выбери раздел 👇",
        reply_markup=main_menu_keyboard(),
    )


async def show_reminders_menu(message: Message) -> None:
    await message.answer(
        "Раздел «Напоминания». Что делаем?",
        reply_markup=reminders_menu_keyboard(),
    )


async def reset_state(state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()


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
        alert_time = event_dt_utc - delta
        if alert_time > now_utc:
            alerts.append(alert_time)
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


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await show_main_menu(message)


@router.message(F.text == "🏠 На главную")
async def go_home(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await show_main_menu(message)


@router.message(F.text == "⬅️ Назад")
async def go_back(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await show_main_menu(message)
        return
    if current == ReminderCreation.entering_text.state:
        await state.set_state(ReminderCreation.choosing_alerts)
        data = await state.get_data()
        draft: ReminderDraft = data.get("draft", ReminderDraft())
        await message.answer("Выбери уведомления:")
        await message.answer("Когда напомнить?", reply_markup=alerts_keyboard(draft.alerts))
    elif current == ReminderCreation.choosing_alerts.state:
        await state.set_state(ReminderCreation.choosing_minute)
        await message.answer("Теперь минуты:")
        await message.answer("Минуты:", reply_markup=minutes_keyboard())
    elif current == ReminderCreation.choosing_minute.state:
        await state.set_state(ReminderCreation.choosing_hour)
        await message.answer("Выбери час:")
        await message.answer("Часы:", reply_markup=hours_keyboard())
    elif current in {
        ReminderCreation.choosing_hour.state,
        ReminderCreation.choosing_custom_date.state,
    }:
        await state.set_state(ReminderCreation.choosing_date)
        await message.answer(
            "Когда напомнить?",
            reply_markup=reminder_date_choice_keyboard(),
        )
    elif current in {
        SimpleTextState.awaiting_task_text.state,
        SimpleTextState.awaiting_ritual_text.state,
        SimpleTextState.awaiting_shopping_text.state,
    }:
        await state.clear()
        await show_main_menu(message)
    else:
        await state.clear()
        await show_reminders_menu(message)


@router.message(F.text == "⏰ Напоминания")
async def reminders_entry(message: Message, state: FSMContext) -> None:
    await reset_state(state)
    await show_reminders_menu(message)


@router.message(F.text == "ℹ️ Помощь")
async def help_handler(message: Message) -> None:
    await message.answer(
        "Я помогу с напоминаниями, задачами, ритуалами и покупками. "
        "Выбери раздел на клавиатуре снизу.",
    )


@router.message(F.text == "➕ Создать")
async def start_reminder_creation(message: Message, state: FSMContext) -> None:
    await state.set_state(ReminderCreation.choosing_date)
    draft = ReminderDraft()
    await state.update_data(draft=draft, calendar_month=None)
    await message.answer("Создаём новое напоминание.", reply_markup=simple_back_keyboard())
    await message.answer(
        "Выбери дату для напоминания:",
        reply_markup=reminder_date_choice_keyboard(),
    )


@router.callback_query(F.data.startswith("date:"))
async def handle_date_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    draft: ReminderDraft = data.get("draft", ReminderDraft())
    choice = callback.data.split(":", 1)[1]
    today = datetime.now(tz=KYIV_TZ).date()
    if choice == "today":
        draft.target_date = today
        await state.update_data(draft=draft)
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text("Сегодня. Выбери час:")
        await callback.message.answer("Часы:", reply_markup=hours_keyboard())
    elif choice == "tomorrow":
        draft.target_date = today + timedelta(days=1)
        await state.update_data(draft=draft)
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text("Завтра. Выбери час:")
        await callback.message.answer("Часы:", reply_markup=hours_keyboard())
    elif choice == "calendar":
        await state.set_state(ReminderCreation.choosing_custom_date)
        month = data.get("calendar_month")
        if not month:
            month = CalendarMonth(year=today.year, month=today.month)
            await state.update_data(calendar_month=month)
        await callback.message.edit_text(
            "Выбери дату на календаре:",
            reply_markup=calendar_keyboard(month),
        )


@router.callback_query(F.data.startswith("cal:"))
async def handle_calendar(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    if action == "ignore":
        await callback.answer()
        return

    data = await state.get_data()
    month: CalendarMonth | None = data.get("calendar_month")
    if not month:
        today_local = datetime.now(tz=KYIV_TZ).date()
        month = CalendarMonth(year=today_local.year, month=today_local.month)

    if action == "prev":
        month = shift_month(month, -1)
        await state.update_data(calendar_month=month)
        await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(month))
        await callback.answer()
        return
    if action == "next":
        month = shift_month(month, 1)
        await state.update_data(calendar_month=month)
        await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(month))
        await callback.answer()
        return
    if action == "select":
        year = int(parts[2])
        month_num = int(parts[3])
        day = int(parts[4])
        draft: ReminderDraft = data.get("draft", ReminderDraft())
        draft.target_date = date(year, month_num, day)
        await state.update_data(
            draft=draft, calendar_month=CalendarMonth(year=year, month=month_num)
        )
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text(
            f"Дата выбрана: {draft.target_date.strftime('%d.%m.%Y')}. Теперь час:",
        )
        await callback.message.answer("Часы:", reply_markup=hours_keyboard())
        await callback.answer()


@router.callback_query(F.data.startswith("hour:"))
async def handle_hour(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    draft: ReminderDraft = data.get("draft", ReminderDraft())
    draft.hour = int(callback.data.split(":")[1])
    await state.update_data(draft=draft)
    await state.set_state(ReminderCreation.choosing_minute)
    await callback.message.edit_text(f"Час {draft.hour:02d}. Теперь минуты:")
    await callback.message.answer("Минуты:", reply_markup=minutes_keyboard())


@router.callback_query(F.data.startswith("minute:"))
async def handle_minute(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    draft: ReminderDraft = data.get("draft", ReminderDraft())
    draft.minute = int(callback.data.split(":")[1])
    await state.update_data(draft=draft)
    await state.set_state(ReminderCreation.choosing_alerts)
    await callback.message.edit_text(f"Время {draft.hour:02d}:{draft.minute:02d}. Уведомления?")
    await callback.message.answer(
        "Выбери, когда напомнить:", reply_markup=alerts_keyboard(draft.alerts)
    )


@router.callback_query(F.data.startswith("alert:"))
async def handle_alert_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    draft: ReminderDraft = data.get("draft", ReminderDraft())
    value = callback.data.split(":")[1]
    if value == "done":
        if not draft.alerts:
            await callback.answer("Нужно выбрать хотя бы одно уведомление", show_alert=True)
            return
        await state.set_state(ReminderCreation.entering_text)
        await callback.message.edit_text("Теперь отправь текст напоминания одной строкой.")
        return
    if value in draft.alerts:
        draft.alerts.remove(value)
    else:
        draft.alerts.add(value)
    await state.update_data(draft=draft)
    await callback.message.edit_reply_markup(reply_markup=alerts_keyboard(draft.alerts))


async def finalize_reminder(message: Message, state: FSMContext, text: str) -> None:
    data = await state.get_data()
    draft: ReminderDraft = data.get("draft")
    if not draft or not draft.is_complete:
        await message.answer("Что-то пошло не так. Попробуй создать напоминание заново.")
        await state.clear()
        return
    event_dt_utc = draft.build_event_datetime()
    if event_dt_utc <= datetime.now(tz=UTC):
        await message.answer(
            "Это время уже в прошлом. Выбери другое.",
            reply_markup=reminders_menu_keyboard(),
        )
        await state.clear()
        return
    alerts_utc = compute_alert_datetimes(event_dt_utc, draft.alerts)
    reminder, alerts = await db_manager.create_reminder(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=text.strip(),
        event_ts_utc=event_dt_utc,
        created_utc=datetime.now(tz=UTC),
        alert_times_utc=alerts_utc,
    )
    if scheduler:
        await scheduler.schedule_alerts(alerts)
    await message.answer("Напоминание сохранено!", reply_markup=reminders_menu_keyboard())
    await message.answer(
        format_reminder_card(reminder),
        reply_markup=reminder_actions_keyboard(reminder.id),
    )
    await state.clear()


@router.message(ReminderCreation.entering_text, F.text & ~F.text.startswith("/"))
async def reminder_text_entered(message: Message, state: FSMContext) -> None:
    await finalize_reminder(message, state, message.text)


@router.message(ReminderCreation.entering_text)
async def reminder_text_invalid(message: Message) -> None:
    await message.answer("Пришли текст напоминания одной строкой, пожалуйста.")


async def send_reminder_list(
    message: Message,
    reminders: Sequence[Reminder],
    empty_text: str,
) -> None:
    if not reminders:
        await message.answer(empty_text)
        return
    for reminder in reminders:
        await message.answer(
            format_reminder_card(reminder),
            reply_markup=reminder_actions_keyboard(reminder.id),
        )


@router.message(F.text == "📅 На сегодня")
async def reminders_today(message: Message, state: FSMContext) -> None:
    await state.clear()
    today = datetime.now(tz=KYIV_TZ).date()
    start = datetime.combine(today, time.min, tzinfo=KYIV_TZ).astimezone(UTC)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=KYIV_TZ).astimezone(UTC)
    reminders = await db_manager.get_reminders_for_range(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        start_utc=start,
        end_utc=end,
        archived=False,
    )
    await send_reminder_list(message, reminders, "На сегодня пока ничего нет.")


@router.message(F.text == "📆 На завтра")
async def reminders_tomorrow(message: Message, state: FSMContext) -> None:
    await state.clear()
    today = datetime.now(tz=KYIV_TZ).date()
    tomorrow = today + timedelta(days=1)
    start = datetime.combine(tomorrow, time.min, tzinfo=KYIV_TZ).astimezone(UTC)
    end = datetime.combine(tomorrow + timedelta(days=1), time.min, tzinfo=KYIV_TZ).astimezone(UTC)
    reminders = await db_manager.get_reminders_for_range(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        start_utc=start,
        end_utc=end,
        archived=False,
    )
    await send_reminder_list(message, reminders, "На завтра планов пока нет.")


@router.message(F.text == "📋 Все")
async def reminders_all(message: Message, state: FSMContext) -> None:
    await state.clear()
    reminders = await db_manager.get_reminders_for_range(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        start_utc=None,
        end_utc=None,
        archived=False,
    )
    await send_reminder_list(message, reminders, "Активных напоминаний нет.")


@router.message(F.text == "📦 Архив")
async def reminders_archive(message: Message, state: FSMContext) -> None:
    await state.clear()
    reminders = await db_manager.get_reminders_for_range(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        start_utc=None,
        end_utc=None,
        archived=True,
    )
    if not reminders:
        await message.answer("Архив напоминаний пуст.")
        return
    for reminder in reminders:
        await message.answer(format_reminder_card(reminder))


@router.callback_query(F.data.startswith("rem:"))
async def reminder_actions(callback: CallbackQuery) -> None:
    if not scheduler:
        await callback.answer("Сервис временно недоступен", show_alert=True)
        return
    _, action, reminder_id_str = callback.data.split(":", 2)
    reminder_id = int(reminder_id_str)
    reminder = await db_manager.get_reminder(reminder_id)
    if not reminder:
        await callback.answer("Напоминание не найдено", show_alert=True)
        return
    if action != "delete":
        await callback.answer()
        return
    await db_manager.archive_reminder(reminder_id)
    await db_manager.mark_alerts_fired_for_reminder(reminder_id)
    await scheduler.remove_alerts_for_reminder(reminder_id)
    await callback.message.edit_text("🗑 Напоминание перемещено в архив.")
    await callback.answer()


# --- tasks ---------------------------------------------------------------------


@router.message(F.text == "✅ Задачи")
async def tasks_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Раздел «Задачи».", reply_markup=tasks_menu_keyboard())


@router.message(F.text == "➕ Создать задачу")
async def tasks_create(message: Message, state: FSMContext) -> None:
    await state.set_state(SimpleTextState.awaiting_task_text)
    await message.answer(
        "Напиши текст задачи одной строкой.",
        reply_markup=simple_back_keyboard(),
    )


@router.message(SimpleTextState.awaiting_task_text, F.text & ~F.text.startswith("/"))
async def task_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_task(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer("✅ Задача сохранена.", reply_markup=tasks_menu_keyboard())


@router.message(SimpleTextState.awaiting_task_text)
async def task_invalid(message: Message) -> None:
    await message.answer("Пришли текст задачи без вложений, пожалуйста.")


@router.message(F.text == "📋 Список задач")
async def tasks_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_tasks(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        archived=False,
    )
    if not rows:
        await message.answer("Пока задач нет. Создай первую!", reply_markup=tasks_menu_keyboard())
        return
    for task in rows:
        local = task.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
        await message.answer(
            f"• {task.text}\n<i>создано {local}</i>",
            reply_markup=task_item_actions_keyboard(task.id),
        )


@router.message(F.text == "📦 Архив задач")
async def tasks_archive(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_tasks(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        archived=True,
    )
    if not rows:
        await message.answer("Архив задач пуст.")
        return
    for task in rows:
        local = task.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
        await message.answer(f"🗄 {task.text}\n<i>создано {local}</i>")


@router.callback_query(F.data.startswith("task:"))
async def task_actions(callback: CallbackQuery) -> None:
    _, action, task_id_str = callback.data.split(":", 2)
    task_id = int(task_id_str)
    if action == "done":
        await db_manager.archive_task(task_id)
        await callback.message.edit_text("✅ Задача перенесена в архив.")
        await callback.answer()
    elif action == "del":
        await db_manager.delete_task(task_id)
        await callback.message.edit_text("🗑 Задача удалена.")
        await callback.answer()
    else:
        await callback.answer()


# --- rituals -------------------------------------------------------------------


@router.message(F.text == "🔁 Ритуалы")
async def rituals_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Раздел «Ритуалы».", reply_markup=rituals_menu_keyboard())


@router.message(F.text == "➕ Добавить ритуал")
async def ritual_add(message: Message, state: FSMContext) -> None:
    await state.set_state(SimpleTextState.awaiting_ritual_text)
    await message.answer(
        "Отправь текст ритуала одной строкой.",
        reply_markup=simple_back_keyboard(),
    )


@router.message(SimpleTextState.awaiting_ritual_text, F.text & ~F.text.startswith("/"))
async def ritual_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_ritual(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer("Сохранил!", reply_markup=rituals_menu_keyboard())


@router.message(SimpleTextState.awaiting_ritual_text)
async def ritual_invalid(message: Message) -> None:
    await message.answer("Жду текст без вложений.")


@router.message(F.text == "🧩 Пресеты")
async def rituals_presets(message: Message, state: FSMContext) -> None:
    await state.clear()
    lines = ["<b>Рекомендуемые ритуалы:</b>"]
    for title, body, benefit in RITUAL_PRESETS:
        lines.append(f"• <b>{title}</b>\n{body}\n<i>Зачем:</i> {benefit}\n")
    await message.answer("\n".join(lines))


@router.message(F.text == "📋 Мои ритуалы")
async def rituals_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_rituals(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
    )
    if not rows:
        await message.answer("Пока ритуалов нет. Добавь свой или выбери пресет.")
        return
    for ritual in rows:
        await message.answer(
            f"• {ritual.text}",
            reply_markup=rituals_list_item_keyboard(ritual.id),
        )


@router.callback_query(F.data.startswith("rit:del:"))
async def ritual_delete(callback: CallbackQuery) -> None:
    ritual_id = int(callback.data.split(":")[2])
    await db_manager.delete_ritual(ritual_id)
    await callback.message.edit_text("Ритуал удалён.")
    await callback.answer("Удалено")


# --- shopping ------------------------------------------------------------------


@router.message(F.text == "🛒 Список покупок")
async def shopping_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Раздел «Покупки».", reply_markup=shopping_menu_keyboard())


@router.message(F.text == "➕ Добавить позицию")
async def shopping_add(message: Message, state: FSMContext) -> None:
    await state.set_state(SimpleTextState.awaiting_shopping_text)
    await message.answer("Введи позицию списка покупок.", reply_markup=simple_back_keyboard())


@router.message(SimpleTextState.awaiting_shopping_text, F.text & ~F.text.startswith("/"))
async def shopping_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_shopping_item(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer("✅ Добавлено!", reply_markup=shopping_menu_keyboard())


@router.message(SimpleTextState.awaiting_shopping_text)
async def shopping_invalid(message: Message) -> None:
    await message.answer("Пока принимаю только текст.")


@router.message(F.text == "📋 Список покупок")
async def shopping_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_shopping(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        archived=False,
    )
    if not rows:
        await message.answer("Список пуст. Добавь первую позицию!", reply_markup=shopping_menu_keyboard())
        return
    for item in rows:
        local = item.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
        await message.answer(
            f"• {item.text}\n<i>добавлено {local}</i>",
            reply_markup=shopping_item_actions_keyboard(item.id),
        )


@router.message(F.text == "📦 Архив покупок")
async def shopping_archive(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_shopping(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        archived=True,
    )
    if not rows:
        await message.answer("Архив покупок пуст.")
        return
    for item in rows:
        local = item.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
        await message.answer(f"🗄 {item.text}\n<i>добавлено {local}</i>")


@router.callback_query(F.data.startswith("shop:"))
async def shopping_actions(callback: CallbackQuery) -> None:
    _, action, item_id_str = callback.data.split(":", 2)
    item_id = int(item_id_str)
    if action == "done":
        await db_manager.archive_shopping_item(item_id)
        await callback.message.edit_text("☑ Перемещено в архив.")
        await callback.answer()
    elif action == "del":
        await db_manager.delete_shopping_item(item_id)
        await callback.message.edit_text("🗑 Удалено.")
        await callback.answer()
    else:
        await callback.answer()


async def main() -> None:
    global scheduler
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)

    await db_manager.init()
    scheduler = SchedulerManager(db_manager, bot)
    await scheduler.start()

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
