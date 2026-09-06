"""Работа с SQLite."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Generator, Iterable, Optional, TypeVar

import config
from utils.formatting import row_to_dict

Row = sqlite3.Row
T = TypeVar("T")


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Контекстный менеджер соединения с БД (commit/rollback, WAL)."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицы, миграции, индексы."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                author_id TEXT NOT NULL,
                author_name TEXT NOT NULL,
                executor_id TEXT,
                executor_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                taken_at TIMESTAMP,
                completed_at TIMESTAMP,
                cancel_comment TEXT,
                channel_id TEXT,
                message_id TEXT,
                guild_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS participants (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL,
                closed_tasks INTEGER DEFAULT 0,
                created_tasks INTEGER DEFAULT 0,
                resolved_tasks INTEGER DEFAULT 0,
                points INTEGER DEFAULT 0
            )
            """
        )

        task_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(tasks)")
        }
        if "guild_id" not in task_columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN guild_id TEXT")

        participant_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(participants)")
        }
        if "resolved_tasks" not in participant_columns:
            conn.execute(
                "ALTER TABLE participants "
                "ADD COLUMN resolved_tasks INTEGER DEFAULT 0"
            )
        if "points" not in participant_columns:
            conn.execute(
                "ALTER TABLE participants ADD COLUMN points INTEGER DEFAULT 0"
            )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_executor "
            "ON tasks (executor_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_participants_points "
            "ON participants (points DESC)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_totals (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL,
                total_seconds INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                channel_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_sessions_ended "
            "ON voice_sessions (ended_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_sessions_user "
            "ON voice_sessions (user_id)"
        )


def _run(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return func(*args, **kwargs)


async def to_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Запуск синхронной работы с БД вне event loop."""
    return await asyncio.to_thread(_run, func, *args, **kwargs)


def execute(query: str, params: tuple | list = ()) -> int:
    """Выполняет запрос, возвращает rowcount."""
    with get_connection() as conn:
        cur = conn.execute(query, params)
        return cur.rowcount


def fetch_one(query: str, params: tuple | list = ()) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()
        return row_to_dict(row)


def fetch_all(query: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def update_participant(
    user_id: str,
    user_name: str,
    *,
    closed_delta: int = 0,
    created_delta: int = 0,
    resolved_delta: int = 0,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO participants (
                user_id, user_name, closed_tasks, created_tasks,
                resolved_tasks, points
            )
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                user_name = excluded.user_name,
                closed_tasks = closed_tasks + ?,
                created_tasks = created_tasks + ?,
                resolved_tasks = resolved_tasks + ?
            """,
            (
                user_id,
                user_name,
                closed_delta,
                created_delta,
                resolved_delta,
                closed_delta,
                created_delta,
                resolved_delta,
            ),
        )


def get_task(task_id: str) -> Optional[dict[str, Any]]:
    return fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))


def create_task_row(
    *,
    description: str,
    author_id: str,
    author_name: str,
) -> dict[str, Any]:
    """INSERT с уникальным id (retry при коллизии)."""
    now = datetime.now().isoformat()
    last_error: Exception | None = None

    for _ in range(config.TASK_ID_MAX_ATTEMPTS):
        task_id = uuid.uuid4().hex[: config.TASK_ID_LENGTH]
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tasks (
                        id, description, status, author_id, author_name, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        description,
                        config.STATUS_OPEN,
                        author_id,
                        author_name,
                        now,
                    ),
                )
            return {
                "id": task_id,
                "description": description,
                "status": config.STATUS_OPEN,
                "author_id": author_id,
                "author_name": author_name,
                "executor_id": None,
                "executor_name": None,
                "created_at": now,
                "taken_at": None,
                "completed_at": None,
                "cancel_comment": None,
                "channel_id": None,
                "message_id": None,
                "guild_id": None,
            }
        except sqlite3.IntegrityError as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"Не удалось сгенерировать уникальный id задачи: {last_error}"
    )


def set_task_message(
    task_id: str,
    *,
    channel_id: str,
    message_id: str,
    guild_id: str | None,
) -> None:
    execute(
        """
        UPDATE tasks
        SET channel_id = ?, message_id = ?, guild_id = ?
        WHERE id = ?
        """,
        (channel_id, message_id, guild_id, task_id),
    )


