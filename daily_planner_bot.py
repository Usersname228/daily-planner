import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import re
import threading

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Вставьте сюда ваш токен бота (получите у @BotFather)
BOT_TOKEN = "8077812685:AAGvQEySVbAljwvdN805liSJTBGzWz_uIlw"

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Состояния FSM
class ReminderStates(StatesGroup):
    waiting_for_task = State()
    waiting_for_time = State()
    waiting_for_date = State()

# Класс для работы с базой данных SQLite (синхронная версия)
class Database:
    def __init__(self, db_name='reminders.db'):
        self.db_name = db_name
        self.lock = threading.Lock()
        self.init_db_sync()
    
    def init_db_sync(self):
        """Инициализация базы данных (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    task TEXT NOT NULL,
                    reminder_time DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_completed BOOLEAN DEFAULT 0
                )
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_id ON reminders (user_id)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reminder_time ON reminders (reminder_time)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_is_completed ON reminders (is_completed)
            ''')
            
            conn.commit()
            conn.close()
            logger.info("База данных инициализирована")
    
    async def init_db(self):
        """Асинхронная обёртка для инициализации БД"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.init_db_sync)
    
    def add_reminder_sync(self, user_id: int, task: str, reminder_time: str):
        """Добавление нового напоминания (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                'INSERT INTO reminders (user_id, task, reminder_time) VALUES (?, ?, ?)',
                (user_id, task, reminder_time)
            )
            
            conn.commit()
            conn.close()
            logger.info(f"Добавлено напоминание для пользователя {user_id}")
    
    async def add_reminder(self, user_id: int, task: str, reminder_time: str):
        """Асинхронная обёртка для добавления напоминания"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.add_reminder_sync, user_id, task, reminder_time)
    
    def get_user_reminders_sync(self, user_id: int):
        """Получение всех напоминаний пользователя (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                '''SELECT id, task, reminder_time, is_completed 
                   FROM reminders 
                   WHERE user_id = ? 
                   ORDER BY reminder_time''',
                (user_id,)
            )
            
            result = cursor.fetchall()
            conn.close()
            return result
    
    async def get_user_reminders(self, user_id: int):
        """Асинхронная обёртка для получения напоминаний пользователя"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_user_reminders_sync, user_id)
    
    def get_pending_reminders_sync(self):
        """Получение ожидающих напоминаний (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                '''SELECT id, user_id, task, reminder_time 
                   FROM reminders 
                   WHERE is_completed = 0 
                   AND reminder_time <= datetime('now', '+5 minutes')
                   ORDER BY reminder_time''',
            )
            
            result = cursor.fetchall()
            conn.close()
            return result
    
    async def get_pending_reminders(self):
        """Асинхронная обёртка для получения ожидающих напоминаний"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_pending_reminders_sync)
    
    def mark_as_completed_sync(self, reminder_id: int):
        """Пометка напоминания как выполненного (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                'UPDATE reminders SET is_completed = 1 WHERE id = ?',
                (reminder_id,)
            )
            
            conn.commit()
            conn.close()
            logger.info(f"Напоминание {reminder_id} отмечено как выполненное")
    
    async def mark_as_completed(self, reminder_id: int):
        """Асинхронная обёртка для отметки как выполненного"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.mark_as_completed_sync, reminder_id)
    
    def delete_reminder_sync(self, reminder_id: int, user_id: int):
        """Удаление напоминания (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                'DELETE FROM reminders WHERE id = ? AND user_id = ?',
                (reminder_id, user_id)
            )
            
            conn.commit()
            conn.close()
            logger.info(f"Удалено напоминание {reminder_id} пользователя {user_id}")
    
    async def delete_reminder(self, reminder_id: int, user_id: int):
        """Асинхронная обёртка для удаления напоминания"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.delete_reminder_sync, reminder_id, user_id)
    
    def get_today_tasks_sync(self, user_id: int):
        """Получение задач на сегодня (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                '''SELECT id, task, reminder_time, is_completed 
                   FROM reminders 
                   WHERE user_id = ? 
                   AND date(reminder_time) = date('now')
                   ORDER BY reminder_time''',
                (user_id,)
            )
            
            result = cursor.fetchall()
            conn.close()
            return result
    
    async def get_today_tasks(self, user_id: int):
        """Асинхронная обёртка для получения задач на сегодня"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_today_tasks_sync, user_id)
    
    def get_week_tasks_sync(self, user_id: int):
        """Получение задач на неделю (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                '''SELECT id, task, reminder_time, is_completed 
                   FROM reminders 
                   WHERE user_id = ? 
                   AND date(reminder_time) BETWEEN date('now') AND date('now', '+7 days')
                   ORDER BY reminder_time''',
                (user_id,)
            )
            
            result = cursor.fetchall()
            conn.close()
            return result
    
    async def get_week_tasks(self, user_id: int):
        """Асинхронная обёртка для получения задач на неделю"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_week_tasks_sync, user_id)
    
    def get_completed_count_sync(self, user_id: int):
        """Получение количества выполненных задач (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                '''SELECT COUNT(*) 
                   FROM reminders 
                   WHERE user_id = ? AND is_completed = 1''',
                (user_id,)
            )
            
            result = cursor.fetchone()[0]
            conn.close()
            return result
    
    async def get_completed_count(self, user_id: int):
        """Асинхронная обёртка для получения количества выполненных задач"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_completed_count_sync, user_id)
    
    def delete_all_completed_sync(self, user_id: int):
        """Удаление всех выполненных задач (синхронная)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                'DELETE FROM reminders WHERE user_id = ? AND is_completed = 1',
                (user_id,)
            )
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            logger.info(f"Удалено {deleted_count} выполненных задач пользователя {user_id}")
            return deleted_count
    
    async def delete_all_completed(self, user_id: int):
        """Асинхронная обёртка для удаления всех выполненных задач"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.delete_all_completed_sync, user_id)

