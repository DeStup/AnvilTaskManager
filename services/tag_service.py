"""Справочник тегов из JSON-файла."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord

import config
from utils.logging_setup import error_logger


@dataclass(frozen=True)
class Tag:
    name: str
    description: str


_cache_mtime: float | None = None
_cache_tags: list[Tag] = []


def _load_from_disk(path: Path) -> list[Tag]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        error_logger.error(f"Failed to load tags from {path}: {exc}")
        return []

    if not isinstance(raw, list):
        error_logger.error(f"tags.json must be a JSON array, got {type(raw).__name__}")
        return []

    tags: list[Tag] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            error_logger.error(f"tags.json[{i}]: expected object")
            continue
        name = str(item.get("name", "")).strip()
        description = str(item.get("description", "")).strip()
        if not name or not description:
            error_logger.error(f"tags.json[{i}]: name and description required")
            continue
        key = name.casefold()
        if key in seen:
            error_logger.error(f"tags.json[{i}]: duplicate name {name!r}")
            continue
        seen.add(key)
        tags.append(Tag(name=name, description=description))
    return tags


def load_tags(*, force: bool = False) -> list[Tag]:
    """Читает data/tags.json; кэш сбрасывается при изменении файла."""
    global _cache_mtime, _cache_tags
    path = config.TAGS_PATH
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None

    if not force and mtime is not None and mtime == _cache_mtime:
        return _cache_tags

    _cache_tags = _load_from_disk(path)
    _cache_mtime = mtime
    return _cache_tags


def find_tag(name: str) -> Optional[Tag]:
    needle = name.casefold().strip()
    for tag in load_tags():
        if tag.name.casefold() == needle:
            return tag
    return None


def autocomplete_choices(
    current: str,
    *,
    limit: int = 25,
) -> list[discord.app_commands.Choice[str]]:
    q = current.casefold().strip()
    tags = load_tags()
    if q:
        tags = [
            t
            for t in tags
            if q in t.name.casefold() or q in t.description.casefold()
        ]
    choices: list[discord.app_commands.Choice[str]] = []
    for tag in tags[:limit]:
        value = tag.name[:100]
        label = tag.name[:100]
        choices.append(discord.app_commands.Choice(name=label, value=value))
    return choices


def build_tag_embed(tag: Tag) -> discord.Embed:
    return discord.Embed(
        description=tag.description,
        color=discord.Color.from_str("#40E0D0"),
    )
