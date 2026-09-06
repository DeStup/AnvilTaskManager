"""Форматирование и вспомогательные преобразования."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import discord

import config
from utils.logging_setup import error_logger


def get_user_info(interaction: discord.Interaction) -> str:
    return f"User: {interaction.user.name} (ID: {interaction.user.id})"


def format_timestamp(dt_str: str | None, style: str = "f") -> str:
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str)
        return f"<t:{int(dt.timestamp())}:{style}>"
    except Exception as exc:
        error_logger.error(f"Error formatting timestamp: {exc}")
        return dt_str[:16]


def row_to_dict(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """sqlite3.Row / Mapping → обычный dict."""
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def task_message_link(
    channel_id: str | None,
    message_id: str | None,
    guild_id: str | int | None = None,
) -> str | None:
    """Ссылка на сообщение задачи в гильдии (не @me)."""
    if not channel_id or not message_id:
        return None
    gid = guild_id or (config.GUILD_ID if config.GUILD_ID else None)
    if not gid:
        return None
    return f"https://discord.com/channels/{gid}/{channel_id}/{message_id}"


def link_from_task(task: Mapping[str, Any]) -> str | None:
    return task_message_link(
        task.get("channel_id"),
        task.get("message_id"),
        task.get("guild_id"),
    )


async def reply(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = True,
) -> None:
    """response.send или followup после defer."""
    kwargs: dict[str, Any] = {"ephemeral": ephemeral}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral)
