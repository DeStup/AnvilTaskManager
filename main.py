import os
import uuid
import sqlite3
from datetime import datetime
from typing import Optional, List
import logging
from logging.handlers import RotatingFileHandler

import discord
from discord.ui import Button, View, Modal, TextInput, Select
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

# ============== НАСТРОЙКА ЛОГИРОВАНИЯ ==============
LOG_DIR = './logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))

action_logger = logging.getLogger('task_actions')
action_handler = RotatingFileHandler(
    f'{LOG_DIR}/actions.log',
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding='utf-8'
)
action_handler.setFormatter(log_formatter)
action_logger.addHandler(action_handler)
action_logger.setLevel(logging.INFO)

error_logger = logging.getLogger('task_errors')
error_handler = RotatingFileHandler(
    f'{LOG_DIR}/errors.log',
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding='utf-8'
)
error_handler.setFormatter(log_formatter)
error_logger.addHandler(error_handler)
error_logger.setLevel(logging.ERROR)


def get_user_info(interaction) -> str:
    return f"User: {interaction.user.name} (ID: {interaction.user.id})"


async def send_log_to_channel(bot, message: str, color: discord.Color = None):
    """Отправляет лог сообщение в указанный канал"""
    if not LOG_CHANNEL_ID:
        return
    try:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if not channel:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                description=message,
                color=color or discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.set_footer(text="Лог действий")
            await channel.send(embed=embed)
    except Exception as e:
        error_logger.error(f"Error sending log to channel: {e}")


# ============== КОНСТАНТЫ ==============
TASK_STATUSES = {
    "open": {"name": "📋 Открыта", "color": discord.Color.blue()},
    "in_progress": {"name": "⚙️ В работе", "color": discord.Color.gold()},
    "pending_approval": {"name": "⏳ Ожидает подтверждения", "color": discord.Color.purple()},
    "completed": {"name": "✅ Завершена", "color": discord.Color.green()},
    "cancelled": {"name": "❌ Отменена", "color": discord.Color.red()}
}
CLEAR_TYPES = {
    "rating": {"name": "Очистить рейтинг", "emoji": "🏆", "description": "Удалить всю статистику участников"},
    "tasks": {"name": "Очистить активные задачи", "emoji": "📋", "description": "Удалить все открытые и в работе задачи"},
    "archive": {"name": "Очистить архив", "emoji": "📦", "description": "Удалить все завершенные задачи"}
}

ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x]


def format_timestamp(dt_str: str, style: str = 'f') -> str:
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str)
        return f"<t:{int(dt.timestamp())}:{style}>"
    except Exception as e:
        error_logger.error(f"Error formatting timestamp: {e}")
        return dt_str[:16]


def has_permission(interaction: discord.Interaction) -> bool:
    user_id = interaction.user.id
    if user_id in ALLOWED_USERS:
        return True
    if interaction.user.guild_permissions.administrator:
        return True
    if interaction.user.guild_permissions.manage_guild:
        return True
    return False

async def send_task_log(bot, task_dict: dict, action: str, user_mention: str, color: discord.Color,
                        additional_info: str = None):
    """Универсальная функция для отправки логов о задачах"""
    # Формируем ссылку на задачу
    task_link = None
    if task_dict.get('channel_id') and task_dict.get('message_id'):
        try:
            task_link = f"https://discord.com/channels/@me/{task_dict['channel_id']}/{task_dict['message_id']}"
        except:
            pass

    # Базовое сообщение
    message_parts = [action]
    message_parts.append(f"**ID:** {task_dict['id']}")
    message_parts.append(f"**Автор:** <@{task_dict['author_id']}>")

    # Добавляем исполнителя если есть
    if task_dict.get('executor_id'):
        message_parts.append(f"**Исполнитель:** <@{task_dict['executor_id']}>")

    # Добавляем информацию о действии ТОЛЬКО если user_mention передан
    if user_mention:
        message_parts.append(f"**Действие:** {user_mention}")

    # Добавляем дополнительную информацию если есть
    if additional_info:
        message_parts.append(additional_info)

    # Добавляем ссылку если есть
    if task_link:
        message_parts.append(f"**🔗 Ссылка:** [Перейти к задаче]({task_link})")

    await send_log_to_channel(bot, "\n".join(message_parts), color)


async def send_simple_log(bot, action: str, user_mention: str, color: discord.Color, additional_info: str = None):
    """Универсальная функция для отправки простых логов (без задачи)"""
    message_parts = [action, f"**Действие:** {user_mention}"]
    if additional_info:
        message_parts.append(additional_info)
    await send_log_to_channel(bot, "\n".join(message_parts), color)

