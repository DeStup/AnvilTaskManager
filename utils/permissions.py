"""Проверки прав доступа."""

from __future__ import annotations

import discord

import config


def has_permission(interaction: discord.Interaction) -> bool:
    """Админ-меню, очистка, коррекция очков, подтверждение чужих задач."""
    user = interaction.user
    if user.id in config.ALLOWED_USERS:
        return True
    if isinstance(user, discord.Member):
        perms = user.guild_permissions
        return bool(perms.administrator or perms.manage_guild)
    return False
