"""Регистрация обработчиков команд и событий."""

from __future__ import annotations

from typing import TYPE_CHECKING

from handlers import events, tasks

if TYPE_CHECKING:
    from bot import TaskBot


def setup(bot: TaskBot) -> None:
    """Подключает все handlers к боту."""
    events.setup(bot)
    tasks.setup(bot)
