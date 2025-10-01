from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# --- main menus ----------------------------------------------------------------

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="⏰ Напоминания")
    builder.button(text="✅ Задачи")
    builder.button(text="🔁 Ритуалы")
    builder.button(text="🛒 Список покупок")
    builder.button(text="ℹ️ Помощь")
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def simple_back_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2)
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
    builder.button(text="📅 На дату…", callback_data="date:calendar")
    builder.adjust(3)
    return builder.as_markup()


def hours_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for hour in range(24):
        builder.button(text=f"{hour:02d}", callback_data=f"hour:{hour}")
    builder.adjust(6, 6, 6, 6)
    return builder.as_markup()


MINUTES = (0, 5, 10, 15, 20, 30, 40, 45, 50)


def minutes_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minute in MINUTES:
        builder.button(text=f"{minute:02d}", callback_data=f"minute:{minute}")
    builder.adjust(4, 4, 1)
    return builder.as_markup()


def alerts_keyboard(selected: Iterable[str]) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    builder = InlineKeyboardBuilder()
    for label, value in ALERT_OPTIONS:
        mark = "✅ " if value in selected_set else "▫️ "
        builder.button(text=f"{mark}{label}", callback_data=f"alert:{value}")
    builder.button(text="Готово", callback_data="alert:done")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def reminder_actions_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Удалить", callback_data=f"rem:delete:{reminder_id}")
    return builder.as_markup()


@dataclass(slots=True)
class CalendarMonth:
    year: int
    month: int


def calendar_keyboard(month: CalendarMonth) -> InlineKeyboardMarkup:
    import calendar

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"{calendar.month_name[month.month]} {month.year}",
        callback_data="cal:ignore",
    )
    builder.adjust(1)

    for day_name in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"):
        builder.button(text=day_name, callback_data="cal:ignore")
    builder.adjust(7)

    calendar_iter = calendar.Calendar(firstweekday=0)
    for week in calendar_iter.monthdayscalendar(month.year, month.month):
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
    builder.button(text="📋 Список задач")
    builder.button(text="📦 Архив задач")
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2, 2, 1)
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
    builder.button(text="📋 Список покупок")
    builder.button(text="📦 Архив покупок")
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

def rituals_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить ритуал")
    builder.button(text="🧩 Пресеты")
    builder.button(text="📋 Мои ритуалы")
    builder.button(text="⬅️ Назад")
    builder.button(text="🏠 На главную")
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def rituals_list_item_keyboard(ritual_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить", callback_data=f"rit:del:{ritual_id}")
    builder.adjust(1)
    return builder.as_markup()


__all__ = [
    "ALERT_DEFAULT_SELECTION",
    "ALERT_OPTIONS",
    "CalendarMonth",
    "alerts_keyboard",
    "calendar_keyboard",
    "hours_keyboard",
    "main_menu_keyboard",
    "minutes_keyboard",
    "reminder_actions_keyboard",
    "reminder_date_choice_keyboard",
    "reminders_menu_keyboard",
    "rituals_list_item_keyboard",
    "rituals_menu_keyboard",
    "shopping_item_actions_keyboard",
    "shopping_menu_keyboard",
    "simple_back_keyboard",
    "task_item_actions_keyboard",
    "tasks_menu_keyboard",
]