# ============== БАЗА ДАННЫХ ==============
class Database:
    def __init__(self, db_path: str = './data/tasks.db'):
        os.makedirs('./data', exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()

        # Создаем таблицу tasks
        cursor.execute('''
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
                message_id TEXT
            )
        ''')

        # Обновляем таблицу participants - добавляем колонку resolved_tasks если её нет
        cursor.execute("PRAGMA table_info(participants)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'resolved_tasks' not in columns:
            cursor.execute('ALTER TABLE participants ADD COLUMN resolved_tasks INTEGER DEFAULT 0')

        # Создаем таблицу если её нет
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL,
                completed_tasks INTEGER DEFAULT 0,
                created_tasks INTEGER DEFAULT 0,
                resolved_tasks INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()

    def execute(self, query: str, params: tuple = ()):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor, conn

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchone()
        conn.close()
        return result

    def fetch_all(self, query: str, params: tuple = ()) -> List[dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return results

    def update_participant(self, user_id: str, user_name: str,
                           completed_delta: int = 0, created_delta: int = 0, resolved_delta: int = 0):
        """Обновляет статистику участника"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Проверяем существование колонки resolved_tasks
        cursor.execute("PRAGMA table_info(participants)")
        columns = [col[1] for col in cursor.fetchall()]
        has_resolved = 'resolved_tasks' in columns

        if has_resolved:
            cursor.execute('''
                INSERT INTO participants (user_id, user_name, completed_tasks, created_tasks, resolved_tasks)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    user_name = excluded.user_name,
                    completed_tasks = completed_tasks + ?,
                    created_tasks = created_tasks + ?,
                    resolved_tasks = resolved_tasks + ?
            ''', (user_id, user_name, completed_delta, created_delta, resolved_delta,
                  completed_delta, created_delta, resolved_delta))
        else:
            # Для обратной совместимости
            cursor.execute('''
                INSERT INTO participants (user_id, user_name, completed_tasks, created_tasks)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    user_name = excluded.user_name,
                    completed_tasks = completed_tasks + ?,
                    created_tasks = created_tasks + ?
            ''', (user_id, user_name, completed_delta, created_delta, completed_delta, created_delta))

        conn.commit()
        conn.close()


db = Database()


# ============== БАЗОВЫЙ VIEW ==============
class BaseView(View):
    def __init__(self, user_id: int, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Вы не можете использовать это меню!", ephemeral=True)
            return False
        return True


# ============== МОДАЛЬНЫЕ ОКНА ==============
class TaskDescriptionModal(Modal, title="📝 Новая задача"):
    description = TextInput(
        label="Описание задачи",
        placeholder="Подробное описание задачи...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        task_id = str(uuid.uuid4())[:8]
        try:
            db.execute('''
                INSERT INTO tasks (id, description, status, author_id, author_name, created_at)
                VALUES (?, ?, 'open', ?, ?, ?)
            ''', (task_id, self.description.value, str(interaction.user.id), interaction.user.name,
                  datetime.now().isoformat()))

            db.update_participant(str(interaction.user.id), interaction.user.name, created_delta=1)

            embed = discord.Embed(
                description=f"```\n{self.description.value}\n```",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 Автор", value=interaction.user.mention, inline=True)
            embed.add_field(name="📌 Статус", value="📋 Открыта", inline=True)
            embed.add_field(name="⚙️ Исполнитель", value="❌ Не назначен", inline=True)
            embed.set_footer(text=f"ID: {task_id}")

            message = await interaction.channel.send(embed=embed, view=PersistentTaskView(task_id))

            db.execute('UPDATE tasks SET channel_id = ?, message_id = ? WHERE id = ?',
                       (str(interaction.channel.id), str(message.id), task_id))

            action_logger.info(f"{get_user_info(interaction)} created task {task_id}")

            # Получаем созданную задачу для лога
            task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (task_id,))
            task_dict = {key: task[key] for key in task.keys()}

            # Отправляем лог
            await send_task_log(
                interaction.client,
                task_dict,
                "📋 **Создана задача**",
                None,  # Убираем user_mention
                discord.Color.green()
            )

            await interaction.response.send_message(f"✅ Задача #{task_id} создана!", ephemeral=True)

        except Exception as e:
            error_logger.error(f"Error creating task: {e}", exc_info=True)
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)


class ConfirmClearModal(Modal, title="⚠️ Подтверждение очистки"):
    """Модальное окно для подтверждения очистки"""

    confirm = TextInput(
        label="Введите 'ПОДТВЕРДИТЬ' для подтверждения",
        placeholder="ПОДТВЕРДИТЬ",
        required=True,
        max_length=20
    )

    def __init__(self, clear_type: str):
        super().__init__()
        self.clear_type = clear_type

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value != "ПОДТВЕРДИТЬ":
            await interaction.response.send_message("❌ Очистка отменена: неверное подтверждение.", ephemeral=True)
            return

        clear_type_name = CLEAR_TYPES[self.clear_type]["name"]

        try:
            if self.clear_type == "rating":
                # Очищаем рейтинг
                db.execute('DELETE FROM participants')
                count = 0
                message = "Рейтинг очищен!"

            elif self.clear_type == "tasks":
                # Получаем список активных задач для удаления сообщений
                tasks = db.fetch_all('SELECT * FROM tasks WHERE status IN ("open", "in_progress", "pending_approval")')
                count = len(tasks)

                # Удаляем сообщения из каналов
                for task in tasks:
                    if task['channel_id'] and task['message_id']:
                        try:
                            channel = interaction.client.get_channel(int(task['channel_id']))
                            if channel:
                                message = await channel.fetch_message(int(task['message_id']))
                                await message.delete()
                        except Exception as e:
                            error_logger.error(f"Error deleting message for task {task['id']}: {e}")

                # Удаляем задачи из БД
                db.execute('DELETE FROM tasks WHERE status IN ("open", "in_progress", "pending_approval")')
                message = f"Очищено {count} активных задач!"

            elif self.clear_type == "archive":
                # Получаем список архивных задач для удаления сообщений
                tasks = db.fetch_all('SELECT * FROM tasks WHERE status = "completed"')
                count = len(tasks)

                # Удаляем сообщения из каналов
                for task in tasks:
                    if task['channel_id'] and task['message_id']:
                        try:
                            channel = interaction.client.get_channel(int(task['channel_id']))
                            if channel:
                                message = await channel.fetch_message(int(task['message_id']))
                                await message.delete()
                        except Exception as e:
                            error_logger.error(f"Error deleting message for task {task['id']}: {e}")

                # Удаляем задачи из БД
                db.execute('DELETE FROM tasks WHERE status = "completed"')
                message = f"Очищено {count} завершенных задач!"

            else:
                await interaction.response.send_message("❌ Неизвестный тип очистки.", ephemeral=True)
                return

            # Логируем действие
            action_logger.info(f"{get_user_info(interaction)} cleared {clear_type_name}")

            # Отправляем лог в канал
            await send_simple_log(
                interaction.client,
                f"🧹 **{clear_type_name}**",
                interaction.user.mention,
                discord.Color.red(),
                f"{message}"
            )

            await interaction.response.send_message(message, ephemeral=True)

        except Exception as e:
            error_logger.error(f"Error clearing {self.clear_type}: {e}", exc_info=True)
            await interaction.response.send_message(f"❌ Ошибка при очистке: {str(e)}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        error_logger.error(f"Modal error: {error}", exc_info=True)
        await interaction.response.send_message(f"❌ Ошибка: {str(error)}", ephemeral=True)


class ClearSelect(Select):
    """Выпадающий список для выбора типа очистки"""

    def __init__(self):
        options = []
        for key, value in CLEAR_TYPES.items():
            options.append(discord.SelectOption(
                label=value["name"],
                value=key,
                emoji=value["emoji"],
                description=value["description"]
            ))

        super().__init__(
            placeholder="🔧 Выберите что очистить...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] not in CLEAR_TYPES:
            await interaction.response.send_message("❌ Неверный выбор.", ephemeral=True)
            return

        # Открываем модальное окно для подтверждения
        modal = ConfirmClearModal(self.values[0])
        await interaction.response.send_modal(modal)


class ClearView(View):
    """View для выбора типа очистки"""

    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(ClearSelect())


class RatingCorrectionModal(Modal, title="📊 Изменение рейтинга"):
    """Модальное окно для ввода нового значения рейтинга"""

    new_rating = TextInput(
        label="Новый рейтинг",
        placeholder="Введите новое значение рейтинга...",
        required=True,
        min_length=1,
        max_length=10
    )

    def __init__(self, user_id: str, user_name: str, current_rating: int):
        super().__init__()
        self.user_id = user_id
        self.user_name = user_name
        self.current_rating = current_rating
        self.new_rating.placeholder = f"Текущий рейтинг: {current_rating}"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_value = int(self.new_rating.value)

            if new_value < 0:
                await interaction.response.send_message(
                    "❌ Рейтинг не может быть отрицательным!",
                    ephemeral=True
                )
                return

            # Обновляем рейтинг
            db.execute('''
                UPDATE participants 
                SET completed_tasks = ?
                WHERE user_id = ?
            ''', (new_value, self.user_id))

            # Логируем в файл
            action_logger.info(
                f"{get_user_info(interaction)} changed rating for {self.user_name} (ID: {self.user_id}) "
                f"from {self.current_rating} to {new_value}"
            )

            # Отправляем лог в канал
            await send_simple_log(
                interaction.client,
                f"📊 **Коррекция рейтинга**",
                interaction.user.mention,
                discord.Color.blue(),
                f"**Пользователь:** <@{self.user_id}>\n"
                f"**Было:** {self.current_rating}\n"
                f"**Стало:** {new_value}"
            )

            await interaction.response.send_message(
                f"✅ Рейтинг пользователя <@{self.user_id}> изменён с {self.current_rating} на {new_value}!",
                ephemeral=True
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ Введите корректное число!",
                ephemeral=True
            )
        except Exception as e:
            error_logger.error(f"Error correcting rating: {e}", exc_info=True)
            await interaction.response.send_message(
                f"❌ Ошибка: {str(e)}",
                ephemeral=True
            )

# ============== ПАГИНАЦИЯ ==============
class PaginationView(BaseView):
    """View с пагинацией для списков"""

    def __init__(self, user_id: int, items: List[dict], items_per_page: int = 10, title: str = "Список",
                 color: discord.Color = discord.Color.blue(), refresh_callback=None):
        super().__init__(user_id, timeout=120)
        self.items = items
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = max(1, (len(items) + items_per_page - 1) // items_per_page)
        self.title = title
        self.color = color
        self.refresh_callback = refresh_callback
        self._update_buttons()

    def _update_buttons(self):
        """Обновляет состояние кнопок в зависимости от страницы"""
        self.clear_items()

        # Кнопки навигации
        prev_button = Button(label="◀", style=discord.ButtonStyle.secondary, row=0)
        prev_button.callback = self.prev_page
        prev_button.disabled = self.current_page == 0
        self.add_item(prev_button)

        page_button = Button(label=f"Страница {self.current_page + 1}/{self.total_pages}",
                             style=discord.ButtonStyle.secondary, disabled=True, row=0)
        self.add_item(page_button)

        next_button = Button(label="▶", style=discord.ButtonStyle.secondary, row=0)
        next_button.callback = self.next_page
        next_button.disabled = self.current_page >= self.total_pages - 1
        self.add_item(next_button)

        # Кнопка обновления УДАЛЕНА

    async def refresh(self, interaction: discord.Interaction):
        """Обновить список задач (оставлен для обратной совместимости, но не используется)"""
        if self.refresh_callback:
            new_items = await self.refresh_callback(interaction)
            if new_items is not None:
                self.items = new_items
                self.total_pages = max(1, (len(self.items) + self.items_per_page - 1) // self.items_per_page)
                self.current_page = min(self.current_page, self.total_pages - 1)
                self._update_buttons()
                await self._update_and_send(interaction)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        await self._update_and_send(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        await self._update_and_send(interaction)

    async def _update_and_send(self, interaction: discord.Interaction):
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.items))
        current_items = self.items[start_idx:end_idx]

        embed = self._create_embed(current_items, start_idx + 1, end_idx)
        self._update_buttons()

        await interaction.response.edit_message(embed=embed, view=self)

    def _create_embed(self, items: List[dict], start_num: int, end_num: int) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            color=self.color
        )

        for idx, item in enumerate(items):
            # Преобразуем sqlite3.Row в dict если нужно
            if hasattr(item, 'keys'):
                item_dict = {key: item[key] for key in item.keys()}
            else:
                item_dict = item

            # Выделяем описание в блок кода
            description_text = item_dict['description']
            if len(description_text) > 80:
                description_text = description_text[:77] + "..."

            formatted_description = f"```\n{description_text}\n```"

            if item_dict.get('completed_at') and item_dict['completed_at']:
                # Это задача из архива - без ссылки
                completed_by = item_dict.get('executor_id') if item_dict.get('executor_id') else None

                if completed_by:
                    executor_text = f"⚙️ <@{completed_by}>"
                else:
                    executor_text = "⚙️ Неизвестно"

                embed.add_field(
                    name="\u200b",
                    value=(
                        f"{formatted_description}"
                        f"👤 <@{item_dict['author_id']}> • {executor_text} • ✅ {format_timestamp(item_dict['completed_at'], 'f')}"
                    ),
                    inline=False
                )
            else:
                # Это активная задача - со ссылкой
                status_emoji = {"open": "📋", "in_progress": "⚙️"}.get(item_dict['status'], "📋")
                status_name = {"open": "Открыта", "in_progress": "В работе"}.get(item_dict['status'],
                                                                                 item_dict['status'])
                executor = item_dict.get('executor_id') if item_dict.get('executor_id') else None

                # Формируем ссылку на сообщение задачи
                message_link = "—"
                if item_dict.get('channel_id') and item_dict.get('message_id'):
                    try:
                        message_link = f"https://discord.com/channels/@me/{item_dict['channel_id']}/{item_dict['message_id']}"
                    except:
                        message_link = "—"

                # Формируем строку исполнителя
                executor_text = f"⚙️ <@{executor}>" if executor else "⚙️ ❌"

                embed.add_field(
                    name="\u200b",
                    value=(
                        f"{formatted_description}"
                        f"👤 <@{item_dict['author_id']}> • {executor_text} • {status_emoji} {status_name} • 📅 {format_timestamp(item_dict['created_at'], 'f')}"
                        f"\n🔗 [Перейти]({message_link})" if message_link != "—" else ""
                    ),
                    inline=False
                )

            # Добавляем разделитель между задачами (более короткий)
            if idx < len(items) - 1:
                embed.add_field(name="\u200b", value="•" * 30, inline=False)

        return embed


class RatingPaginationView(BaseView):
    """View с пагинацией для рейтинга"""

    def __init__(self, user_id: int, items: List[dict], items_per_page: int = 10):
        super().__init__(user_id, timeout=120)
        self.items = items
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = max(1, (len(items) + items_per_page - 1) // items_per_page)
        self._update_buttons()

    def _update_buttons(self):
        """Обновляет состояние кнопок в зависимости от страницы"""
        self.clear_items()

        # Кнопки навигации
        prev_button = Button(label="◀", style=discord.ButtonStyle.secondary, row=0)
        prev_button.callback = self.prev_page
        prev_button.disabled = self.current_page == 0
        self.add_item(prev_button)

        page_button = Button(
            label=f"Страница {self.current_page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=0
        )
        self.add_item(page_button)

        next_button = Button(label="▶", style=discord.ButtonStyle.secondary, row=0)
        next_button.callback = self.next_page
        next_button.disabled = self.current_page >= self.total_pages - 1
        self.add_item(next_button)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        await self._update_and_send(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        await self._update_and_send(interaction)

    async def _update_and_send(self, interaction: discord.Interaction):
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.items))
        current_items = self.items[start_idx:end_idx]

        embed = await self._create_embed(current_items, start_idx + 1, end_idx, interaction)
        self._update_buttons()

        await interaction.response.edit_message(embed=embed, view=self)

    async def _create_embed(self, items: List[dict], start_num: int, end_num: int,
                            interaction: discord.Interaction) -> discord.Embed:
        embed = discord.Embed(
            title="🏆 Рейтинг исполнителей",
            color=discord.Color.gold()
        )

        # Получаем всех участников сервера для быстрого поиска
        guild = interaction.guild
        members = {str(member.id): member for member in guild.members} if guild else {}

        # Глобальный индекс для определения медалей
        global_idx = start_num - 1

        for idx, item in enumerate(items):
            current_global_idx = global_idx + idx + 1

            # Определяем медаль для топ-3
            medal = ""
            if current_global_idx == 1:
                medal = "🥇 "
            elif current_global_idx == 2:
                medal = "🥈 "
            elif current_global_idx == 3:
                medal = "🥉 "
            else:
                medal = f"{current_global_idx}. "

            user_id = item['user_id']

            # Получаем актуальный никнейм пользователя (для отображения)
            display_name = "Неизвестный пользователь"
            if user_id in members:
                member = members[user_id]
                display_name = member.display_name
            else:
                try:
                    user = await interaction.client.fetch_user(int(user_id))
                    display_name = user.display_name
                except Exception as e:
                    error_logger.error(f"Error fetching user {user_id}: {e}")
                    display_name = f"User {user_id[:6]}"

            # ВАЖНО: упоминание помещаем в value, а не в name
            # В name оставляем только медаль и никнейм (для красоты)
            embed.add_field(
                name="\u200b",  # Невидимый разделитель
                value=(
                    f"{medal}<@{user_id}> - {item['completed_tasks']}"
                ),
                inline=False
            )

        return embed

# ============== ПЕРСИСТЕНТНЫЕ КНОПКИ ==============
class PersistentTaskView(discord.ui.View):
    def __init__(self, task_id: str):
        super().__init__(timeout=None)
        self.task_id = task_id
        self._add_buttons()

    def _add_buttons(self):
        task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (self.task_id,))
        if not task:
            return
        if task['status'] == 'open':
            self.add_item(PersistentAcceptButton(self.task_id))
            self.add_item(PersistentDeleteButton(self.task_id))
        elif task['status'] == 'in_progress':
            self.add_item(PersistentCompleteButton(self.task_id))
            self.add_item(PersistentAbandonButton(self.task_id))
            self.add_item(PersistentDeleteButton(self.task_id))
        elif task['status'] == 'pending_approval':
            self.add_item(PersistentConfirmButton(self.task_id))
            self.add_item(PersistentReturnButton(self.task_id))
            self.add_item(PersistentDeleteButton(self.task_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not db.fetch_one('SELECT * FROM tasks WHERE id = ?', (self.task_id,)):
            await interaction.response.send_message("❌ Задача не найдена.", ephemeral=True)
            return False
        return True


class PersistentAcceptButton(discord.ui.Button):
    def __init__(self, task_id: str):
        super().__init__(label="Принять", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"accept_{task_id}")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await accept_task_action(interaction, self.task_id)


class PersistentCompleteButton(discord.ui.Button):
    def __init__(self, task_id: str):
        super().__init__(label="Завершить", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"complete_{task_id}")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await complete_task_action(interaction, self.task_id, None)


class PersistentAbandonButton(discord.ui.Button):
    def __init__(self, task_id: str):
        super().__init__(label="Отказаться", style=discord.ButtonStyle.secondary, emoji="↩️", custom_id=f"abandon_{task_id}")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await abandon_task_action(interaction, self.task_id, None)


class PersistentConfirmButton(discord.ui.Button):
    def __init__(self, task_id: str):
        super().__init__(label="Подтвердить", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"confirm_{task_id}")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await confirm_task_action(interaction, self.task_id)


class PersistentReturnButton(discord.ui.Button):
    def __init__(self, task_id: str):
        super().__init__(label="Вернуть", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id=f"return_{task_id}")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await return_task_action(interaction, self.task_id, None)


class PersistentDeleteButton(discord.ui.Button):
    def __init__(self, task_id: str):
        super().__init__(label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id=f"delete_{task_id}")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await delete_task_action(interaction, self.task_id)


# ============== ВЫПАДАЮЩИЕ СПИСКИ ==============
class TaskSelect(Select):
    def __init__(self, action_type: str, user_id: int, task_status: str = None):
        self.action_type = action_type
        self.user_id = user_id
        tasks = db.fetch_all('SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC', (task_status,)) if task_status else db.fetch_all('SELECT * FROM tasks WHERE status IN ("open", "in_progress") ORDER BY CASE status WHEN "open" THEN 1 WHEN "in_progress" THEN 2 END, created_at DESC')
        options = self._build_options(tasks, action_type, user_id)
        super().__init__(placeholder="🔍 Выберите задачу...", min_values=1, max_values=1, options=options)

    def _build_options(self, tasks, action_type, user_id):
        options = []
        filtered = []
        if action_type == "take":
            filtered = [t for t in tasks if t['status'] == 'open']
        elif action_type == "my_tasks":
            filtered = [t for t in tasks if t['executor_id'] == str(user_id) and t['status'] == 'in_progress']
        elif action_type == "archive":
            filtered = [t for t in tasks if t['status'] == 'completed']
        else:
            filtered = tasks

        if not filtered:
            options.append(discord.SelectOption(label="Нет задач", value="none", description="Список пуст", emoji="📭"))
        else:
            for task in filtered[:25]:
                status_emoji = {"open": "📋", "in_progress": "⚙️", "completed": "✅"}.get(task['status'], "📋")
                options.append(discord.SelectOption(label=f"{status_emoji} {task['id']}", value=task['id'], description=f"{task['description'][:50]}...", emoji="📋"))
        return options

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("Нет доступных задач.", ephemeral=True)
            return
        task_id = self.values[0]
        actions = {"take": lambda: accept_task_action(interaction, task_id), "delete": lambda: delete_task_action(interaction, task_id), "view": lambda: show_task_detail(interaction, task_id), "my_tasks": lambda: show_my_task_detail(interaction, task_id)}
        if self.action_type in actions:
            await actions[self.action_type]()


class TaskSelectView(BaseView):
    def __init__(self, action_type: str, user_id: int, task_status: str = None):
        super().__init__(user_id, timeout=60)
        self.add_item(TaskSelect(action_type, user_id, task_status))


# ============== ОСНОВНЫЕ ФУНКЦИИ ==============
async def update_task_message(interaction: discord.Interaction, task_id: str):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (task_id,))
    if not task:
        return

    task_dict = {key: task[key] for key in task.keys()}

    # Определяем цвета в зависимости от статуса
    colors = {
        "open": discord.Color.blue(),
        "in_progress": discord.Color.gold(),
        "pending_approval": discord.Color.purple(),
        "completed": discord.Color.green()
    }

    # Статусы с эмодзи
    status_emoji = {
        "open": "📋",
        "in_progress": "⚙️",
        "pending_approval": "⏳",
        "completed": "✅"
    }
    status_name = {
        "open": "Открыта",
        "in_progress": "В работе",
        "pending_approval": "Ожидает подтверждения",
        "completed": "Завершена"
    }

    # Создаем embed ТАКОЙ ЖЕ как при создании
    embed = discord.Embed(
        description=f"```\n{task_dict['description']}\n```",
        color=colors.get(task_dict['status'], discord.Color.blue()),
        timestamp=datetime.now()
    )

    embed.add_field(name="👤 Автор", value=f"<@{task_dict['author_id']}>", inline=True)
    embed.add_field(
        name="📌 Статус",
        value=f"{status_emoji.get(task_dict['status'], '📋')} {status_name.get(task_dict['status'], task_dict['status'])}",
        inline=True
    )

    if task_dict.get('executor_id'):
        embed.add_field(name="⚙️ Исполнитель", value=f"<@{task_dict['executor_id']}>", inline=True)
    else:
        embed.add_field(name="⚙️ Исполнитель", value="❌ Не назначен", inline=True)

    embed.set_footer(text=f"ID: {task_dict['id']}")

    try:
        channel = interaction.client.get_channel(int(task_dict['channel_id']))
        if channel:
            message = await channel.fetch_message(int(task_dict['message_id']))
            await message.edit(embed=embed, view=PersistentTaskView(task_dict['id']))
    except Exception as e:
        error_logger.error(f"Error updating message: {e}")


async def accept_task_action(interaction: discord.Interaction, task_id: str):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ? AND status = "open"', (task_id,))
    if not task:
        await interaction.response.send_message("❌ Задача уже взята в работу.", ephemeral=True)
        return
    if task['author_id'] == str(interaction.user.id):
        await interaction.response.send_message("❌ Вы не можете принять свою задачу.", ephemeral=True)
        return

    db.execute('UPDATE tasks SET status = "in_progress", executor_id = ?, executor_name = ?, taken_at = ? WHERE id = ?',
               (str(interaction.user.id), interaction.user.name, datetime.now().isoformat(), task_id))

    action_logger.info(f"{get_user_info(interaction)} accepted task {task_id}")

    # Получаем обновленную задачу
    updated_task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task_dict = {key: updated_task[key] for key in updated_task.keys()}

    # Отправляем лог без Автора и Действия
    message_parts = [
        "📥 **Задача принята**",
        f"**ID:** {task_id}",
        f"**Исполнитель:** {interaction.user.mention}"
    ]

    # Добавляем ссылку если есть
    task_link = None
    if task_dict.get('channel_id') and task_dict.get('message_id'):
        try:
            task_link = f"https://discord.com/channels/@me/{task_dict['channel_id']}/{task_dict['message_id']}"
            message_parts.append(f"**🔗 Ссылка:** [Перейти к задаче]({task_link})")
        except:
            pass

    await send_log_to_channel(interaction.client, "\n".join(message_parts), discord.Color.gold())

    await update_task_message(interaction, task_id)
    await interaction.response.send_message(f"✅ Вы приняли задачу #{task_id}!", ephemeral=True)


async def complete_task_action(interaction: discord.Interaction, task_id: str, comment: str = None):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ? AND executor_id = ? AND status = "in_progress"',
                        (task_id, str(interaction.user.id)))
    if not task:
        await interaction.response.send_message("❌ Не удалось завершить задачу.", ephemeral=True)
        return

    db.execute('UPDATE tasks SET status = "pending_approval" WHERE id = ?', (task_id,))

    action_logger.info(f"{get_user_info(interaction)} completed task {task_id}")

    # Получаем обновленную задачу
    updated_task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task_dict = {key: updated_task[key] for key in updated_task.keys()}

    # Отправляем лог без Автора и Действия
    message_parts = [
        "✅ **Задача выполнена**",
        f"**ID:** {task_id}",
        f"**Исполнитель:** {interaction.user.mention}",
        "⏳ Ожидает подтверждения от автора."
    ]

    # Добавляем ссылку если есть
    task_link = None
    if task_dict.get('channel_id') and task_dict.get('message_id'):
        try:
            task_link = f"https://discord.com/channels/@me/{task_dict['channel_id']}/{task_dict['message_id']}"
            message_parts.append(f"**🔗 Ссылка:** [Перейти к задаче]({task_link})")
        except:
            pass

    await send_log_to_channel(interaction.client, "\n".join(message_parts), discord.Color.purple())

    await update_task_message(interaction, task_id)
    await interaction.response.send_message(f"✅ Задача #{task_id} выполнена! Ожидайте подтверждения.", ephemeral=True)


async def abandon_task_action(interaction: discord.Interaction, task_id: str, reason: str = None):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ? AND executor_id = ? AND status = "in_progress"',
                        (task_id, str(interaction.user.id)))
    if not task:
        await interaction.response.send_message("❌ Не удалось отказаться от задачи.", ephemeral=True)
        return

    db.execute(
        'UPDATE tasks SET status = "open", executor_id = NULL, executor_name = NULL, taken_at = NULL, cancel_comment = NULL WHERE id = ?',
        (task_id,))

    action_logger.info(f"{get_user_info(interaction)} abandoned task {task_id}")

    # Получаем обновленную задачу
    updated_task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task_dict = {key: updated_task[key] for key in updated_task.keys()}

    # Отправляем лог без Автора
    message_parts = [
        "↩️ **Отказ от задачи**",
        f"**ID:** {task_id}",
        f"**Исполнитель:** {interaction.user.mention}"
    ]

    # Добавляем ссылку если есть
    task_link = None
    if task_dict.get('channel_id') and task_dict.get('message_id'):
        try:
            task_link = f"https://discord.com/channels/@me/{task_dict['channel_id']}/{task_dict['message_id']}"
            message_parts.append(f"**🔗 Ссылка:** [Перейти к задаче]({task_link})")
        except:
            pass

    await send_log_to_channel(interaction.client, "\n".join(message_parts), discord.Color.orange())

    await update_task_message(interaction, task_id)
    await interaction.response.send_message(f"↩️ Вы отказались от задачи #{task_id}.", ephemeral=True)


async def confirm_task_action(interaction: discord.Interaction, task_id: str):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ? AND status = "pending_approval"', (task_id,))
    if not task:
        await interaction.response.send_message("❌ Задача не найдена или не ожидает подтверждения.", ephemeral=True)
        return

    is_author = task['author_id'] == str(interaction.user.id)
    has_admin_rights = has_permission(interaction)

    if not (is_author or has_admin_rights):
        await interaction.response.send_message("❌ Только автор или администратор могут подтвердить выполнение.",
                                                ephemeral=True)
        return

    task_dict = {key: task[key] for key in task.keys()}

    # Сохраняем ссылку до удаления сообщения
    task_link = None
    if task_dict.get('channel_id') and task_dict.get('message_id'):
        try:
            task_link = f"https://discord.com/channels/@me/{task_dict['channel_id']}/{task_dict['message_id']}"
        except:
            pass

    db.execute('UPDATE tasks SET status = "completed", completed_at = ? WHERE id = ?',
               (datetime.now().isoformat(), task_id))

    # Начисляем очки:
    # 1. Исполнитель получает +1 в resolved_tasks (выполненные задачи)
    if task_dict.get('executor_id'):
        db.update_participant(task_dict['executor_id'], task_dict['executor_name'], resolved_delta=1)

    # 2. Автор получает +1 в created_tasks (уже начислено при создании)
    #    и +1 в completed_tasks (за то что подтвердил)
    if task_dict.get('author_id'):
        db.update_participant(task_dict['author_id'], task_dict['author_name'], completed_delta=1)

    action_logger.info(f"{get_user_info(interaction)} confirmed task {task_id}")

    # Отправляем лог
    message_parts = [
        "✨ **Задача подтверждена**",
        f"**ID:** {task_id}",
        f"**Автор:** <@{task_dict['author_id']}>",
        f"**Исполнитель:** <@{task_dict['executor_id']}>" if task_dict.get('executor_id') else None,
        f"**Начислено:** Исполнитель +1 resolved, Автор +1 completed"
    ]
    message_parts = [p for p in message_parts if p]
    if task_link:
        message_parts.append(f"**🔗 Ссылка:** [Перейти к задаче]({task_link})")

    await send_log_to_channel(interaction.client, "\n".join(message_parts), discord.Color.green())

    # Удаляем сообщение из канала
    try:
        if task_dict.get('channel_id') and task_dict.get('message_id'):
            channel = interaction.client.get_channel(int(task_dict['channel_id']))
            if channel:
                message = await channel.fetch_message(int(task_dict['message_id']))
                await message.delete()
    except Exception as e:
        error_logger.error(f"Error deleting message for task {task_id}: {e}")

    await interaction.response.send_message(f"✅ Задача #{task_id} успешно выполнена и подтверждена!", ephemeral=True)


async def return_task_action(interaction: discord.Interaction, task_id: str, reason: str = None):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ? AND status = "pending_approval"', (task_id,))
    if not task:
        await interaction.response.send_message("❌ Задача не найдена.", ephemeral=True)
        return
    if task['author_id'] != str(interaction.user.id) and not has_permission(interaction):
        await interaction.response.send_message("❌ Только автор может вернуть задачу.", ephemeral=True)
        return

    task_dict = {key: task[key] for key in task.keys()}
    db.execute('UPDATE tasks SET status = "in_progress", completed_at = NULL WHERE id = ?', (task_id,))
    action_logger.info(f"{get_user_info(interaction)} returned task {task_id}")

    # Отправляем лог без Действия и Исполнителя
    message_parts = [
        "🔄 **Задача возвращена в работу**",
        f"**ID:** {task_id}",
        f"**Автор:** <@{task_dict['author_id']}>"
    ]

    # Добавляем ссылку если есть
    task_link = None
    if task_dict.get('channel_id') and task_dict.get('message_id'):
        try:
            task_link = f"https://discord.com/channels/@me/{task_dict['channel_id']}/{task_dict['message_id']}"
            message_parts.append(f"**🔗 Ссылка:** [Перейти к задаче]({task_link})")
        except:
            pass

    await send_log_to_channel(interaction.client, "\n".join(message_parts), discord.Color.orange())

    await update_task_message(interaction, task_id)

    if task_dict.get('executor_id'):
        try:
            executor = await interaction.client.fetch_user(int(task_dict['executor_id']))
            embed = discord.Embed(title="🔄 Задача возвращена в работу",
                                  description=f"Задача **#{task_id}** возвращена.", color=discord.Color.orange())
            embed.add_field(name="👤 Автор", value=interaction.user.mention)
            embed.add_field(name="📝 Описание", value=task_dict['description'][:200])

            if task_link:
                embed.add_field(name="🔗 Ссылка", value=f"[Перейти к задаче]({task_link})")
            await executor.send(embed=embed)
        except Exception as e:
            error_logger.error(f"Error notifying executor: {e}")

    await interaction.response.send_message(f"🔄 Задача #{task_id} возвращена в работу.", ephemeral=True)

async def delete_task_action(interaction: discord.Interaction, task_id: str):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (task_id,))
    if not task:
        await interaction.response.send_message("❌ Задача не найдена.", ephemeral=True)
        return

    is_author = task['author_id'] == str(interaction.user.id)
    is_admin_or_dev = has_permission(interaction)

    if not (is_author or is_admin_or_dev):
        await interaction.response.send_message("❌ Вы не можете удалить эту задачу.", ephemeral=True)
        return

    task_dict = {key: task[key] for key in task.keys()}
    channel_id = task_dict.get('channel_id')
    message_id = task_dict.get('message_id')

    # Сохраняем ссылку до удаления
    task_link = None
    if channel_id and message_id:
        try:
            task_link = f"https://discord.com/channels/@me/{channel_id}/{message_id}"
        except:
            pass

    db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))

    # Удаляем сообщение из канала
    if channel_id and message_id:
        try:
            channel = interaction.client.get_channel(int(channel_id))
            if channel:
                message = await channel.fetch_message(int(message_id))
                await message.delete()
        except Exception as e:
            error_logger.error(f"Error deleting message for task {task_id}: {e}")

    action_logger.info(f"{get_user_info(interaction)} deleted task {task_id}")

    # Отправляем лог с "Удалил" вместо "Действие"
    message_parts = [
        "🗑️ **Задача удалена**",
        f"**ID:** {task_id}",
        f"**Автор:** <@{task_dict['author_id']}>",
        f"**Удалил:** {interaction.user.mention}"
    ]

    await send_log_to_channel(interaction.client, "\n".join(message_parts), discord.Color.red())
    await interaction.response.send_message(f"🗑️ Задача `{task_id}` успешно удалена!", ephemeral=True)

def _create_task_embed(task: dict) -> discord.Embed:
    status = TASK_STATUSES.get(task['status'], {'name': task['status'], 'color': discord.Color.default()})
    embed = discord.Embed(title=f"📋 Задача {task['id']}", color=status['color'])
    embed.add_field(name="📝 Описание", value=task['description'], inline=False)
    embed.add_field(name="📌 Статус", value=status['name'], inline=True)
    embed.add_field(name="👤 Автор", value=f"<@{task['author_id']}>", inline=True)
    if task.get('executor_name'):
        embed.add_field(name="⚙️ Исполнитель", value=f"<@{task['executor_id']}>", inline=True)
    embed.add_field(name="📅 Создана", value=format_timestamp(task['created_at'], 'f'), inline=True)
    if task.get('taken_at'):
        embed.add_field(name="⏰ Взята", value=format_timestamp(task['taken_at'], 'f'), inline=True)
    if task.get('completed_at'):
        embed.add_field(name="✅ Завершена", value=format_timestamp(task['completed_at'], 'f'), inline=True)
    if task.get('cancel_comment'):
        embed.add_field(name="💬 Комментарий", value=task['cancel_comment'], inline=False)
    return embed


async def show_task_detail(interaction: discord.Interaction, task_id: str):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ?', (task_id,))
    if not task:
        await interaction.response.send_message("❌ Задача не найдена.", ephemeral=True)
        return
    task_dict = {key: task[key] for key in task.keys()}
    embed = _create_task_embed(task_dict)
    view = TaskSelectView("view", interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def show_my_task_detail(interaction: discord.Interaction, task_id: str):
    task = db.fetch_one('SELECT * FROM tasks WHERE id = ? AND executor_id = ?', (task_id, str(interaction.user.id)))
    if not task:
        await interaction.response.send_message("❌ Задача не найдена.", ephemeral=True)
        return
    embed = _create_task_embed({key: task[key] for key in task.keys()})
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def show_task_list(interaction: discord.Interaction, filter_type: str = "all"):
    """Показать список активных задач с пагинацией и ссылками"""

    tasks = db.fetch_all('''
        SELECT * FROM tasks 
        WHERE status IN ('open', 'in_progress')
        ORDER BY CASE status WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 END, created_at DESC
    ''')
    tasks = [dict(task) for task in tasks]

    if not tasks:
        embed = discord.Embed(
            title="📭 Список задач",
            description="Активных задач пока нет. /add чтобы добавить задачу",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = PaginationView(
        user_id=interaction.user.id,
        items=tasks,
        items_per_page=10,
        title="📋 Список задач",  # Убрано "активных"
        color=discord.Color.blue()
    )

    start_idx = 0
    end_idx = min(10, len(tasks))
    current_items = tasks[start_idx:end_idx]
    embed = view._create_embed(current_items, start_idx + 1, end_idx)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def show_archive(interaction: discord.Interaction):
    """Показать архив завершенных задач"""

    tasks = db.fetch_all('''
        SELECT * FROM tasks 
        WHERE status = 'completed'
        ORDER BY completed_at DESC
    ''')
    tasks = [dict(task) for task in tasks]

    if not tasks:
        embed = discord.Embed(
            title="📦 Архив задач",
            description="Завершенных задач пока нет.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = PaginationView(
        user_id=interaction.user.id,
        items=tasks,
        items_per_page=10,
        title="📦 Архив завершенных задач",
        color=discord.Color.purple()
    )

    start_idx = 0
    end_idx = min(10, len(tasks))
    current_items = tasks[start_idx:end_idx]
    embed = view._create_embed(current_items, start_idx + 1, end_idx)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def show_rating(interaction: discord.Interaction):
    """Показать рейтинг исполнителей с пагинацией и упоминаниями"""

    # Получаем всех участников с их статистикой
    participants = db.fetch_all('''
        SELECT user_id, completed_tasks
        FROM participants
        ORDER BY completed_tasks DESC
    ''')

    # Преобразуем в список словарей
    participants = [dict(p) for p in participants]

    if not participants:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🏆 Рейтинг исполнителей",
                description="Пока нет участников с выполненными задачами.",
                color=discord.Color.blue()
            ),
            ephemeral=True
        )
        return

    # Создаем view с пагинацией
    view = RatingPaginationView(
        user_id=interaction.user.id,
        items=participants,
        items_per_page=10
    )

    # Отправляем первую страницу
    start_idx = 0
    end_idx = min(10, len(participants))
    current_items = participants[start_idx:end_idx]
    embed = await view._create_embed(current_items, 1, end_idx, interaction)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ============== ГЛАВНОЕ МЕНЮ ==============
class TaskMenuView(BaseView):
    """Главное меню с кнопками"""

    def __init__(self, user_id: int):
        super().__init__(user_id, timeout=180)
        self._setup_buttons()

    def _setup_buttons(self):
        # Ряд 0
        self.add_item(self._create_button("Список задач", discord.ButtonStyle.primary, "📋", self.list_button, 0))
        self.add_item(self._create_button("Рейтинг", discord.ButtonStyle.secondary, "🏆", self.rating_button, 0))

        # Ряд 1
        self.add_item(self._create_button("Архив", discord.ButtonStyle.secondary, "📦", self.archive_button, 1))
        self.add_item(self._create_button("Удалить задачу", discord.ButtonStyle.danger, "🗑️", self.delete_button, 1))

        # Ряд 2
        self.add_item(self._create_button("Очистка", discord.ButtonStyle.danger, "🧹", self.clear_button, 2))
        self.add_item(
            self._create_button("Коррекция рейтинга", discord.ButtonStyle.primary, "📊", self.correction_button, 2))

    def _create_button(self, label: str, style: discord.ButtonStyle, emoji: str,
                       callback_func, row: int) -> Button:
        button = Button(label=label, style=style, emoji=emoji, row=row)
        button.callback = callback_func
        return button

    async def list_button(self, interaction: discord.Interaction):
        await show_task_list(interaction, "all")

    async def rating_button(self, interaction: discord.Interaction):
        await show_rating(interaction)

    async def archive_button(self, interaction: discord.Interaction):
        await show_archive(interaction)

    async def delete_button(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🗑️ Удаление задачи",
            description="Выберите задачу для удаления (доступно только для автора или администратора):",
            color=discord.Color.red()
        )
        view = TaskSelectView("delete", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def clear_button(self, interaction: discord.Interaction):
        """Кнопка очистки - доступна только админам"""
        if not has_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав на очистку. Только администраторы и разработчики могут использовать эту функцию.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🧹 Очистка данных",
            description="Выберите тип данных для очистки из списка ниже.\n\n"
                        "⚠️ **ВНИМАНИЕ!** Это действие необратимо!\n"
                        "После подтверждения данные будут удалены навсегда.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Доступные типы очистки:",
            value=(
                "🏆 **Очистить рейтинг** - удалить всю статистику участников\n"
                "📋 **Очистить активные задачи** - удалить все открытые и в работе задачи\n"
                "📦 **Очистить архив** - удалить все завершенные задачи"
            ),
            inline=False
        )

        view = ClearView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def correction_button(self, interaction: discord.Interaction):
        """Кнопка коррекции рейтинга"""
        # Проверка прав
        if not has_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав на коррекцию рейтинга.",
                ephemeral=True
            )
            return

        # Получаем список участников
        participants = db.fetch_all('''
            SELECT user_id, user_name, completed_tasks
            FROM participants
            ORDER BY completed_tasks DESC
        ''')

        if not participants:
            await interaction.response.send_message(
                "❌ Нет участников для коррекции рейтинга.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📊 Коррекция рейтинга",
            description="Выберите пользователя для изменения рейтинга.",
            color=discord.Color.blue()
        )

        view = RatingCorrectionSelectView(participants)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class RatingCorrectionSelect(Select):
    """Выпадающий список для выбора пользователя"""

    def __init__(self, participants: List[dict]):
        options = []
        for p in participants:
            name = p['user_name'][:50]
            options.append(discord.SelectOption(
                label=f"{name} ({p['completed_tasks']})",
                value=p['user_id'],
                description=f"Текущий рейтинг: {p['completed_tasks']}",
                emoji="🏆"
            ))

        super().__init__(
            placeholder="👤 Выберите пользователя...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.participants = {p['user_id']: p for p in participants}

    async def callback(self, interaction: discord.Interaction):
        user_id = self.values[0]
        participant = self.participants.get(user_id)

        if not participant:
            await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)
            return

        modal = RatingCorrectionModal(user_id, participant['user_name'], participant['completed_tasks'])
        await interaction.response.send_modal(modal)


class RatingCorrectionSelectView(View):
    """View с выпадающим списком"""

    def __init__(self, participants: List[dict]):
        super().__init__(timeout=60)
        self.add_item(RatingCorrectionSelect(participants))

# ============== БОТ ==============
class SlashClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=os.getenv("GUILD"))
        self.tree.clear_commands(guild=guild)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.add_view(PersistentTaskView("placeholder"))
        await self._restore_views()

    async def _restore_views(self):
        tasks = db.fetch_all('SELECT * FROM tasks WHERE status IN ("open", "in_progress", "pending_approval")')
        for task in tasks:
            if task['channel_id'] and task['message_id']:
                try:
                    self.add_view(PersistentTaskView(task['id']), message_id=int(task['message_id']))
                except Exception as e:
                    error_logger.error(f"Error restoring view: {e}")


bot = SlashClient()


@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    action_logger.info(f'Bot {bot.user} started!')


# ============== СЛЭШ-КОМАНДЫ ==============
@bot.tree.command(name="menu", description="Показать меню")
async def menu(interaction: discord.Interaction):
    if not has_permission(interaction):
        await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        return
    embed = discord.Embed(title="📋 Управление задачами", description="Используйте кнопки:", color=discord.Color.blue())
    embed.add_field(name="Доступные действия:", value="**➕ Добавить** - /add\n**📋 Список** - /list\n**🏆 Рейтинг** - /rating\n**🗑️ Удалить** - в меню", inline=False)
    await interaction.response.send_message(embed=embed, view=TaskMenuView(interaction.user.id), ephemeral=True)


@bot.tree.command(name="add", description="Добавить задачу")
async def add(interaction: discord.Interaction):
    await interaction.response.send_modal(TaskDescriptionModal())


@bot.tree.command(name="list", description="Список задач")
async def task_list(interaction: discord.Interaction):
    await show_task_list(interaction)


@bot.tree.command(name="rating", description="Рейтинг")
async def rating(interaction: discord.Interaction):
    await show_rating(interaction)


@bot.tree.command(name="ping", description="Пинг")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)


bot.run(os.getenv("DISCORD_TOKEN"))