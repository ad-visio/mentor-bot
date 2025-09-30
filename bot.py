from __future__ import annotations

import aiosqlite
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from zoneinfo import ZoneInfo
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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
    simple_back_keyboard,
    tasks_menu_keyboard,
    task_item_actions_keyboard,
    shopping_menu_keyboard,
    shopping_item_actions_keyboard,
    rituals_menu_keyboard,
)
from scheduler import SchedulerManager
from storage import DBManager, Reminder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mentor.db"
KYIV_TZ = ZoneInfo("Europe/Kyiv")
UTC = ZoneInfo("UTC")


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
            and self.alerts
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

RITUAL_PRESETS = {
    1: {"label": "Утро 15–20 мин", "type": "daily", "hour": 8, "minute": 0, "text": "🧩 Ритуал: Утро (дыхание 4×4×4, визуализация, 3 благодарности, 1 шаг к деньгам)"},
    2: {"label": "Полуденный ресет 3–5 мин", "type": "daily", "hour": 13, "minute": 0, "text": "🧩 Ритуал: Полуденный ресет (10 вдохов, 1 шаг к цели)"},
    3: {"label": "Фокус-блок 50/10", "type": "daily", "hour": 10, "minute": 0, "text": "🧩 Ритуал: Фокус-блок (50 мин глубокой работы + 10 мин перерыв)"},
    4: {"label": "Вечер 10–15 мин", "type": "daily", "hour": 21, "minute": 30, "text": "🧩 Ритуал: Вечер (выгрузка, 3 благодарности, музыка/медитация)"},
    5: {"label": "Еженедельное резюме (вс)", "type": "weekly", "weekday": 6, "hour": 19, "minute": 0, "text": "🧩 Ритуал: Резюме недели (победы/уроки, 3 фокуса, денежная лестница)"},
}
RITUAL_GUIDE = [
    ("Дыхание 4×4×4 (5 минут)", "Фокус и снижение стресса. Дыши: 4с вдох — 4с задержка — 4с выдох. 5 минут."),
    ("Журнал изобилия (3 записи)", "Замечать «богатство» вокруг: доход, подарки, удачи, красота. 3 пункта в день."),
    ("Музыкальный якорь (3–5 минут)", "Включи свой трек-якорь. Сядь ровно, расправь плечи, настрой намерение."),
    ("Визуализация «тёплый денежный дождь» (3 минуты)", "Представь мягкий тёплый поток сверху вниз — спокойная уверенность и изобилие."),
    ("Одна мысль (2 минуты)", "Сядь в тишине. Держи одну добрую мысль. Если «улетел» — мягко возвращайся."),
]


async def show_main_menu(message: Message) -> None:
    await message.answer(
        "Привет! Я твой бот-наставник. Выбери раздел 👇",
        reply_markup=main_menu_keyboard(),
    )


async def show_reminders_menu(message: Message) -> None:
    await message.answer("Раздел «Напоминания». Что делаем?", reply_markup=reminders_menu_keyboard())


