"""Конфигурация бота и константы задач."""

from __future__ import annotations

import os
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "tasks.db"
TAGS_PATH = DATA_DIR / "tags.json"

TOKEN: str | None = os.getenv("DISCORD_TOKEN")
GUILD_ID: int = int(os.getenv("GUILD", "0"))

ALLOWED_USERS: frozenset[int] = frozenset(
    int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()
)

LOG_CHANNEL_ID: int = int(os.getenv("LOG_CHANNEL_ID", "0"))
TASKS_CHANNEL_ID: int = int(os.getenv("TASKS_CHANNEL_ID", "0"))

LOG_MAX_BYTES: int = 10 * 1024 * 1024
LOG_BACKUP_COUNT: int = 5

TASK_ID_LENGTH: int = 8
TASK_ID_MAX_ATTEMPTS: int = 5
TASK_DESCRIPTION_MAX: int = 500
LIST_PAGE_SIZE: int = 10
SELECT_MAX_OPTIONS: int = 25

# Очистка сообщений Discord: параллелизм и пауза между DELETE
CLEAR_DELETE_CONCURRENCY: int = 3
CLEAR_DELETE_DELAY_SEC: float = 0.35

# Голосовой учёт
VOICE_SESSION_RETENTION_DAYS: int = 14
VOICE_FLUSH_INTERVAL_SEC: float = 60.0
VOICE_CLEANUP_INTERVAL_SEC: float = 3600.0

# Статусы задач
STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES: tuple[str, ...] = (
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
    STATUS_PENDING_APPROVAL,
)

TASK_STATUSES: dict[str, dict] = {
    STATUS_OPEN: {"name": "📋 Открыта", "color": discord.Color.blue()},
    STATUS_IN_PROGRESS: {"name": "⚙️ В работе", "color": discord.Color.gold()},
    STATUS_PENDING_APPROVAL: {
        "name": "⏳ Ожидает подтверждения",
        "color": discord.Color.purple(),
    },
    STATUS_COMPLETED: {"name": "✅ Завершена", "color": discord.Color.green()},
    STATUS_CANCELLED: {"name": "❌ Отменена", "color": discord.Color.red()},
}

STATUS_EMOJI: dict[str, str] = {
    STATUS_OPEN: "📋",
    STATUS_IN_PROGRESS: "⚙️",
    STATUS_PENDING_APPROVAL: "⏳",
    STATUS_COMPLETED: "✅",
}

STATUS_NAME: dict[str, str] = {
    STATUS_OPEN: "Открыта",
    STATUS_IN_PROGRESS: "В работе",
    STATUS_PENDING_APPROVAL: "Ожидает подтверждения",
    STATUS_COMPLETED: "Завершена",
}

STATUS_COLOR: dict[str, discord.Color] = {
    STATUS_OPEN: discord.Color.blue(),
    STATUS_IN_PROGRESS: discord.Color.gold(),
    STATUS_PENDING_APPROVAL: discord.Color.purple(),
    STATUS_COMPLETED: discord.Color.green(),
}

CLEAR_TYPES: dict[str, dict[str, str]] = {
    "stats": {
        "name": "Очистить статистику",
        "emoji": "📊",
        "description": "Удалить счётчики участников (создано / закрыто / выполнено)",
    },
    "tasks": {
        "name": "Очистить активные задачи",
        "emoji": "📋",
        "description": "Удалить все открытые и в работе задачи",
    },
    "archive": {
        "name": "Очистить архив",
        "emoji": "📦",
        "description": "Удалить все завершенные задачи",
    },
}
