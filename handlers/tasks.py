"""Slash-команды задач."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from handlers.views.menu import TaskMenuView
from handlers.views.modals import TaskDescriptionModal
from services import task_service
from utils.permissions import has_permission

if TYPE_CHECKING:
    from bot import TaskBot


def setup(bot: TaskBot) -> None:
    @bot.tree.command(name="menu", description="Показать меню")
    async def menu(interaction: discord.Interaction) -> None:
        if not has_permission(interaction):
            await interaction.response.send_message(
                "❌ Меню для администраторов.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="📋 Управление задачами",
            description="Используйте кнопки:",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Доступные действия:",
            value=(
                "**➕ Добавить** — /add\n"
                "**📋 Список** — /list\n"
                "**🗑️ Удалить** — в меню"
            ),
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=TaskMenuView(interaction.user.id),
            ephemeral=True,
        )

    @bot.tree.command(name="add", description="Добавить задачу")
    async def add(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TaskDescriptionModal())

    @bot.tree.command(name="list", description="Список задач")
    async def task_list(interaction: discord.Interaction) -> None:
        await task_service.show_task_list(interaction)

    @bot.tree.command(name="ping", description="Пинг")
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🏓 Pong!", ephemeral=True)
