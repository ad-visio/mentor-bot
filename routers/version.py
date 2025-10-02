from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from meta import get_version_line

version_router = Router()


@version_router.message(Command("version"))
async def handle_version(message: Message) -> None:
    await message.answer(get_version_line())
