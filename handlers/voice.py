"""События голосовых каналов."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from services import voice_service
from utils.logging_setup import error_logger

if TYPE_CHECKING:
    from bot import TaskBot


def setup(bot: TaskBot) -> None:
    @bot.event
    async def on_voice_state_update(
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        try:
            await voice_service.handle_voice_state_update(member, before, after)
        except Exception as exc:
            error_logger.error(
                f"voice_state_update error: {exc}",
                exc_info=True,
            )
