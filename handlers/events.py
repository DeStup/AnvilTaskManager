"""События жизненного цикла бота."""

from __future__ import annotations

from typing import TYPE_CHECKING

import config
from services import voice_service
from utils.logging_setup import error_logger, system_logger

if TYPE_CHECKING:
    from bot import TaskBot


def setup(bot: TaskBot) -> None:
    @bot.event
    async def on_ready() -> None:
        print(f"Бот {bot.user} запущен!")
        system_logger.info(f"Bot {bot.user} started!")

        voice_service.start_background_tasks(bot)

        guild = None
        if config.GUILD_ID:
            guild = bot.get_guild(config.GUILD_ID)
        if guild is None and bot.guilds:
            guild = bot.guilds[0]
        if guild is not None:
            try:
                await voice_service.restore_from_guild(guild)
            except Exception as exc:
                error_logger.error(
                    f"Voice restore failed: {exc}",
                    exc_info=True,
                )
