from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# --- shared ---------------------------------------------------------------------


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="⏰ Напоминания")
    builder.button(text="✅ Задачи")
    builder.button(text="🧘 Ритуалы")
    builder.button(text="🛒 Покупки")
    builder.button(text="🗓 План дня")
    builder.button(text="🗒 Заметки")
    builder.button(text="📈 Отчёт")
    builder.adjust(2, 2, 3)
    return builder.as_markup(resize_keyboard=True)


def simple_back_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


# --- reminders -----------------------------------------------------------------

ALERT_OPTIONS: Sequence[tuple[str, str]] = (
    ("За 24 ч", "1440"),
    ("За 3 ч", "180"),
    ("За 1 ч", "60"),
    ("За 30 мин", "30"),
    ("За 15 мин", "15"),
    ("В момент", "0"),
)

ALERT_DEFAULT_SELECTION = {"15", "0"}


@dataclass(slots=True)
class CalendarMonth:
    year: int
    month: int


def reminders_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Создать")
    builder.button(text="📅 На сегодня")
    builder.button(text="📆 На завтра")
    builder.button(text="📋 Все")
    builder.button(text="📦 Архив")
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def reminder_date_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="date:today")
    builder.button(text="Завтра", callback_data="date:tomorrow")
    builder.button(text="📅 Другая дата", callback_data="date:calendar")
    builder.adjust(3)
    return builder.as_markup()


def hours_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for hour in range(24):
        builder.button(text=f"{hour:02d}", callback_data=f"hour:{hour}")
    builder.adjust(6, 6, 6, 6)
    return builder.as_markup()


REMINDER_MINUTES = (0, 10, 20, 40, 50)


def minutes_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minute in REMINDER_MINUTES:
        builder.button(text=f"{minute:02d}", callback_data=f"minute:{minute}")
    builder.adjust(3, 2)
    return builder.as_markup()


def alerts_keyboard(selected: Iterable[str]) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    builder = InlineKeyboardBuilder()
    for label, value in ALERT_OPTIONS:
        prefix = "✅" if value in selected_set else "▫️"
        builder.button(text=f"{prefix} {label}", callback_data=f"alert:{value}")
    builder.button(text="Готово", callback_data="alert:done")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def reminder_actions_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Удалить", callback_data=f"rem:delete:{reminder_id}")
    return builder.as_markup()


def calendar_keyboard(month: CalendarMonth) -> InlineKeyboardMarkup:
    import calendar

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"{calendar.month_name[month.month]} {month.year}",
        callback_data="cal:ignore",
    )
    builder.adjust(1)

    for day in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"):
        builder.button(text=day, callback_data="cal:ignore")
    builder.adjust(7)

    cal = calendar.Calendar(firstweekday=0)
    for week in cal.monthdayscalendar(month.year, month.month):
        for day in week:
            if day == 0:
                builder.button(text=" ", callback_data="cal:ignore")
            else:
                builder.button(
                    text=str(day), callback_data=f"cal:select:{month.year}:{month.month}:{day}"
                )
        builder.adjust(7)

    builder.button(text="«", callback_data="cal:prev")
    builder.button(text="»", callback_data="cal:next")
    builder.adjust(2)
    return builder.as_markup()


# --- tasks ---------------------------------------------------------------------


def tasks_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Создать задачу")
    builder.button(text="📋 Все задачи")
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def task_item_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data=f"task:done:{task_id}")
    builder.button(text="🗑 Удалить", callback_data=f"task:del:{task_id}")
    builder.adjust(2)
    return builder.as_markup()


# --- shopping ------------------------------------------------------------------


