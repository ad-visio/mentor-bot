from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Set

from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

# -------- главная
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.button(text="⏰ Напоминания")
    b.button(text="✅ Задачи")
    b.button(text="🔁 Ритуалы")
    b.button(text="🛒 Список покупок")
    b.button(text="ℹ️ Помощь")
    b.button(text="🏠 На главную")
    b.adjust(2, 2, 2)
    return b.as_markup(resize_keyboard=True)

def simple_back_keyboard() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.button(text="⬅️ Назад")
    b.button(text="🏠 На главную")
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)

# -------- напоминания
def reminders_menu_keyboard() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.button(text="➕ Создать")
    b.button(text="📅 На сегодня")
    b.button(text="📆 На завтра")
    b.button(text="📋 Все")
    b.button(text="📦 Архив")
    b.button(text="⬅️ Назад")
    b.button(text="🏠 На главную")
    b.adjust(2, 2, 2, 1)
    return b.as_markup(resize_keyboard=True)

def reminder_date_choice_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="date:today")
    kb.button(text="Завтра", callback_data="date:tomorrow")
    kb.button(text="📅 На дату…", callback_data="date:calendar")
    kb.adjust(3)
    return kb.as_markup()

def hours_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for h in range(0, 24):
        kb.button(text=f"{h:02d}", callback_data=f"hour:{h}")
    kb.adjust(6, 6, 6, 6)
    return kb.as_markup()

# добавил 10/20/40/50
MINUTES = [0, 5, 10, 15, 20, 30, 40, 45, 50]

def minutes_keyboard() -> InlineKeyboardMarkup:
    # добавил 10, 20, 40, 50
    minutes = [0, 10, 15, 20, 30, 40, 45, 50]
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for m in minutes:
        row.append(InlineKeyboardButton(text=f"{m:02d}", callback_data=f"minute:{m}"))
        if len(row) == 4:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    return builder.as_markup()

# чекбоксы уведомлений
ALERT_OPTIONS = [
    ("За 24 ч", "1440"),
    ("За 3 ч", "180"),
    ("За 1 ч", "60"),
    ("За 30 мин", "30"),
    ("За 15 мин", "15"),
    ("В момент", "0"),
]
ALERT_DEFAULT_SELECTION = {"15", "0"}

def alerts_keyboard(selected: Iterable[str] | Set[str]) -> InlineKeyboardMarkup:
    selected = set(selected)
    kb = InlineKeyboardBuilder()
    for label, value in ALERT_OPTIONS:
        mark = "✅ " if value in selected else "▫️ "
        kb.button(text=f"{mark}{label}", callback_data=f"alert:{value}")
    kb.button(text="Готово", callback_data="alert:done")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()

# У напоминаний оставляем ТОЛЬКО «Удалить»
def reminder_actions_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Удалить", callback_data=f"rem:delete:{reminder_id}")
    builder.adjust(1)
    return builder.as_markup()

# -------- календарь
@dataclass(slots=True)
class CalendarMonth:
    year: int
    month: int

def calendar_keyboard(month: CalendarMonth) -> InlineKeyboardMarkup:
    import calendar
    kb = InlineKeyboardBuilder()
    # заголовок
    kb.button(text=f"{calendar.month_name[month.month]} {month.year}", callback_data="cal:ignore")
    kb.adjust(1)

    # дни недели
    for d in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]:
        kb.button(text=d, callback_data="cal:ignore")
    kb.adjust(7)

    # сетка дней
    month_cal = calendar.Calendar(firstweekday=0).monthdayscalendar(month.year, month.month)
    for week in month_cal:
        for day in week:
            if day == 0:
                kb.button(text=" ", callback_data="cal:ignore")
            else:
                kb.button(text=str(day), callback_data=f"cal:select:{month.year}:{month.month}:{day}")
        kb.adjust(7)

    # переключатели
    kb.button(text="«", callback_data="cal:prev")
    kb.button(text="»", callback_data="cal:next")
    kb.adjust(2)
    return kb.as_markup()

# -------- задачи
def tasks_menu_keyboard() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.button(text="➕ Создать задачу")
    b.button(text="📋 Список задач")
    b.button(text="📦 Архив задач")
    b.button(text="⬅️ Назад")
    b.button(text="🏠 На главную")
    b.adjust(2, 2, 1)
    return b.as_markup(resize_keyboard=True)

def task_item_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово (в архив)", callback_data=f"task:done:{task_id}")
    kb.button(text="🗑 Удалить", callback_data=f"task:del:{task_id}")
    kb.adjust(2)
    return kb.as_markup()

# -------- покупки
def shopping_menu_keyboard() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.button(text="➕ Добавить позицию")
    b.button(text="📋 Список покупок")
    b.button(text="📦 Архив покупок")
    b.button(text="⬅️ Назад")
    b.button(text="🏠 На главную")
    b.adjust(2, 2, 1)
    return b.as_markup(resize_keyboard=True)

def shopping_item_actions_keyboard(item_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="☑ Куплено (в архив)", callback_data=f"shop:done:{item_id}")
    kb.button(text="🗑 Удалить", callback_data=f"shop:del:{item_id}")
    kb.adjust(2)
    return kb.as_markup()

# -------- ритуалы
def rituals_menu_keyboard() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.button(text="📖 Справка по ритуалам")
    b.button(text="📒 Мои ритуалы")
    b.button(text="➕ Добавить свой ритуал")
    b.button(text="⬅️ Назад")
    b.button(text="🏠 На главную")
    b.adjust(2, 2, 1)
    return b.as_markup(resize_keyboard=True)
