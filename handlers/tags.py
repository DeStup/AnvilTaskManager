"""Slash-команда /tag — справочник тегов."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

from services import tag_service

if TYPE_CHECKING:
    from bot import TaskBot


def setup(bot: TaskBot) -> None:
    @bot.tree.command(
        name="tag",
        description="Справка по тегу (эфемерно или публично с пингом)",
    )
    @app_commands.describe(
        tag="Тег из справочника",
        user="Кому показать публично (если указать — сообщение увидят все)",
    )
    async def tag_command(
        interaction: discord.Interaction,
        tag: str,
        user: Optional[discord.Member] = None,
    ) -> None:
        found = tag_service.find_tag(tag)
        if not found:
            await interaction.response.send_message(
                f"❌ Тег `{tag}` не найден. Проверьте список в `data/tags.json`.",
                ephemeral=True,
            )
            return

        embed = tag_service.build_tag_embed(found)

        if user is None:
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.send_message(
            content=user.mention,
            embed=embed,
            ephemeral=False,
        )

    @tag_command.autocomplete("tag")
    async def tag_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return tag_service.autocomplete_choices(current)
