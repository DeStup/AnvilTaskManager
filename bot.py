"""Discord-клиент бота."""

from __future__ import annotations

import discord
from discord import app_commands

import config
from handlers.views.persistent import DYNAMIC_TASK_ITEMS


class TaskBot(discord.Client):
    """Клиент со slash CommandTree и DynamicItem для кнопок задач."""

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        from handlers import setup as setup_handlers

        setup_handlers(self)
        self.add_dynamic_items(*DYNAMIC_TASK_ITEMS)

        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
