"""События жизненного цикла бота."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.logging_setup import system_logger

if TYPE_CHECKING:
    from bot import TaskBot


def setup(bot: TaskBot) -> None:
    @bot.event
    async def on_ready() -> None:
        print(f"Бот {bot.user} запущен!")
        system_logger.info(f"Bot {bot.user} started!")