async def reset_state(state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()


def format_reminder_card(reminder: Reminder) -> str:
    local_dt = reminder.event_ts_utc.astimezone(KYIV_TZ)
    return (
        f"<b>{local_dt.strftime('%d.%m.%Y')} · {local_dt.strftime('%H:%M')}</b>\n"
        f"{reminder.text}"
    )


def compute_alert_datetimes(event_dt_utc: datetime, selected: Iterable[str]) -> List[datetime]:
    now_utc = datetime.now(tz=UTC)
    alerts: List[datetime] = []
    for _label, value in ALERT_OPTIONS:
        minutes = int(value)
        if value not in selected:
            continue
        alert_time = event_dt_utc - timedelta(minutes=minutes)
        if alert_time > now_utc:
            alerts.append(alert_time)
    return alerts


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
        await message.answer("Мы уже на главной.", reply_markup=main_menu_keyboard())
        return
    if current == ReminderCreation.entering_text:
        await state.set_state(ReminderCreation.choosing_alerts)
        data = await state.get_data()
        draft: ReminderDraft = data.get("draft")
        await message.answer("Выбери уведомления:", reply_markup=simple_back_keyboard())
        await message.answer(
            "Когда напомнить?", reply_markup=alerts_keyboard(draft.alerts)
        )
    elif current == ReminderCreation.choosing_alerts:
        await state.set_state(ReminderCreation.choosing_minute)
        await message.answer("Теперь выбери минуты:", reply_markup=simple_back_keyboard())
        await message.answer("Минуты:", reply_markup=minutes_keyboard())
    elif current == ReminderCreation.choosing_minute:
        await state.set_state(ReminderCreation.choosing_hour)
        await message.answer("Выбери час:", reply_markup=simple_back_keyboard())
        await message.answer("Часы:", reply_markup=hours_keyboard())
    elif current in (ReminderCreation.choosing_hour, ReminderCreation.choosing_custom_date):
        await state.set_state(ReminderCreation.choosing_date)
        await message.answer(
            "Когда напомнить?", reply_markup=reminder_date_choice_keyboard()
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
        "Я помогу с напоминаниями, задачами и списками. Начни с выбора раздела."
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
    draft: ReminderDraft = data.get("draft")
    if not draft:
        draft = ReminderDraft()
        await state.update_data(draft=draft)
    choice = callback.data.split(":", 1)[1]
    today = datetime.now(tz=KYIV_TZ).date()
    if choice == "today":
        draft.target_date = today
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text("Выбран сегодня. Теперь час:")
        await callback.message.answer("Выбери час:", reply_markup=hours_keyboard())
    elif choice == "tomorrow":
        draft.target_date = today + timedelta(days=1)
        await state.set_state(ReminderCreation.choosing_hour)
        await callback.message.edit_text("Завтра так завтра! Час?")
        await callback.message.answer("Выбери час:", reply_markup=hours_keyboard())
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


@router.callback_query(F.data.startswith("cal:"))
async def handle_calendar(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    action = parts[1]

    # Нажатия на «пустые» ячейки календаря игнорируем
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

        draft: ReminderDraft | None = data.get("draft")
        if not draft:
            draft = ReminderDraft()

        draft.target_date = date(year, month_num, day)
        await state.update_data(draft=draft, calendar_month=CalendarMonth(year=year, month=month_num))
        await state.set_state(ReminderCreation.choosing_hour)

        await callback.message.edit_text(
            f"Дата выбрана: {draft.target_date.strftime('%d.%m.%Y')}. Теперь час:"
        )
        await callback.message.answer("Выбери час:", reply_markup=hours_keyboard())
        await callback.answer()
        return


async def finalize_reminder(message: Message, state: FSMContext, text: str) -> None:
    data = await state.get_data()
    draft: ReminderDraft = data.get("draft")
    if not draft or not draft.is_complete:
        await message.answer("Не хватает данных. Давай начнём заново.")
        await state.clear()
        return
    event_dt_utc = draft.build_event_datetime()
    now_local = datetime.now(tz=KYIV_TZ)
    if event_dt_utc <= now_local.astimezone(UTC):
        await message.answer(
            "Это время уже в прошлом. Выбери другое.", reply_markup=reminders_menu_keyboard()
        )
        await state.clear()
        return
    alert_times = compute_alert_datetimes(event_dt_utc, draft.alerts)
    reminder, alerts = await db_manager.create_reminder(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=text.strip(),
        event_ts_utc=event_dt_utc,
        created_utc=datetime.now(tz=UTC),
        alert_times_utc=alert_times,
    )
    if scheduler:
        await scheduler.create_jobs_for_alerts(alerts)
    await message.answer("Напоминание сохранено!", reply_markup=reminders_menu_keyboard())
    await message.answer(format_reminder_card(reminder), reply_markup=reminder_actions_keyboard(reminder.id))
    await state.clear()


@router.message(ReminderCreation.entering_text, F.text & ~F.text.startswith("/"))
async def reminder_text_entered(message: Message, state: FSMContext) -> None:
    await finalize_reminder(message, state, message.text)


@router.message(ReminderCreation.entering_text)
async def reminder_text_invalid(message: Message) -> None:
    await message.answer("Напиши текст напоминания одной строкой, пожалуйста.")


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
    end = (datetime.combine(today + timedelta(days=1), time.min, tzinfo=KYIV_TZ).astimezone(UTC))
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
    await send_reminder_list(message, reminders, "В архиве пусто.")


@router.callback_query(F.data.startswith("rem:"))
async def reminder_actions(callback: CallbackQuery) -> None:
    if not scheduler:
        await callback.answer("Сервис временно недоступен", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[1]
    reminder_id = int(parts[2])
    reminder = await db_manager.get_reminder(reminder_id)
    if not reminder:
        await callback.answer("Напоминание не найдено", show_alert=True)
        return

    if action == "delete":
        await db_manager.archive_reminder(reminder_id)
        try:
            await callback.message.edit_text("Напоминание удалено.")
        except Exception:
            # если сообщение уже редактировали/удаляли — молча игнорим
            pass
        await callback.answer("Готово")
    else:
        await callback.answer()


async def handle_snooze_action(callback: CallbackQuery, reminder: Reminder, value: str) -> None:
    now_utc = datetime.now(tz=UTC)
    if value == "tomorrow_morning":
        new_time_local = datetime.combine(
            datetime.now(tz=KYIV_TZ).date() + timedelta(days=1),
            time(9, 0),
            tzinfo=KYIV_TZ,
        )
        new_alert_time = new_time_local.astimezone(UTC)
    else:
        minutes = int(value)
        new_alert_time = now_utc + timedelta(minutes=minutes)
    if new_alert_time <= now_utc:
        await callback.answer("Это время уже прошло.", show_alert=True)
        return
    alerts = await db_manager.add_alerts(reminder.id, [new_alert_time])
    if scheduler:
        await scheduler.create_jobs_for_alerts(alerts)
    await callback.answer("Отложено")


@router.message(F.text == "✅ Задачи")
async def tasks_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Раздел задач:", reply_markup=tasks_menu_keyboard())

@router.message(F.text == "➕ Создать задачу")
async def task_ask(message: Message, state: FSMContext) -> None:
    await state.set_state(SimpleTextState.awaiting_task_text)
    await message.answer("📝 Напиши текст задачи одной строкой.", reply_markup=simple_back_keyboard())

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

@router.message(F.text == "📋 Список задач")
async def task_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_tasks(message.chat.id, message.from_user.id if message.from_user else 0, archived=False)
    if not rows:
        await message.answer("Пока задач нет ✨", reply_markup=tasks_menu_keyboard())
        return
    for t in rows:
        local = t.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
        await message.answer(f"• {t.text}\n<i>создано {local}</i>", reply_markup=task_item_actions_keyboard(t.id))

@router.message(F.text == "📦 Архив задач")
async def task_archive(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_tasks(message.chat.id, message.from_user.id if message.from_user else 0, archived=True)
    if not rows:
        await message.answer("Архив задач пуст.", reply_markup=tasks_menu_keyboard())
        return
    for t in rows:
        local = t.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
        await message.answer(f"🗄 {t.text}\n<i>создано {local}</i>")

@router.callback_query(F.data.startswith("task:"))
async def task_actions(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    task_id = int(parts[2])
    if action == "done":
        await db_manager.archive_task(task_id)
        await callback.message.edit_text("✅ Перемещено в архив.")
        await callback.answer()
    elif action == "del":
        await db_manager.delete_task(task_id)
        await callback.message.edit_text("🗑 Удалено.")
        await callback.answer()
    else:
        await callback.answer()
# === ЗАДАЧИ ===
@router.message(F.text == "✅ Задачи")
async def tasks_entry(message: Message, state: FSMContext) -> None:
    await state.set_state(SimpleTextState.awaiting_task_text)
    await message.answer("Напиши текст задачи одной строкой. Или нажми «📋 Все задачи» в меню.", reply_markup=simple_back_keyboard())

@router.message(F.text == "📋 Все задачи")
async def tasks_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.get_tasks(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        limit=100
    )
    if not rows:
        await message.answer("Пока задач нет. Нажми «✅ Задачи» и создай первую.")
        return
    out = ["<b>Задачи:</b>"]
    for r in rows:
        out.append(f"• {r['text']}  <i>(id={r['id']})</i>")
    await message.answer("\n".join(out))

@router.message(SimpleTextState.awaiting_task_text, F.text & ~F.text.startswith("/"))
async def task_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_task(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await message.answer("✅ Задача сохранена. Посмотреть: «📋 Все задачи».", reply_markup=main_menu_keyboard())
    await state.clear()

@router.message(SimpleTextState.awaiting_task_text)
async def task_invalid(message: Message) -> None:
    await message.answer("Пришли текст задачи без вложений или нажми «🏠 На главную».")


@router.message(SimpleTextState.awaiting_task_text, F.text & ~F.text.startswith("/"))
async def task_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_task(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await message.answer("Задача записана!", reply_markup=main_menu_keyboard())
    await state.clear()


@router.message(SimpleTextState.awaiting_task_text)
async def task_invalid(message: Message) -> None:
    await message.answer("Пришли текст задачи без вложений.")


@router.message(F.text == "🔁 Ритуалы")
async def rituals_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔁 Ритуалы:", reply_markup=rituals_menu_keyboard())


@router.message(SimpleTextState.awaiting_ritual_text, F.text & ~F.text.startswith("/"))
async def ritual_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_ritual(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await message.answer("Сохранил, вернёмся к этому позже!", reply_markup=main_menu_keyboard())
    await state.clear()


@router.message(SimpleTextState.awaiting_ritual_text)
async def ritual_invalid(message: Message) -> None:
    await message.answer("Жду текстовую заметку.")
@router.message(F.text == "🧩 Пресеты ритуалов")
async def rituals_presets(message: Message) -> None:
    presets = [(pid, cfg["label"]) for pid, cfg in RITUAL_PRESETS.items()]
    await message.answer("Выбери пресет для включения:", reply_markup=rituals_presets_keyboard(presets))
@router.callback_query(F.data.startswith("rit:enable:"))
async def ritual_enable(callback: CallbackQuery) -> None:
    if not scheduler:
        await callback.answer("Сервис недоступен", show_alert=True); return

    pid = int(callback.data.split(":")[2])
    cfg = RITUAL_PRESETS.get(pid)
    if not cfg:
        await callback.answer("Не найден пресет", show_alert=True); return

    # сохраняем сам ритуал (чтобы отобразить в «Мои ритуалы»)
    await db_manager.create_ritual(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id if callback.from_user else 0,
        text=cfg["label"],
        created_utc=datetime.now(tz=UTC),
    )

    # создадим напоминания на 14 дней вперёд
    now_local = datetime.now(tz=KYIV_TZ)
    created_alerts_all = []
    for d in range(0, 14):
        day = (now_local.date() + timedelta(days=d))
        if cfg["type"] == "weekly":
            if day.weekday() != cfg.get("weekday", 6):
                continue
        event_local = datetime.combine(day, time(cfg.get("hour", 9), cfg.get("minute", 0)), tzinfo=KYIV_TZ)
        if event_local <= now_local:
            continue
        event_utc = event_local.astimezone(UTC)

        reminder, alerts = await db_manager.create_reminder(
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id if callback.from_user else 0,
            text=cfg["text"],
            event_ts_utc=event_utc,
            created_utc=datetime.now(tz=UTC),
            # напоминания по умолчанию: за 15 минут и в момент
            alert_times_utc=[event_utc - timedelta(minutes=15), event_utc],
        )
        created_alerts_all.extend(alerts)

    if scheduler and created_alerts_all:
        await scheduler.create_jobs_for_alerts(created_alerts_all)

    await callback.answer("Ритуал включён ✅")
    await callback.message.edit_text("Ритуал включён. Напоминания созданы на 14 дней.")
@router.message(F.text == "📋 Мои ритуалы")
async def rituals_my(message: Message, state: FSMContext) -> None:
    from storage import DB_PATH as STORAGE_DB_PATH
    async with aiosqlite.connect(STORAGE_DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, text, created_utc FROM rituals "
            "WHERE chat_id=? AND user_id=? "
            "ORDER BY id DESC LIMIT 50",
            (message.chat.id, message.from_user.id if message.from_user else 0)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Пока ритуалов нет. Открой «🧩 Пресеты ритуалов».")
        return
    for r in rows:
        await message.answer(f"• {r['text']}", reply_markup=rituals_list_item_keyboard(r['id']))

@router.callback_query(F.data.startswith("rit:del:"))
async def ritual_delete(callback: CallbackQuery) -> None:
    rid = int(callback.data.split(":")[2])
    from storage import DB_PATH as STORAGE_DB_PATH
    async with aiosqlite.connect(STORAGE_DB_PATH) as conn:
        await conn.execute("DELETE FROM rituals WHERE id=?", (rid,))
        await conn.commit()
    await callback.message.edit_text("Ритуал удалён.")
    await callback.answer("Удалено")


@router.message(F.text == "🛒 Список покупок")
async def shop_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Список покупок:", reply_markup=shopping_menu_keyboard())

@router.message(F.text == "➕ Добавить позицию")
async def shop_add_ask(message: Message, state: FSMContext) -> None:
    await state.set_state(SimpleTextState.awaiting_shopping_text)
    await message.answer("📝 Введи позицию для списка.", reply_markup=simple_back_keyboard())

@router.message(SimpleTextState.awaiting_shopping_text, F.text & ~F.text.startswith("/"))
async def shop_add_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_shopping_item(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await state.clear()
    await message.answer("✅ Добавлено!", reply_markup=shopping_menu_keyboard())
def shopping_item_kb(item_id: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="✅ Куплено", callback_data=f"shop:done:{item_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"shop:del:{item_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
@router.message(F.text == "🛒 Список покупок")
async def shopping_entry(message: Message, state: FSMContext) -> None:
    await state.set_state(SimpleTextState.awaiting_shopping_text)
    await message.answer("Введи позицию. Или нажми «📋 Посмотреть список».", reply_markup=simple_back_keyboard())

@router.message(F.text == "📋 Посмотреть список")
async def shopping_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.get_shopping_items(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        include_bought=False,
    )
    if not rows:
        await message.answer("Список пуст. Добавь позицию во «🛒 Список покупок».")
        return
    for r in rows:
        await message.answer(f"• {r['text']}", reply_markup=shopping_item_kb(r["id"]))

@router.message(SimpleTextState.awaiting_shopping_text, F.text & ~F.text.startswith("/"))
async def shopping_received(message: Message, state: FSMContext) -> None:
    await db_manager.create_shopping_item(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        text=message.text.strip(),
        created_utc=datetime.now(tz=UTC),
    )
    await message.answer("Добавил. Посмотреть: «📋 Посмотреть список».", reply_markup=main_menu_keyboard())
    await state.clear()

@router.message(SimpleTextState.awaiting_shopping_text)
async def shopping_invalid(message: Message) -> None:
    await message.answer("Пока принимаю только текст.")

@router.callback_query(F.data.startswith("shop:"))
async def shopping_actions(callback: CallbackQuery) -> None:
    _, action, sid = callback.data.split(":")
    item_id = int(sid)
    if action == "done":
        await db_manager.mark_shopping_bought(item_id)
        await callback.message.edit_text("✅ Куплено")
        await callback.answer("Отметил как куплено")
    elif action == "del":
        await db_manager.delete_shopping_item(item_id)
        await callback.message.edit_text("🗑 Удалено")
        await callback.answer("Удалил")
RITUAL_PRESETS: list[dict] = [
    {
        "title": "Утренний фокус (20–25 мин)",
        "text": "Дыхание 4×4×4 (3–5 мин) → Журнал изобилия (3 факта) → 1 быстрый шаг к деньгам (10–15 мин)",
        "benefit": "Повышает ясность, запускает денежный рычаг, закрепляет ощущение изобилия."
    },
    {
        "title": "Вечерний якорь (5–10 мин)",
        "text": "Музыка/релакс → 3 благодарности → «золотой кадр» прожитого дня",
        "benefit": "Снижает тревожность, улучшает сон и закрепляет позитивные паттерны."
    },
    {
        "title": "Микро-фокус (5 мин, в течение дня)",
        "text": "Таймер 5 мин → одна задача без отвлечений → короткая запись «что сделал»",
        "benefit": "Лечит прокрастинацию и возвращает чувство контроля."
    }
]
@router.message(F.text == "🔁 Ритуалы")
async def rituals_entry(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Ритуалы. Выбери действие:\n• «🎛 Пресеты» — готовые наборы\n• «📜 Мои ритуалы» — список твоих",
        reply_markup=simple_back_keyboard(),
    )

@router.message(F.text == "🎛 Пресеты")
async def rituals_presets(message: Message) -> None:
    # как раньше: создают напоминания — у тебя эта часть уже работает

    out = ["<b>Рекомендуемые ритуалы:</b>"]
    for p in RITUAL_PRESETS:
        out.append(f"• <b>{p['title']}</b>\n{p['text']}\n<i>Зачем:</i> {p['benefit']}\n")
    await message.answer("\n".join(out))

@router.message(F.text == "📜 Мои ритуалы")
async def my_rituals_list(message: Message) -> None:
    # покажем, что сохранено через /ритуалы (то, что ты сохранял текстом)
    rows = await db_manager.get_rituals(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        limit=100
    )
    out = []
    if rows:
        out.append("<b>Твои ритуалы:</b>")
        for r in rows:
            out.append(f"• {r['text']}  <i>(id={r['id']})</i>")
    else:
        out.append("Пока нет сохранённых ритуалов. Можешь создать их текстом в разделе «🔁 Ритуалы».")
    out.append("\n<b>Справка по рекомендованным:</b>")
    for p in RITUAL_PRESETS:
        out.append(f"• <b>{p['title']}</b>\n{p['text']}\n<i>Зачем:</i> {p['benefit']}\n")
    await message.answer("\n".join(out))

@router.message(F.text == "📋 Список покупок")
async def shop_list(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_shopping(message.chat.id, message.from_user.id if message.from_user else 0, archived=False)
    if not rows:
        await message.answer("Список пуст ✨", reply_markup=shopping_menu_keyboard())
        return
    for it in rows:
        local = it.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
        await message.answer(f"• {it.text}\n<i>добавлено {local}</i>", reply_markup=shopping_item_actions_keyboard(it.id))

@router.message(F.text == "📦 Архив покупок")
async def shop_archive(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db_manager.list_shopping(message.chat.id, message.from_user.id if message.from_user else 0, archived=True)
    if not rows:
        await message.answer("Архив покупок пуст.", reply_markup=shopping_menu_keyboard())
        return
    for it in rows:
        local = it.created_utc.astimezone(KYIV_TZ).strftime("%d.%m %H:%М")
        await message.answer(f"🗄 {it.text}\n<i>добавлено {local}</i>")

@router.callback_query(F.data.startswith("shop:"))
async def shop_actions(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    item_id = int(parts[2])
    if action == "done":
        await db_manager.archive_shopping(item_id)
        await callback.message.edit_text("☑ Перемещено в архив.")
        await callback.answer()
    elif action == "del":
        await db_manager.delete_shopping(item_id)
        await callback.message.edit_text("🗑 Удалено.")
        await callback.answer()
    else:
        await callback.answer()


async def main() -> None:
    global scheduler
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