def shopping_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить позицию")
    builder.button(text="📋 Посмотреть список")
    builder.button(text="📦 История")
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def shopping_item_actions_keyboard(item_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Куплено", callback_data=f"shop:done:{item_id}")
    builder.button(text="🗑 Удалить", callback_data=f"shop:del:{item_id}")
    builder.adjust(2)
    return builder.as_markup()


# --- rituals -------------------------------------------------------------------

RITUAL_ACTION_PREFIX = "rit"


def rituals_menu_keyboard(already_added: Iterable[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    added = set(already_added)
    presets = (
        (
            "sunrise_focus",
            "Утренний фокус",
            "Дыхание 4×4×4 → журнал благодарностей (3 пункта) → первый шаг к цели",
            "20 минут, заряд энергии и ясность",
        ),
        (
            "midday_reset",
            "Полуденный ресет",
            "10 глубоких вдохов → проверка MIT → короткая запись итога",
            "5 минут, помогает перезагрузиться",
        ),
        (
            "evening_anchor",
            "Вечерний якорь",
            "Тёплая музыка → 3 благодарности → визуализация успеха",
            "10 минут, снижает стресс и улучшает сон",
        ),
    )
    for preset_id, title, _, summary in presets:
        mark = "✅" if preset_id in added else "➕"
        builder.button(
            text=f"{mark} {title}",
            callback_data=f"{RITUAL_ACTION_PREFIX}:preset:{preset_id}",
        )
        builder.button(text=summary, callback_data="rit:ignore")
        builder.adjust(1, 1)
    return builder.as_markup()


def ritual_schedule_keyboard(preset_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, day in (("Сегодня", "today"), ("Завтра", "tomorrow")):
        builder.button(
            text=label,
            callback_data=f"{RITUAL_ACTION_PREFIX}:schedule:{preset_id}:{day}",
        )
    builder.adjust(2)
    return builder.as_markup()


# --- daily plan ----------------------------------------------------------------


def daily_plan_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить пункт")
    builder.button(text="📋 Показать план")
    builder.button(text="✅ Отметить выполнено")
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def daily_plan_items_keyboard(items: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item_id, title in items:
        builder.button(text=f"✅ {title}", callback_data=f"plan:done:{item_id}")
    if not items:
        builder.button(text="Нет активных пунктов", callback_data="plan:ignore")
    builder.adjust(1)
    return builder.as_markup()


# --- notes ---------------------------------------------------------------------


def notes_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="🗒 Заметка")
    builder.button(text="📋 Мои заметки")
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def notes_list_keyboard(notes: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not notes:
        builder.button(text="Нет заметок", callback_data="note:ignore")
        builder.adjust(1)
        return builder.as_markup()
    for note_id, text in notes:
        builder.button(text=f"🗑 {text}", callback_data=f"note:del:{note_id}")
    builder.adjust(1)
    return builder.as_markup()


# --- daily review --------------------------------------------------------------


def review_prompt_keyboard(date_label: str, date_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Заполнить за {date_label}", callback_data=f"review:start:{date_code}"
    )
    builder.button(text="Пропустить", callback_data=f"review:skip:{date_code}")
    builder.adjust(1)
    builder.adjust(1)
    return builder.as_markup()


def review_mit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data="review:mit:yes")
    builder.button(text="Частично", callback_data="review:mit:partial")
    builder.button(text="Нет", callback_data="review:mit:no")
    builder.adjust(3)
    return builder.as_markup()


def review_mood_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for score in range(1, 6):
        builder.button(text=str(score), callback_data=f"review:mood:{score}")
    builder.adjust(5)
    return builder.as_markup()


def review_confirm_keyboard(date_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сохранить", callback_data=f"review:save:{date_code}")
    builder.button(text="Пропустить", callback_data=f"review:cancel:{date_code}")
    builder.adjust(2)
    return builder.as_markup()


__all__ = [
    "ALERT_DEFAULT_SELECTION",
    "ALERT_OPTIONS",
    "CalendarMonth",
    "alerts_keyboard",
    "cancel_keyboard",
    "calendar_keyboard",
    "daily_plan_items_keyboard",
    "daily_plan_menu_keyboard",
    "hours_keyboard",
    "main_menu_keyboard",
    "minutes_keyboard",
    "notes_list_keyboard",
    "notes_menu_keyboard",
    "reminder_actions_keyboard",
    "reminder_date_choice_keyboard",
    "reminders_menu_keyboard",
    "review_confirm_keyboard",
    "review_mit_keyboard",
    "review_mood_keyboard",
    "review_prompt_keyboard",
    "ritual_schedule_keyboard",
    "rituals_menu_keyboard",
    "shopping_item_actions_keyboard",
    "shopping_menu_keyboard",
    "simple_back_keyboard",
    "task_item_actions_keyboard",
    "tasks_menu_keyboard",
]
