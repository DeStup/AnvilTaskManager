"""Бизнес-логика задач."""

from __future__ import annotations

import asyncio
from typing import Any

import discord

import config
from services import database as db
from services.channel_log import send_task_event, send_task_log
from utils.embeds import build_task_channel_embed, build_task_detail_embed
from utils.formatting import defer, get_user_info, link_from_task, reply
from utils.logging_setup import action_logger, error_logger
from utils.permissions import has_permission


async def _delete_task_message(
    bot: discord.Client,
    channel_id: str | None,
    message_id: str | None,
) -> None:
    if not channel_id or not message_id:
        return
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel:
            channel = await bot.fetch_channel(int(channel_id))
        message = await channel.fetch_message(int(message_id))
        await message.delete()
    except Exception as exc:
        error_logger.error(f"Error deleting task message: {exc}")


async def _delete_messages_batched(
    bot: discord.Client,
    tasks: list[dict[str, Any]],
) -> None:
    """Параллельное удаление с лимитом concurrency и паузой."""
    sem = asyncio.Semaphore(config.CLEAR_DELETE_CONCURRENCY)

    async def _one(task: dict[str, Any]) -> None:
        async with sem:
            await _delete_task_message(
                bot,
                task.get("channel_id"),
                task.get("message_id"),
            )
            await asyncio.sleep(config.CLEAR_DELETE_DELAY_SEC)

    await asyncio.gather(*(_one(t) for t in tasks))


async def _post_task_comment_thread(
    bot: discord.Client,
    task: dict[str, Any],
    *,
    comment: str,
    author: discord.abc.User,
    mention_user_id: str | None = None,
) -> None:
    """Создаёт ветку у сообщения задачи (если нужно) и пишет комментарий."""
    text = (comment or "").strip()
    if not text:
        return
    channel_id = task.get("channel_id")
    message_id = task.get("message_id")
    if not channel_id or not message_id:
        return
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel:
            channel = await bot.fetch_channel(int(channel_id))
        message = await channel.fetch_message(int(message_id))

        thread = message.thread
        if thread is None:
            thread_name = f"💬 {task['id']}"
            thread = await message.create_thread(
                name=thread_name[:100],
                auto_archive_duration=10080,
            )

        mention = f"<@{mention_user_id}> " if mention_user_id else ""
        await thread.send(f"{mention}**{author.display_name}:**\n{text}")
    except Exception as exc:
        error_logger.error(f"Error posting task comment thread: {exc}", exc_info=True)


async def update_task_message(
    interaction: discord.Interaction,
    task: dict[str, Any],
) -> None:
    from handlers.views.persistent import PersistentTaskView

    if not task.get("channel_id") or not task.get("message_id"):
        return

    embed = build_task_channel_embed(task)
    try:
        channel = interaction.client.get_channel(int(task["channel_id"]))
        if not channel:
            channel = await interaction.client.fetch_channel(int(task["channel_id"]))
        message = await channel.fetch_message(int(task["message_id"]))
        await message.edit(
            embed=embed,
            view=PersistentTaskView(task["id"], status=task["status"]),
        )
    except Exception as exc:
        error_logger.error(f"Error updating message: {exc}")


async def create_task(interaction: discord.Interaction, description: str) -> str:
    """Создаёт задачу и публикует сообщение. Возвращает task_id."""
    from handlers.views.persistent import PersistentTaskView

    await defer(interaction, ephemeral=True)

    task = await db.acreate_task_row(
        description=description,
        author_id=str(interaction.user.id),
        author_name=interaction.user.name,
    )
    task_id = task["id"]
    await db.aupdate_participant(
        str(interaction.user.id),
        interaction.user.name,
        created_delta=1,
    )

    embed = build_task_channel_embed(task)
    view = PersistentTaskView(task_id, status=config.STATUS_OPEN)

    if config.TASKS_CHANNEL_ID:
        target = interaction.client.get_channel(config.TASKS_CHANNEL_ID)
        if not target:
            target = await interaction.client.fetch_channel(config.TASKS_CHANNEL_ID)
        message = await target.send(embed=embed, view=view)
    else:
        message = await interaction.channel.send(embed=embed, view=view)

    guild_id = str(message.guild.id) if message.guild else (
        str(config.GUILD_ID) if config.GUILD_ID else None
    )
    await db.aset_task_message(
        task_id,
        channel_id=str(message.channel.id),
        message_id=str(message.id),
        guild_id=guild_id,
    )
    task["channel_id"] = str(message.channel.id)
    task["message_id"] = str(message.id)
    task["guild_id"] = guild_id

    action_logger.info(f"{get_user_info(interaction)} created task {task_id}")
    await send_task_log(
        interaction.client,
        task,
        "📋 **Создана задача**",
        None,
        discord.Color.green(),
    )
    return task_id