# Инициализация базы данных
db = Database()

# Функции для создания клавиатур
def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Добавить задачу"), KeyboardButton(text="📋 Мои задачи")],
            [KeyboardButton(text="✅ Выполнено"), KeyboardButton(text="🗑 Удалить задачу")],
            [KeyboardButton(text="⏰ Ближайшие напоминания"), KeyboardButton(text="📅 Сегодня")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_time_keyboard():
    """Клавиатура для выбора времени"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Через 30 мин", callback_data="time_30min"),
                InlineKeyboardButton(text="Через 1 час", callback_data="time_1h")
            ],
            [
                InlineKeyboardButton(text="Через 3 часа", callback_data="time_3h"),
                InlineKeyboardButton(text="Завтра", callback_data="time_tomorrow")
            ],
            [
                InlineKeyboardButton(text="Через неделю", callback_data="time_week"),
                InlineKeyboardButton(text="Указать время", callback_data="time_custom")
            ]
        ]
    )
    return keyboard

def get_cancel_keyboard():
    """Клавиатура для отмены"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ]
    )
    return keyboard

def get_confirm_keyboard(action: str):
    """Клавиатура подтверждения"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}"),
                InlineKeyboardButton(text="❌ Нет", callback_data="cancel")
            ]
        ]
    )
    return keyboard

# Функция для парсинга времени из текста
def parse_time_from_text(time_text: str):
    """Парсинг времени из текста пользователя"""
    if not time_text:
        return None
    
    time_text = time_text.lower().strip()
    now = datetime.now()
    
    # Проверка стандартных форматов
    patterns = [
        (r'^(\d{1,2}):(\d{2})$', 
         lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)),
        
        (r'^через (\d+) минут[уы]?$', 
         lambda m: now + timedelta(minutes=int(m.group(1)))),
        
        (r'^через (\d+) час[аов]?$', 
         lambda m: now + timedelta(hours=int(m.group(1)))),
        
        (r'^через (\d+) д[еья][йнь]?$', 
         lambda m: now + timedelta(days=int(m.group(1)))),
        
        (r'^завтра[ в]?(\d{1,2})?:?(\d{2})?$', 
         lambda m: handle_tomorrow(m, now)),
        
        (r'^(\d{1,2})\.(\d{1,2})\.(\d{4})[ в]?(\d{1,2})?:?(\d{2})?$', 
         lambda m: handle_full_date(m)),
    ]
    
    for pattern, func in patterns:
        match = re.match(pattern, time_text)
        if match:
            result_time = func(match)
            
            # Если время уже прошло сегодня для формата ЧЧ:ММ, переносим на завтра
            if pattern == r'^(\d{1,2}):(\d{2})$' and result_time <= now:
                result_time += timedelta(days=1)
            
            return result_time
    
    # Проверка ключевых слов
    keyword_mapping = {
        'через 15 минут': now + timedelta(minutes=15),
        'через 30 минут': now + timedelta(minutes=30),
        'через 1 час': now + timedelta(hours=1),
        'через 2 часа': now + timedelta(hours=2),
        'через 3 часа': now + timedelta(hours=3),
        'через 6 часов': now + timedelta(hours=6),
        'через 12 часов': now + timedelta(hours=12),
        'через день': now + timedelta(days=1),
        'через 2 дня': now + timedelta(days=2),
        'через неделю': now + timedelta(weeks=1),
        'завтра': now + timedelta(days=1),
        'послезавтра': now + timedelta(days=2),
        'через месяц': now + timedelta(days=30),
    }
    
    if time_text in keyword_mapping:
        return keyword_mapping[time_text]
    
    return None

def handle_tomorrow(match, now):
    """Обработка времени на завтра"""
    if match.group(1) and match.group(2):
        # Завтра в конкретное время
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    else:
        # Завтра в это же время
        return now + timedelta(days=1)

def handle_full_date(match):
    """Обработка полной даты"""
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    
    if match.group(4) and match.group(5):
        hour, minute = int(match.group(4)), int(match.group(5))
    else:
        hour, minute = 12, 0  # По умолчанию в 12:00
    
    return datetime(year, month, day, hour, minute, 0, 0)

# Команда /start
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await db.init_db()
    await message.answer(
        "👋 Привет! Я бот для напоминаний о задачах.\n\n"
        "📌 *Что я умею:*\n"
        "• Добавлять задачи с напоминаниями\n"
        "• Показывать все ваши задачи\n"
        "• Отмечать задачи как выполненные\n"
        "• Удалять задачи\n"
        "• Показывать задачи на сегодня/неделю\n\n"
        "🎯 *Используйте кнопки ниже или команды:*\n"
        "/add - добавить задачу\n"
        "/list - список задач\n"
        "/today - задачи на сегодня\n"
        "/week - задачи на неделю\n"
        "/help - помощь\n\n"
        "💡 *Подсказка:* Для быстрого добавления задачи используйте кнопку '📝 Добавить задачу'",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# Команда /help
@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = """
📚 *Справка по использованию бота:*

