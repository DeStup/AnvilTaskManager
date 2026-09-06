"""Логи действий в Discord-канал."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import discord

import config
from utils.formatting import link_from_task
from utils.logging_setup import error_logger


async def send_log_to_channel(
    bot: discord.Client,
    message: str,
    color: Optional[discord.Color] = None,
) -> None:
    if not config.LOG_CHANNEL_ID:
        return
    try:
        channel = bot.get_channel(config.LOG_CHANNEL_ID)
        if not channel:
            channel = await bot.fetch_channel(config.LOG_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                description=message,
                color=color or discord.Color.blue(),
                timestamp=datetime.now(),
            )
            embed.set_footer(text="Лог действий")
            await channel.send(embed=embed)
    except Exception as exc:
        error_logger.error(f"Error sending log to channel: {exc}")


def build_task_event_parts(
    title: str,
    *,
    task_id: str,
    author_id: str | None = None,
    executor_id: str | None = None,
    executor_mention: str | None = None,
    actor_label: str | None = None,
    actor_mention: str | None = None,
    extra_lines: list[str] | None = None,
    link: str | None = None,
) -> list[str]:
    """Единый формат логов по задачам."""
    parts = [title, f"**ID:** {task_id}"]
    if author_id:
        parts.append(f"**Автор:** <@{author_id}>")
    if executor_mention:
        parts.append(f"**Исполнитель:** {executor_mention}")
    elif executor_id:
        parts.append(f"**Исполнитель:** <@{executor_id}>")
    if actor_label and actor_mention:
        parts.append(f"**{actor_label}:** {actor_mention}")
    if extra_lines:
        parts.extend(extra_lines)
    if link:
        parts.append(f"**🔗 Ссылка:** [Перейти к задаче]({link})")
    return parts


async def send_task_event(
    bot: discord.Client,
    title: str,
    color: discord.Color,
    *,
    task: dict[str, Any] | None = None,
    task_id: str | None = None,
    author_id: str | None = None,
    executor_id: str | None = None,
    executor_mention: str | None = None,
    actor_label: str | None = None,
    actor_mention: str | None = None,
    extra_lines: list[str] | None = None,
    include_author: bool = True,
    include_link: bool = True,
) -> None:
    tid = task_id or (task["id"] if task else None)
    if not tid:
        return
    link = link_from_task(task) if (include_link and task) else None
    resolved_author = None
    if include_author:
        resolved_author = (
            author_id if author_id is not None else (task or {}).get("author_id")
        )
    parts = build_task_event_parts(
        title,
        task_id=tid,
        author_id=resolved_author,
        executor_id=executor_id,
        executor_mention=executor_mention,
        actor_label=actor_label,
        actor_mention=actor_mention,
        extra_lines=extra_lines,
        link=link,
    )
    await send_log_to_channel(bot, "\n".join(parts), color)


async def send_task_log(
    bot: discord.Client,
    task: dict[str, Any],
    action: str,
    user_mention: Optional[str],
    color: discord.Color,
    additional_info: Optional[str] = None,
) -> None:
    extra = [additional_info] if additional_info else None
    await send_task_event(
        bot,
        action,
        color,
        task=task,
        actor_label="Действие" if user_mention else None,
        actor_mention=user_mention,
        extra_lines=extra,
        executor_id=task.get("executor_id"),
    )


async def send_simple_log(
    bot: discord.Client,
    action: str,
    user_mention: str,
    color: discord.Color,
    additional_info: Optional[str] = None,
) -> None:
    parts = [action, f"**Действие:** {user_mention}"]
    if additional_info:
        parts.append(additional_info)
    await send_log_to_channel(bot, "\n".join(parts), color)