def try_accept_task(
    task_id: str,
    executor_id: str,
    executor_name: str,
) -> tuple[str, Optional[dict[str, Any]]]:
    """
    Атомарный accept.
    Возвращает (код, задача): ok | own | taken | missing.
    """
    taken_at = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE tasks
            SET status = ?, executor_id = ?, executor_name = ?, taken_at = ?
            WHERE id = ? AND status = ? AND author_id != ?
            RETURNING *
            """,
            (
                config.STATUS_IN_PROGRESS,
                executor_id,
                executor_name,
                taken_at,
                task_id,
                config.STATUS_OPEN,
                executor_id,
            ),
        )
        updated = cur.fetchone()
        if updated:
            return "ok", row_to_dict(updated)

        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return "missing", None
        task = row_to_dict(row)
        assert task is not None
        if task["author_id"] == executor_id and task["status"] == config.STATUS_OPEN:
            return "own", task
        return "taken", task


def try_complete_task(
    task_id: str,
    executor_id: str,
) -> tuple[str, Optional[dict[str, Any]]]:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE tasks
            SET status = ?
            WHERE id = ? AND executor_id = ? AND status = ?
            RETURNING *
            """,
            (
                config.STATUS_PENDING_APPROVAL,
                task_id,
                executor_id,
                config.STATUS_IN_PROGRESS,
            ),
        )
        updated = cur.fetchone()
        if updated:
            return "ok", row_to_dict(updated)
        return "denied", None


def try_abandon_task(
    task_id: str,
    executor_id: str,
) -> tuple[str, Optional[dict[str, Any]]]:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE tasks
            SET status = ?, executor_id = NULL, executor_name = NULL,
                taken_at = NULL, cancel_comment = NULL
            WHERE id = ? AND executor_id = ? AND status = ?
            RETURNING *
            """,
            (
                config.STATUS_OPEN,
                task_id,
                executor_id,
                config.STATUS_IN_PROGRESS,
            ),
        )
        updated = cur.fetchone()
        if updated:
            return "ok", row_to_dict(updated)
        return "denied", None


def try_confirm_task(task_id: str) -> Optional[dict[str, Any]]:
    completed_at = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE tasks
            SET status = ?, completed_at = ?
            WHERE id = ? AND status = ?
            RETURNING *
            """,
            (
                config.STATUS_COMPLETED,
                completed_at,
                task_id,
                config.STATUS_PENDING_APPROVAL,
            ),
        )
        row = cur.fetchone()
        return row_to_dict(row)


def try_return_task(task_id: str) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE tasks
            SET status = ?, completed_at = NULL
            WHERE id = ? AND status = ?
            RETURNING *
            """,
            (
                config.STATUS_IN_PROGRESS,
                task_id,
                config.STATUS_PENDING_APPROVAL,
            ),
        )
        row = cur.fetchone()
        return row_to_dict(row)


def get_active_tasks() -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM tasks
        WHERE status IN ('open', 'in_progress')
        ORDER BY CASE status
            WHEN 'open' THEN 1
            WHEN 'in_progress' THEN 2
        END, created_at DESC
        """
    )


def get_tasks_by_statuses(statuses: Iterable[str]) -> list[dict[str, Any]]:
    status_list = list(statuses)
    if not status_list:
        return []
    placeholders = ",".join("?" * len(status_list))
    return fetch_all(
        f"SELECT * FROM tasks WHERE status IN ({placeholders})",
        tuple(status_list),
    )