1️⃣ *Добавление задачи:*
   - Нажмите '📝 Добавить задачу' или напишите /add
   - Введите описание задачи
   - Выберите или укажите время напоминания

2️⃣ *Форматы времени:*
   • `14:30` - сегодня в указанное время
   • `завтра 14:30` - завтра в указанное время
   • `31.12.2024 14:30` - конкретная дата и время
   • `через 2 часа` - через указанное время
   • `через 30 минут` - через указанное время
   • `через 3 дня` - через указанное количество дней

3️⃣ *Просмотр задач:*
   • '📋 Мои задачи' или /list - все задачи
   • '📅 Сегодня' или /today - задачи на сегодня
   • /week - задачи на неделю
   • '⏰ Ближайшие напоминания' - задачи на ближайшие 24 часа

4️⃣ *Управление задачами:*
   • '✅ Выполнено' - отметить задачу как выполненную
   • '🗑 Удалить задачу' - удалить задачу
   • /clear - удалить все выполненные задачи

5️⃣ *Работа с ID задач:*
   • ID отображается в списке задач
   • Можно отметить/удалить несколько задач через пробел
   • Пример: `123 456 789`

📌 *Быстрые кнопки времени при добавлении задачи:*
• Через 30 мин • Через 1 час • Через 3 часа
• Завтра • Через неделю
"""
    
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Команда /add
@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    """Обработчик команды /add"""
    await state.set_state(ReminderStates.waiting_for_task)
    await message.answer(
        "Введите описание задачи:",
        reply_markup=get_cancel_keyboard()
    )

# Обработчик кнопки "Добавить задачу"
@router.message(lambda message: message.text == "📝 Добавить задачу")
async def add_task_start(message: Message, state: FSMContext):
    """Начало добавления задачи"""
    await state.set_state(ReminderStates.waiting_for_task)
    await message.answer(
        "Введите описание задачи:",
        reply_markup=get_cancel_keyboard()
    )

# Отмена действий
@router.callback_query(lambda c: c.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    """Отмена текущего действия"""
    await state.clear()
    await callback.message.answer(
        "❌ Действие отменено.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# Получение описания задачи
@router.message(ReminderStates.waiting_for_task)
async def process_task_description(message: Message, state: FSMContext):
    """Обработка описания задачи"""
    if len(message.text) > 500:
        await message.answer("Описание задачи слишком длинное (максимум 500 символов). Введите более короткое описание:")
        return
    
    await state.update_data(task=message.text)
    await state.set_state(ReminderStates.waiting_for_time)
    await message.answer(
        "⏰ *Выберите время напоминания или введите его вручную:*\n\n"
        "📌 *Примеры форматов:*\n"
        "• `14:30` - сегодня в это время\n"
        "• `завтра 14:30`\n"
        "• `через 2 часа`\n"
        "• `через 30 минут`\n"
        "• `31.12.2024 14:30`\n"
        "• `через 3 дня`",
        parse_mode="Markdown",
        reply_markup=get_time_keyboard()
    )

# Обработка выбора времени через кнопки
@router.callback_query(lambda c: c.data.startswith('time_'))
async def process_time_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени через inline-кнопки"""
    user_data = await state.get_data()
    task = user_data.get('task')
    
    if not task:
        await callback.message.answer("Ошибка: не найдено описание задачи. Начните заново.")
        await state.clear()
        await callback.answer()
        return
    
    user_id = callback.from_user.id
    time_data = callback.data
    now = datetime.now()
    
    # Маппинг callback_data на временные интервалы
    time_mapping = {
        "time_30min": timedelta(minutes=30),
        "time_1h": timedelta(hours=1),
        "time_3h": timedelta(hours=3),
        "time_tomorrow": timedelta(days=1),
        "time_week": timedelta(weeks=1),
    }
    
    if time_data in time_mapping:
        reminder_time = now + time_mapping[time_data]
        reminder_time_str = reminder_time.strftime("%Y-%m-%d %H:%M:%S")
        
        await db.add_reminder(user_id, task, reminder_time_str)
        
        await callback.message.answer(
            f"✅ *Задача добавлена!*\n\n"
            f"📝 *Задача:* {task}\n"
            f"⏰ *Напоминание:* {reminder_time.strftime('%d.%m.%Y в %H:%M')}\n\n"
            f"📌 ID задачи будет показан в списке задач.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        await state.clear()
    elif time_data == "time_custom":
        await state.set_state(ReminderStates.waiting_for_date)
        await callback.message.answer(
            "⌨️ *Введите время вручную:*\n\n"
            "📋 *Примеры:*\n"
            "• `14:30` - сегодня в это время\n"
            "• `завтра 14:30`\n"
            "• `через 2 часа`\n"
            "• `через 30 минут`\n"
            "• `31.12.2024 14:30`",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard()
        )
    
    await callback.answer()

# Обработка ручного ввода времени
@router.message(ReminderStates.waiting_for_time)
@router.message(ReminderStates.waiting_for_date)
async def process_custom_time(message: Message, state: FSMContext):
    """Обработка ручного ввода времени"""
    user_data = await state.get_data()
    task = user_data.get('task')
    
    if not task:
        await message.answer("Ошибка: не найдено описание задачи. Начните заново.")
        await state.clear()
        return
    
    user_id = message.from_user.id
    
    # Парсим время из текста
    reminder_time = parse_time_from_text(message.text)
    
    if not reminder_time:
        await message.answer(
            "❌ *Не удалось распознать время.*\n\n"
            "📋 *Попробуйте еще раз. Примеры:*\n"
            "• `14:30`\n"
            "• `завтра 14:30`\n"
            "• `через 2 часа`\n"
            "• `через 30 минут`\n"
            "• `31.12.2024 14:30`",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Если время в прошлом (для формата ЧЧ:ММ)
    if reminder_time <= datetime.now():
        if re.match(r'^\d{1,2}:\d{2}$', message.text.strip()):
            reminder_time += timedelta(days=1)
        else:
            await message.answer(
                "❌ *Нельзя установить напоминание в прошлом.*\n\n"
                "Введите будущее время:",
                reply_markup=get_cancel_keyboard()
            )
            return
    
    reminder_time_str = reminder_time.strftime("%Y-%m-%d %H:%M:%S")
    
    await db.add_reminder(user_id, task, reminder_time_str)
    
    await message.answer(
        f"✅ *Задача добавлена!*\n\n"
        f"📝 *Задача:* {task}\n"
        f"⏰ *Напоминание:* {reminder_time.strftime('%d.%m.%Y в %H:%M')}\n\n"
        f"📌 ID задачи будет показан в списке задач.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )
    await state.clear()

# Команда /list и кнопка "Мои задачи"
@router.message(Command("list"))
@router.message(lambda message: message.text == "📋 Мои задачи")
async def show_tasks(message: Message):
    """Показ всех задач пользователя"""
    reminders = await db.get_user_reminders(message.from_user.id)
    
    if not reminders:
        await message.answer(
            "📭 *У вас пока нет задач.*\n\n"
            "Нажмите '📝 Добавить задачу', чтобы создать первую задачу.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Разделяем на активные и выполненные
    active_tasks = []
    completed_tasks = []
    
    for rem_id, task, time_str, completed in reminders:
        if completed:
            completed_tasks.append((rem_id, task, time_str))
        else:
            active_tasks.append((rem_id, task, time_str))
    
    response = "📋 *Ваши задачи:*\n\n"
    
    if active_tasks:
        response += "🟢 *Активные задачи:*\n"
        for rem_id, task, time_str in active_tasks:
            try:
                time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                formatted_time = time_obj.strftime("%d.%m.%Y %H:%M")
                
                # Добавляем информацию о просрочке
                now = datetime.now()
                if time_obj < now:
                    time_difference = now - time_obj
                    days = time_difference.days
                    hours = time_difference.seconds // 3600
                    minutes = (time_difference.seconds % 3600) // 60
                    
                    if days > 0:
                        response += f"🚨 *{task}*\n"
                        response += f"⏰ {formatted_time} (просрочено на {days}д {hours}ч)\n"
                    else:
                        response += f"⚠️ *{task}*\n"
                        response += f"⏰ {formatted_time} (просрочено на {hours}ч {minutes}м)\n"
                else:
                    time_difference = time_obj - now
                    days = time_difference.days
                    hours = time_difference.seconds // 3600
                    minutes = (time_difference.seconds % 3600) // 60
                    
                    if days > 0:
                        response += f"⏳ *{task}*\n"
                        response += f"⏰ {formatted_time} (через {days}д {hours}ч)\n"
                    elif hours > 0:
                        response += f"⏳ *{task}*\n"
                        response += f"⏰ {formatted_time} (через {hours}ч {minutes}м)\n"
                    else:
                        response += f"⏳ *{task}*\n"
                        response += f"⏰ {formatted_time} (через {minutes}м)\n"
                
                response += f"📌 ID: `{rem_id}`\n\n"
            except ValueError:
                response += f"⏳ *{task}*\n"
                response += f"⏰ {time_str}\n"
                response += f"📌 ID: `{rem_id}`\n\n"
    
    if completed_tasks:
        response += "✅ *Выполненные задачи:*\n"
        for rem_id, task, time_str in completed_tasks:
            try:
                time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                formatted_time = time_obj.strftime("%d.%m.%Y %H:%M")
                response += f"✅ *{task}*\n"
                response += f"⏰ {formatted_time}\n"
                response += f"📌 ID: `{rem_id}`\n\n"
            except ValueError:
                response += f"✅ *{task}*\n"
                response += f"⏰ {time_str}\n"
                response += f"📌 ID: `{rem_id}`\n\n"
    
    response += f"📊 *Всего задач:* {len(reminders)}"
    response += f" (активных: {len(active_tasks)}, выполненных: {len(completed_tasks)})"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Кнопка "Ближайшие напоминания"
@router.message(lambda message: message.text == "⏰ Ближайшие напоминания")
async def show_upcoming_tasks(message: Message):
    """Показ ближайших напоминаний"""
    reminders = await db.get_user_reminders(message.from_user.id)
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    
    upcoming = []
    for rem in reminders:
        rem_id, task, time_str, completed = rem
        if completed:
            continue
        
        try:
            rem_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            if now <= rem_time <= tomorrow:
                upcoming.append((rem_id, task, time_str, completed, rem_time))
        except ValueError:
            continue
    
    if not upcoming:
        await message.answer(
            "⏰ *На ближайшие 24 часа напоминаний нет.*\n\n"
            "Добавьте новые задачи, чтобы получать напоминания.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Сортируем по времени
    upcoming.sort(key=lambda x: x[4])
    
    response = "⏰ *Ближайшие напоминания (24 часа):*\n\n"
    for rem_id, task, time_str, completed, rem_time in upcoming:
        time_left = rem_time - now
        hours = int(time_left.total_seconds() // 3600)
        minutes = int((time_left.total_seconds() % 3600) // 60)
        
        response += f"📝 *{task}*\n"
        
        if hours > 0:
            response += f"⏰ Через {hours}ч {minutes}м\n"
        else:
            response += f"⏰ Через {minutes} минут\n"
        
        response += f"🕐 {rem_time.strftime('%d.%m.%Y в %H:%M')}\n"
        response += f"📌 ID: `{rem_id}`\n\n"
    
    response += f"📊 *Всего напоминаний:* {len(upcoming)}"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Команда /today и кнопка "Сегодня"
@router.message(Command("today"))
@router.message(lambda message: message.text == "📅 Сегодня")
async def show_today_tasks(message: Message):
    """Показ задач на сегодня"""
    today_tasks = await db.get_today_tasks(message.from_user.id)
    
    if not today_tasks:
        await message.answer(
            "📅 *На сегодня задач нет.*\n\n"
            "Добавьте задачи на сегодня, чтобы получать напоминания.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Разделяем на активные и выполненные
    active_tasks = []
    completed_tasks = []
    
    for rem_id, task, time_str, completed in today_tasks:
        if completed:
            completed_tasks.append((rem_id, task, time_str))
        else:
            active_tasks.append((rem_id, task, time_str))
    
    response = "📅 *Задачи на сегодня:*\n\n"
    
    if active_tasks:
        response += "🟢 *Активные задачи:*\n"
        for rem_id, task, time_str in active_tasks:
            try:
                time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                time_str_formatted = time_obj.strftime("%H:%M")
                
                now = datetime.now()
                if time_obj < now:
                    response += f"⚠️ *{task}*\n"
                    response += f"⏰ {time_str_formatted} (просрочено)\n"
                else:
                    time_left = time_obj - now
                    hours = int(time_left.total_seconds() // 3600)
                    minutes = int((time_left.total_seconds() % 3600) // 60)
                    
                    if hours > 0:
                        response += f"⏳ *{task}*\n"
                        response += f"⏰ {time_str_formatted} (через {hours}ч {minutes}м)\n"
                    else:
                        response += f"⏳ *{task}*\n"
                        response += f"⏰ {time_str_formatted} (через {minutes}м)\n"
                
                response += f"📌 ID: `{rem_id}`\n\n"
            except ValueError:
                response += f"⏳ *{task}*\n"
                response += f"⏰ {time_str}\n"
                response += f"📌 ID: `{rem_id}`\n\n"
    
    if completed_tasks:
        response += "✅ *Выполненные задачи:*\n"
        for rem_id, task, time_str in completed_tasks:
            try:
                time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                time_str_formatted = time_obj.strftime("%H:%M")
                response += f"✅ *{task}*\n"
                response += f"⏰ {time_str_formatted}\n"
                response += f"📌 ID: `{rem_id}`\n\n"
            except ValueError:
                response += f"✅ *{task}*\n"
                response += f"⏰ {time_str}\n"
                response += f"📌 ID: `{rem_id}`\n\n"
    
    response += f"📊 *Всего задач на сегодня:* {len(today_tasks)}"
    response += f" (активных: {len(active_tasks)}, выполненных: {len(completed_tasks)})"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Команда /week
@router.message(Command("week"))
async def show_week_tasks(message: Message):
    """Показ задач на неделю"""
    week_tasks = await db.get_week_tasks(message.from_user.id)
    
    if not week_tasks:
        await message.answer(
            "📅 *На ближайшую неделю задач нет.*\n\n"
            "Добавьте задачи, чтобы планировать свою неделю.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Группируем по дням
    tasks_by_day = {}
    for rem_id, task, time_str, completed in week_tasks:
        try:
            time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            day_str = time_obj.strftime("%d.%m.%Y (%A)")
            
            if day_str not in tasks_by_day:
                tasks_by_day[day_str] = []
            
            tasks_by_day[day_str].append((rem_id, task, time_obj.strftime("%H:%M"), completed))
        except ValueError:
            continue
    
    response = "📅 *Задачи на неделю:*\n\n"
    for day, tasks in sorted(tasks_by_day.items()):
        # Сортируем задачи по времени
        tasks.sort(key=lambda x: x[2])
        
        response += f"📌 *{day}:*\n"
        
        for rem_id, task, time_str, completed in tasks:
            status = "✅" if completed else "⏳"
            response += f"  {status} *{task}* - {time_str} (ID: `{rem_id}`)\n"
        
        response += "\n"
    
    response += f"📊 *Всего задач на неделю:* {len(week_tasks)}"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Кнопка "Выполнено" и обработка ID задач
@router.message(lambda message: message.text == "✅ Выполнено")
async def mark_completed_start(message: Message):
    """Начало процесса отметки задачи как выполненной"""
    await message.answer(
        "✅ *Отметить задачу как выполненную*\n\n"
        "📌 *Введите ID задачи:*\n"
        "(ID можно увидеть в списке задач)\n\n"
        "📋 *Можно ввести несколько ID через пробел*\n"
        "Пример: `123 456 789`",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# Кнопка "Удалить задачу" и обработка ID задач
@router.message(lambda message: message.text == "🗑 Удалить задачу")
async def delete_task_start(message: Message):
    """Начало процесса удаления задачи"""
    await message.answer(
        "🗑 *Удалить задачу*\n\n"
        "📌 *Введите ID задачи:*\n"
        "(ID можно увидеть в списке задач)\n\n"
        "📋 *Можно ввести несколько ID через пробел*\n"
        "Пример: `123 456 789`\n\n"
        "🧹 *Для удаления всех выполненных задач напишите:*\n"
        "`все выполненные`",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# Обработка ввода ID задач
@router.message(lambda message: any(char.isdigit() for char in message.text) or 'все выполненные' in message.text.lower())
async def process_task_ids(message: Message):
    """Обработка введенных ID задач"""
    text = message.text.strip()
    user_id = message.from_user.id
    
    # Проверка на удаление всех выполненных задач
    if 'все выполненные' in text.lower():
        completed_count = await db.get_completed_count(user_id)
        
        if completed_count == 0:
            await message.answer(
                "📭 *Нет выполненных задач для удаления.*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            f"⚠️ *Вы уверены, что хотите удалить ВСЕ выполненные задачи?*\n\n"
            f"📊 *Будет удалено задач:* {completed_count}\n\n"
            f"Это действие нельзя отменить!",
            parse_mode="Markdown",
            reply_markup=get_confirm_keyboard("clear_all_completed")
        )
        return
    
    # Разделяем ввод на отдельные ID
    task_ids = []
    for part in text.split():
        if part.isdigit():
            task_ids.append(int(part))
    
    if not task_ids:
        await message.answer(
            "❌ *ID задач не найдены.*\n\n"
            "Введите числа (ID задач).",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Получаем все задачи пользователя для проверки
    all_reminders = await db.get_user_reminders(user_id)
    user_task_ids = {rem[0] for rem in all_reminders}
    
    # Проверяем, какие ID принадлежат пользователю
    valid_ids = [tid for tid in task_ids if tid in user_task_ids]
    
    if not valid_ids:
        await message.answer(
            "❌ *Задачи с такими ID не найдены или не принадлежат вам.*\n\n"
            "Проверьте правильность ввода ID.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Создаем клавиатуру для выбора действия
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отметить выполненными", 
                                   callback_data=f"complete_{','.join(map(str, valid_ids))}"),
                InlineKeyboardButton(text="🗑 Удалить", 
                                   callback_data=f"delete_{','.join(map(str, valid_ids))}")
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
            ]
        ]
    )
    
    await message.answer(
        f"📋 *Найдено задач:* {len(valid_ids)}\n"
        f"📌 *ID задач:* {', '.join(map(str, valid_ids))}\n\n"
        f"*Что вы хотите сделать?*",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# Обработка callback для действий с задачами
@router.callback_query(lambda c: c.data.startswith(('complete_', 'delete_', 'confirm_')))
async def process_task_action(callback: CallbackQuery):
    """Обработка действий с задачами"""
    action = callback.data
    user_id = callback.from_user.id
    
    if action.startswith("complete_"):
        # Отметка задач как выполненных
        ids_str = action.replace("complete_", "")
        task_ids = [int(tid) for tid in ids_str.split(",") if tid.isdigit()]
        
        for rem_id in task_ids:
            await db.mark_as_completed(rem_id)
        
        await callback.message.answer(
            f"✅ *{len(task_ids)} задач отмечены как выполненные!*",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        
    elif action.startswith("delete_"):
        # Удаление задач
        ids_str = action.replace("delete_", "")
        task_ids = [int(tid) for tid in ids_str.split(",") if tid.isdigit()]
        
        for rem_id in task_ids:
            await db.delete_reminder(rem_id, user_id)
        
        await callback.message.answer(
            f"🗑 *{len(task_ids)} задач удалены!*",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        
    elif action == "confirm_clear_all_completed":
        # Удаление всех выполненных задач
        deleted_count = await db.delete_all_completed(user_id)
        
        await callback.message.answer(
            f"🧹 *Удалено {deleted_count} выполненных задач!*",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    await callback.answer()

# Команда /clear для удаления выполненных задач
@router.message(Command("clear"))
async def clear_completed_tasks(message: Message):
    """Удаление всех выполненных задач"""
    completed_count = await db.get_completed_count(message.from_user.id)
    
    if completed_count == 0:
        await message.answer(
            "📭 *Нет выполненных задач для удаления.*",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    await message.answer(
        f"⚠️ *Вы уверены, что хотите удалить ВСЕ выполненные задачи?*\n\n"
        f"📊 *Будет удалено задач:* {completed_count}\n\n"
        f"Это действие нельзя отменить!",
        parse_mode="Markdown",
        reply_markup=get_confirm_keyboard("clear_all_completed")
    )

# Функция проверки и отправки напоминаний
async def check_reminders():
    """Фоновая задача для проверки и отправки напоминаний"""
    logger.info("Запущена фоновая задача проверки напоминаний")
    
    while True:
        try:
            reminders = await db.get_pending_reminders()
            
            for rem_id, user_id, task, reminder_time in reminders:
                try:
                    rem_time = datetime.strptime(reminder_time, "%Y-%m-%d %H:%M:%S")
                    now = datetime.now()
                    
                    # Отправляем напоминание, если время пришло
                    if rem_time <= now:
                        try:
                            # Создаем клавиатуру для быстрого действия
                            keyboard = InlineKeyboardMarkup(
                                inline_keyboard=[
                                    [
                                        InlineKeyboardButton(text="✅ Выполнено", 
                                                           callback_data=f"complete_{rem_id}")
                                    ]
                                ]
                            )
                            
                            await bot.send_message(
                                user_id,
                                f"🔔 *НАПОМИНАНИЕ!*\n\n"
                                f"📝 *Задача:* {task}\n\n"
                                f"⏰ *Было запланировано на:* {rem_time.strftime('%d.%m.%Y в %H:%M')}\n\n"
                                f"Нажмите кнопку ниже, чтобы отметить как выполненное",
                                parse_mode="Markdown",
                                reply_markup=keyboard
                            )
                            
                            logger.info(f"Отправлено напоминание пользователю {user_id}: {task}")
                            
                        except Exception as e:
                            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
                    
                except Exception as e:
                    logger.error(f"Ошибка при обработке напоминания {rem_id}: {e}")
            
            # Проверяем каждые 30 секунд
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Ошибка в check_reminders: {e}")
            await asyncio.sleep(60)

# Обработка неизвестных сообщений
@router.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных сообщений"""
    if message.text:
        await message.answer(
            "🤔 *Я не понял ваше сообщение.*\n\n"
            "🎯 *Используйте кнопки или команды:*\n"
            "/start - начать работу\n"
            "/help - помощь\n"
            "/add - добавить задачу\n"
            "/list - список задач\n"
            "/today - задачи на сегодня\n"
            "/week - задачи на неделю",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

# Запуск бота
async def main():
    """Основная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("Запуск бота для напоминаний о задачах")
    logger.info("=" * 50)
    
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА_ЗДЕСЬ":
        logger.error("Токен бота не установлен!")
        print("\n" + "=" * 60)
        print("ВАЖНО: Замените 'ВАШ_ТОКЕН_БОТА_ЗДЕСЬ' на ваш реальный токен бота!")
        print("=" * 60)
        print("\nКак получить токен:")
        print("1. Откройте Telegram и найдите @BotFather")
        print("2. Отправьте команду /newbot")
        print("3. Следуйте инструкциям для создания бота")
        print("4. Скопируйте полученный токен")
        print("5. Вставьте его в код вместо 'ВАШ_ТОКЕН_БОТА_ЗДЕСЬ'")
        print("\nПример: BOT_TOKEN = '1234567890:ABCdefGHIjklMNOpqrsTUVwxyz'")
        print("=" * 60)
        return
    
    # Запуск фоновой задачи проверки напоминаний
    asyncio.create_task(check_reminders())
    logger.info("Фоновая задача проверки напоминаний запущена")
    
    # Запуск бота
    logger.info("Бот запущен и готов к работе")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")