async def accept_task_action(interaction: discord.Interaction, task_id: str) -> None:
    await defer(interaction, ephemeral=True)

    code, updated = await db.atry_accept_task(
        task_id,
        str(interaction.user.id),
        interaction.user.name,
    )
    if code == "own":
        await reply(interaction, "❌ Вы не можете принять свою задачу.")
        return
    if code != "ok" or not updated:
        await reply(interaction, "❌ Задача уже взята в работу.")
        return

    action_logger.info(f"{get_user_info(interaction)} accepted task {task_id}")
    await send_task_event(
        interaction.client,
        "📥 **Задача принята**",
        discord.Color.gold(),
        task=updated,
        executor_mention=interaction.user.mention,
        include_author=False,
    )
    await update_task_message(interaction, updated)
    await reply(interaction, f"✅ Вы приняли задачу #{task_id}!")


async def complete_task_action(
    interaction: discord.Interaction,
    task_id: str,
    *,
    comment: str = "",
) -> None:
    await defer(interaction, ephemeral=True)

    code, updated = await db.atry_complete_task(task_id, str(interaction.user.id))
    if code != "ok" or not updated:
        await reply(interaction, "❌ Вы не можете завершить чужую задачу.")
        return

    action_logger.info(f"{get_user_info(interaction)} completed task {task_id}")
    await send_task_event(
        interaction.client,
        "✅ **Задача выполнена**",
        discord.Color.purple(),
        task=updated,
        executor_mention=interaction.user.mention,
        extra_lines=["⏳ Ожидает подтверждения от автора."],
        include_author=False,
    )
    await update_task_message(interaction, updated)
    await _post_task_comment_thread(
        interaction.client,
        updated,
        comment=comment,
        author=interaction.user,
    )
    await reply(
        interaction,
        f"✅ Задача #{task_id} выполнена! Ожидайте подтверждения.",
    )


async def abandon_task_action(interaction: discord.Interaction, task_id: str) -> None:
    await defer(interaction, ephemeral=True)

    code, updated = await db.atry_abandon_task(task_id, str(interaction.user.id))
    if code != "ok" or not updated:
        await reply(interaction, "❌ Вы не можете отказаться от чужой задачи.")
        return

    action_logger.info(f"{get_user_info(interaction)} abandoned task {task_id}")
    await send_task_event(
        interaction.client,
        "↩️ **Отказ от задачи**",
        discord.Color.orange(),
        task=updated,
        executor_mention=interaction.user.mention,
        include_author=False,
    )
    await update_task_message(interaction, updated)
    await reply(interaction, f"↩️ Вы отказались от задачи #{task_id}.")


async def confirm_task_action(interaction: discord.Interaction, task_id: str) -> None:
    await defer(interaction, ephemeral=True)

    task = await db.aget_task(task_id)
    if not task or task["status"] != config.STATUS_PENDING_APPROVAL:
        await reply(
            interaction,
            "❌ Задача не найдена или не ожидает подтверждения.",
        )
        return

    is_author = task["author_id"] == str(interaction.user.id)
    if not (is_author or has_permission(interaction)):
        await reply(
            interaction,
            "❌ Только автор или администратор могут подтвердить выполнение.",
        )
        return

    updated = await db.atry_confirm_task(task_id)
    if not updated:
        await reply(
            interaction,
            "❌ Задача не найдена или не ожидает подтверждения.",
        )
        return

    if updated.get("executor_id"):
        await db.aupdate_participant(
            updated["executor_id"],
            updated.get("executor_name") or "unknown",
            resolved_delta=1,
        )
    if updated.get("author_id"):
        await db.aupdate_participant(
            updated["author_id"],
            updated.get("author_name") or "unknown",
            closed_delta=1,
        )

    action_logger.info(f"{get_user_info(interaction)} confirmed task {task_id}")
    await send_task_event(
        interaction.client,
        "✨ **Задача подтверждена**",
        discord.Color.green(),
        task=task,
        task_id=task_id,
        author_id=updated.get("author_id"),
        executor_id=updated.get("executor_id"),
        include_link=False,
    )
    await _delete_task_message(
        interaction.client,
        task.get("channel_id"),
        task.get("message_id"),
    )
    await reply(
        interaction,
        f"✅ Задача #{task_id} успешно выполнена и подтверждена!",
    )


async def return_task_action(
    interaction: discord.Interaction,
    task_id: str,
    *,
    comment: str = "",
) -> None:
    await defer(interaction, ephemeral=True)

    task = await db.aget_task(task_id)
    if not task or task["status"] != config.STATUS_PENDING_APPROVAL:
        await reply(interaction, "❌ Задача не найдена.")
        return
    if task["author_id"] != str(interaction.user.id) and not has_permission(interaction):
        await reply(interaction, "❌ Только автор может вернуть задачу в работу.")
        return

    updated = await db.atry_return_task(task_id)
    if not updated:
        await reply(interaction, "❌ Задача не найдена.")
        return

    action_logger.info(f"{get_user_info(interaction)} returned task {task_id}")
    await send_task_event(
        interaction.client,
        "🔄 **Задача возвращена в работу**",
        discord.Color.orange(),
        task=updated,
    )

    await update_task_message(interaction, updated)
    await _post_task_comment_thread(
        interaction.client,
        updated,
        comment=comment,
        author=interaction.user,
        mention_user_id=updated.get("executor_id"),
    )

    await reply(interaction, f"🔄 Задача #{task_id} возвращена в работу.")