def get_completed_tasks() -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM tasks
        WHERE status = 'completed'
        ORDER BY completed_at DESC
        """
    )


def clear_participants() -> None:
    execute("DELETE FROM participants")


def delete_tasks_by_statuses(statuses: Iterable[str]) -> None:
    status_list = list(statuses)
    if not status_list:
        return
    placeholders = ",".join("?" * len(status_list))
    execute(
        f"DELETE FROM tasks WHERE status IN ({placeholders})",
        tuple(status_list),
    )


def delete_task(task_id: str) -> None:
    execute("DELETE FROM tasks WHERE id = ?", (task_id,))


# --- async wrappers ---

async def aget_task(task_id: str) -> Optional[dict[str, Any]]:
    return await to_thread(get_task, task_id)


async def afetch_one(
    query: str,
    params: tuple | list = (),
) -> Optional[dict[str, Any]]:
    return await to_thread(fetch_one, query, params)


async def afetch_all(
    query: str,
    params: tuple | list = (),
) -> list[dict[str, Any]]:
    return await to_thread(fetch_all, query, params)


async def aexecute(query: str, params: tuple | list = ()) -> int:
    return await to_thread(execute, query, params)


async def aupdate_participant(*args: Any, **kwargs: Any) -> None:
    await to_thread(update_participant, *args, **kwargs)


async def acreate_task_row(**kwargs: Any) -> dict[str, Any]:
    return await to_thread(create_task_row, **kwargs)


async def aset_task_message(task_id: str, **kwargs: Any) -> None:
    await to_thread(set_task_message, task_id, **kwargs)


async def atry_accept_task(*args: Any, **kwargs: Any) -> tuple[str, Optional[dict[str, Any]]]:
    return await to_thread(try_accept_task, *args, **kwargs)


async def atry_complete_task(*args: Any, **kwargs: Any) -> tuple[str, Optional[dict[str, Any]]]:
    return await to_thread(try_complete_task, *args, **kwargs)


async def atry_abandon_task(*args: Any, **kwargs: Any) -> tuple[str, Optional[dict[str, Any]]]:
    return await to_thread(try_abandon_task, *args, **kwargs)


async def atry_confirm_task(task_id: str) -> Optional[dict[str, Any]]:
    return await to_thread(try_confirm_task, task_id)


async def atry_return_task(task_id: str) -> Optional[dict[str, Any]]:
    return await to_thread(try_return_task, task_id)


async def aget_active_tasks() -> list[dict[str, Any]]:
    return await to_thread(get_active_tasks)


async def aget_tasks_by_statuses(statuses: Iterable[str]) -> list[dict[str, Any]]:
    return await to_thread(get_tasks_by_statuses, statuses)


async def aget_completed_tasks() -> list[dict[str, Any]]:
    return await to_thread(get_completed_tasks)


async def aclear_participants() -> None:
    await to_thread(clear_participants)


async def adelete_tasks_by_statuses(statuses: Iterable[str]) -> None:
    await to_thread(delete_tasks_by_statuses, statuses)


async def adelete_task(task_id: str) -> None:
    await to_thread(delete_task, task_id)


# --- voice time tracking ---

def add_voice_seconds(user_id: str, user_name: str, seconds: int) -> None:
    if seconds <= 0:
        return
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO voice_totals (user_id, user_name, total_seconds)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                user_name = excluded.user_name,
                total_seconds = total_seconds + excluded.total_seconds
            """,
            (user_id, user_name, seconds),
        )


def insert_voice_session(
    *,
    user_id: str,
    user_name: str,
    channel_id: str,
    channel_name: str,
    started_at: str,
    ended_at: str,
    duration_seconds: int,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO voice_sessions (
                user_id, user_name, channel_id, channel_name,
                started_at, ended_at, duration_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                user_name,
                channel_id,
                channel_name,
                started_at,
                ended_at,
                max(0, duration_seconds),
            ),
        )


def cleanup_old_voice_sessions(retention_days: int) -> int:
    """Удаляет сессии старше retention_days. Возвращает число удалённых строк."""
    cutoff = datetime.now().timestamp() - retention_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM voice_sessions WHERE ended_at < ?",
            (cutoff_iso,),
        )
        return cur.rowcount


def apply_voice_flush(
    totals: list[tuple[str, str, int]],
    sessions: list[dict[str, Any]],
) -> None:
    """Один транзакционный flush: totals + закрытые сессии."""
    with get_connection() as conn:
        for user_id, user_name, seconds in totals:
            if seconds <= 0:
                continue
            conn.execute(
                """
                INSERT INTO voice_totals (user_id, user_name, total_seconds)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    user_name = excluded.user_name,
                    total_seconds = total_seconds + excluded.total_seconds
                """,
                (user_id, user_name, seconds),
            )
        for session in sessions:
            conn.execute(
                """
                INSERT INTO voice_sessions (
                    user_id, user_name, channel_id, channel_name,
                    started_at, ended_at, duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["user_id"],
                    session["user_name"],
                    session["channel_id"],
                    session["channel_name"],
                    session["started_at"],
                    session["ended_at"],
                    max(0, int(session["duration_seconds"])),
                ),
            )


async def aapply_voice_flush(
    totals: list[tuple[str, str, int]],
    sessions: list[dict[str, Any]],
) -> None:
    if not totals and not sessions:
        return
    await to_thread(apply_voice_flush, totals, sessions)


async def acleanup_old_voice_sessions(retention_days: int) -> int:
    return await to_thread(cleanup_old_voice_sessions, retention_days)
