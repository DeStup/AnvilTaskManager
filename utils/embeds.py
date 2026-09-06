"""Сборка embed для задач."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import discord

import config
from utils.formatting import format_timestamp


def build_task_channel_embed(task: dict[str, Any]) -> discord.Embed:
    """Embed сообщения задачи в канале."""
    status = task["status"]
    embed = discord.Embed(
        description=f"```\n{task['description']}\n```",
        color=config.STATUS_COLOR.get(status, discord.Color.blue()),
        timestamp=datetime.now(),
    )
    embed.add_field(name="👤 Автор", value=f"<@{task['author_id']}>", inline=True)
    embed.add_field(
        name="📌 Статус",
        value=(
            f"{config.STATUS_EMOJI.get(status, '📋')} "
            f"{config.STATUS_NAME.get(status, status)}"
        ),
        inline=True,
    )
    if task.get("executor_id"):
        embed.add_field(
            name="⚙️ Исполнитель",
            value=f"<@{task['executor_id']}>",
            inline=True,
        )
    else:
        embed.add_field(name="⚙️ Исполнитель", value="❌ Не назначен", inline=True)
    embed.set_footer(text=f"ID: {task['id']}")
    return embed


def build_task_detail_embed(task: dict[str, Any]) -> discord.Embed:
    """Подробный embed задачи (для просмотра)."""
    status = config.TASK_STATUSES.get(
        task["status"],
        {"name": task["status"], "color": discord.Color.default()},
    )
    embed = discord.Embed(
        title=f"📋 Задача {task['id']}",
        color=status["color"],
    )
    embed.add_field(name="📝 Описание", value=task["description"], inline=False)
    embed.add_field(name="📌 Статус", value=status["name"], inline=True)
    embed.add_field(name="👤 Автор", value=f"<@{task['author_id']}>", inline=True)
    if task.get("executor_id"):
        embed.add_field(
            name="⚙️ Исполнитель",
            value=f"<@{task['executor_id']}>",
            inline=True,
        )
    embed.add_field(
        name="📅 Создана",
        value=format_timestamp(task.get("created_at"), "f"),
        inline=True,
    )
    if task.get("taken_at"):
        embed.add_field(
            name="⏰ Взята",
            value=format_timestamp(task["taken_at"], "f"),
            inline=True,
        )
    if task.get("completed_at"):
        embed.add_field(
            name="✅ Завершена",
            value=format_timestamp(task["completed_at"], "f"),
            inline=True,
        )
    if task.get("cancel_comment"):
        embed.add_field(
            name="💬 Комментарий",
            value=task["cancel_comment"],
            inline=False,
        )
    return embed