async def delete_task_action(interaction: discord.Interaction, task_id: str) -> None:
    await defer(interaction, ephemeral=True)

    task = await db.aget_task(task_id)
    if not task:
        await reply(interaction, "❌ Задача не найдена.")
        return

    is_author = task["author_id"] == str(interaction.user.id)
    if not (is_author or has_permission(interaction)):
        await reply(interaction, "❌ Вы не можете удалить чужую задачу.")
        return

    channel_id = task.get("channel_id")
    message_id = task.get("message_id")
    await db.adelete_task(task_id)
    await _delete_task_message(interaction.client, channel_id, message_id)

    action_logger.info(f"{get_user_info(interaction)} deleted task {task_id}")
    await send_task_event(
        interaction.client,
        "🗑️ **Задача удалена**",
        discord.Color.red(),
        task=task,
        executor_id=None,
        actor_label="Удалил",
        actor_mention=interaction.user.mention,
        include_link=False,
    )
    await reply(interaction, f"🗑️ Задача `{task_id}` успешно удалена!")


async def clear_data(
    interaction: discord.Interaction,
    clear_type: str,
) -> tuple[bool, str]:
    """Очистка статистики / активных / архива. Возвращает (ok, message)."""
    if clear_type == "stats":
        await db.aclear_participants()
        return True, "Статистика очищена!"

    if clear_type == "tasks":
        tasks = await db.aget_tasks_by_statuses(config.ACTIVE_STATUSES)
        await _delete_messages_batched(interaction.client, tasks)
        await db.adelete_tasks_by_statuses(config.ACTIVE_STATUSES)
        return True, f"Очищено {len(tasks)} активных задач!"

    if clear_type == "archive":
        tasks = await db.aget_tasks_by_statuses((config.STATUS_COMPLETED,))
        await _delete_messages_batched(interaction.client, tasks)
        await db.adelete_tasks_by_statuses((config.STATUS_COMPLETED,))
        return True, f"Очищено {len(tasks)} завершенных задач!"

    return False, "Неизвестный тип очистки."


async def show_task_detail(interaction: discord.Interaction, task_id: str) -> None:
    from handlers.views.select import TaskSelectView

    task = await db.aget_task(task_id)
    if not task:
        await reply(interaction, "❌ Задача не найдена.")
        return
    embed = build_task_detail_embed(task)
    view = TaskSelectView("view", interaction.user.id)
    await reply(interaction, embed=embed, view=view)


async def show_my_task_detail(interaction: discord.Interaction, task_id: str) -> None:
    task = await db.afetch_one(
        "SELECT * FROM tasks WHERE id = ? AND executor_id = ?",
        (task_id, str(interaction.user.id)),
    )
    if not task:
        await reply(interaction, "❌ Задача не найдена.")
        return
    await reply(interaction, embed=build_task_detail_embed(task))


async def show_task_list(interaction: discord.Interaction) -> None:
    from handlers.views.pagination import PaginationView

    tasks = await db.aget_active_tasks()
    if not tasks:
        await reply(
            interaction,
            embed=discord.Embed(
                title="📭 Список задач",
                description="Активных задач пока нет. /add чтобы добавить задачу",
                color=discord.Color.blue(),
            ),
        )
        return

    view = PaginationView(
        user_id=interaction.user.id,
        items=tasks,
        items_per_page=config.LIST_PAGE_SIZE,
        title="📋 Список задач",
        color=discord.Color.blue(),
    )
    page_items, start_num, end_num = view.page_slice()
    embed = view.create_embed(page_items, start_num, end_num)
    await reply(interaction, embed=embed, view=view)


async def show_archive(interaction: discord.Interaction) -> None:
    from handlers.views.pagination import PaginationView

    tasks = await db.aget_completed_tasks()
    if not tasks:
        await reply(
            interaction,
            embed=discord.Embed(
                title="📦 Архив задач",
                description="Завершенных задач пока нет.",
                color=discord.Color.blue(),
            ),
        )
        return

    view = PaginationView(
        user_id=interaction.user.id,
        items=tasks,
        items_per_page=config.LIST_PAGE_SIZE,
        title="📦 Архив завершенных задач",
        color=discord.Color.purple(),
    )
    page_items, start_num, end_num = view.page_slice()
    embed = view.create_embed(page_items, start_num, end_num)
    await reply(interaction, embed=embed, view=view)
