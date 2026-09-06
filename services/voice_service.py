"""Учёт времени в голосовых каналах (in-memory + фоновый flush)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime

import discord

import config
from services import database as db
from utils.logging_setup import error_logger, system_logger


@dataclass
class _ActiveSession:
    user_id: str
    user_name: str
    channel_id: str
    channel_name: str
    started_at: datetime
    # monotonic: старт текущего «слышащего» сегмента; None = пауза (self_deaf)
    segment_mono: float | None
    counted_seconds: int = 0
    credited_seconds: int = 0  # уже учтено в voice_totals


@dataclass
class _PendingClose:
    user_id: str
    user_name: str
    channel_id: str
    channel_name: str
    started_at: str
    ended_at: str
    duration_seconds: int
    uncredited_seconds: int


_lock = asyncio.Lock()
_active: dict[str, _ActiveSession] = {}
_pending_closes: list[_PendingClose] = []
_tasks_started = False


def _is_counting(state: discord.VoiceState | None) -> bool:
    """В канале и без self-deaf. Отключение микрофона (mute) не влияет."""
    if state is None or state.channel is None:
        return False
    return not bool(state.self_deaf)


def _accrue(session: _ActiveSession, now_mono: float) -> None:
    if session.segment_mono is None:
        return
    delta = int(now_mono - session.segment_mono)
    if delta > 0:
        session.counted_seconds += delta
    session.segment_mono = now_mono


def _peek_credit(session: _ActiveSession) -> int:
    return max(0, session.counted_seconds - session.credited_seconds)


def _close_session(
    session: _ActiveSession,
    *,
    user_name: str,
    ended_at: datetime,
    now_mono: float,
) -> None:
    _accrue(session, now_mono)
    session.segment_mono = None
    uncredited = _peek_credit(session)
    # credited обновится после успешного flush закрытой сессии
    session.credited_seconds = session.counted_seconds
    _pending_closes.append(
        _PendingClose(
            user_id=session.user_id,
            user_name=user_name,
            channel_id=session.channel_id,
            channel_name=session.channel_name,
            started_at=session.started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_seconds=session.counted_seconds,
            uncredited_seconds=uncredited,
        )
    )


def _start_session(
    *,
    user_id: str,
    user_name: str,
    channel: discord.abc.VocalGuildChannel,
    state: discord.VoiceState,
    now: datetime,
    now_mono: float,
) -> None:
    counting = _is_counting(state)
    _active[user_id] = _ActiveSession(
        user_id=user_id,
        user_name=user_name,
        channel_id=str(channel.id),
        channel_name=channel.name,
        started_at=now,
        segment_mono=now_mono if counting else None,
    )


async def handle_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member.bot:
        return
    if config.GUILD_ID and member.guild.id != config.GUILD_ID:
        return

    user_id = str(member.id)
    user_name = member.display_name
    before_ch = before.channel
    after_ch = after.channel
    now = datetime.now()
    now_mono = time.monotonic()

    async with _lock:
        left_or_switched = before_ch is not None and (
            after_ch is None or before_ch.id != after_ch.id
        )
        if left_or_switched and user_id in _active:
            _close_session(
                _active.pop(user_id),
                user_name=user_name,
                ended_at=now,
                now_mono=now_mono,
            )

        joined_or_switched = after_ch is not None and (
            before_ch is None or before_ch.id != after_ch.id
        )
        if joined_or_switched:
            _start_session(
                user_id=user_id,
                user_name=user_name,
                channel=after_ch,
                state=after,
                now=now,
                now_mono=now_mono,
            )
            return

        if after_ch is None:
            return

        session = _active.get(user_id)
        if session is None:
            _start_session(
                user_id=user_id,
                user_name=user_name,
                channel=after_ch,
                state=after,
                now=now,
                now_mono=now_mono,
            )
            return

        session.user_name = user_name
        session.channel_name = after_ch.name
        was_counting = session.segment_mono is not None
        should_count = _is_counting(after)

        if was_counting and not should_count:
            _accrue(session, now_mono)
            session.segment_mono = None
        elif not was_counting and should_count:
            session.segment_mono = now_mono


def _collect_flush_payload() -> tuple[
    list[tuple[str, str, int]],
    list[dict],
    list[tuple[_ActiveSession, int]],
    list[_PendingClose],
]:
    """Собирает payload; credited для active фиксируется только после успешного DB."""
    now_mono = time.monotonic()
    totals: list[tuple[str, str, int]] = []
    sessions: list[dict] = []
    active_credits: list[tuple[_ActiveSession, int]] = []

    for session in _active.values():
        _accrue(session, now_mono)
        credit = _peek_credit(session)
        if credit > 0:
            totals.append((session.user_id, session.user_name, credit))
            active_credits.append((session, credit))

    closes = list(_pending_closes)
    _pending_closes.clear()
    for closed in closes:
        if closed.uncredited_seconds > 0:
            totals.append(
                (
                    closed.user_id,
                    closed.user_name,
                    closed.uncredited_seconds,
                )
            )
        sessions.append(
            {
                "user_id": closed.user_id,
                "user_name": closed.user_name,
                "channel_id": closed.channel_id,
                "channel_name": closed.channel_name,
                "started_at": closed.started_at,
                "ended_at": closed.ended_at,
                "duration_seconds": closed.duration_seconds,
            }
        )

    return totals, sessions, active_credits, closes


async def flush_to_db() -> None:
    async with _lock:
        totals, sessions, active_credits, closes = _collect_flush_payload()
    if not totals and not sessions:
        return
    try:
        await db.aapply_voice_flush(totals, sessions)
    except Exception as exc:
        error_logger.error(f"Voice flush failed: {exc}", exc_info=True)
        async with _lock:
            _pending_closes.extend(closes)
        return

    async with _lock:
        for session, credit in active_credits:
            session.credited_seconds += credit


async def restore_from_guild(guild: discord.Guild) -> None:
    """После on_ready: подхватить кто уже в войсе."""
    now = datetime.now()
    now_mono = time.monotonic()
    channels = list(guild.voice_channels) + list(guild.stage_channels)
    async with _lock:
        for channel in channels:
            for member in channel.members:
                if member.bot:
                    continue
                user_id = str(member.id)
                if user_id in _active:
                    continue
                state = member.voice
                if state is None:
                    continue
                _start_session(
                    user_id=user_id,
                    user_name=member.display_name,
                    channel=channel,
                    state=state,
                    now=now,
                    now_mono=now_mono,
                )
    system_logger.info(
        f"Voice tracking restored: {len(_active)} active session(s)"
    )


async def _flush_loop() -> None:
    while True:
        await asyncio.sleep(config.VOICE_FLUSH_INTERVAL_SEC)
        await flush_to_db()


async def _cleanup_loop() -> None:
    while True:
        try:
            deleted = await db.acleanup_old_voice_sessions(
                config.VOICE_SESSION_RETENTION_DAYS
            )
            if deleted:
                system_logger.info(
                    f"Voice sessions cleanup: deleted {deleted} row(s)"
                )
        except Exception as exc:
            error_logger.error(f"Voice cleanup failed: {exc}", exc_info=True)
        await asyncio.sleep(config.VOICE_CLEANUP_INTERVAL_SEC)


def start_background_tasks(bot: discord.Client) -> None:
    global _tasks_started
    if _tasks_started:
        return
    _tasks_started = True
    bot.loop.create_task(_flush_loop())
    bot.loop.create_task(_cleanup_loop())
    system_logger.info("Voice flush/cleanup tasks started")
