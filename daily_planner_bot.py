import asyncio
import logging
import sqlite3
import aiosqlite
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

# Настройка логирования
logging.basicConfig(level=logging.INFO)
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

# Класс для работы с базой данных SQLite
class Database:
    def __init__(self, db_name='reminders.db'):
        self.db_name = db_name
    
    async def init_db(self):
        """Инициализация базы данных"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    task TEXT NOT NULL,
                    reminder_time DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_completed BOOLEAN DEFAULT 0
                )
            ''')
            await db.commit()
            logger.info("База данных инициализирована")
    
    async def add_reminder(self, user_id: int, task: str, reminder_time: str):
        """Добавление нового напоминания"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'INSERT INTO reminders (user_id, task, reminder_time) VALUES (?, ?, ?)',
                (user_id, task, reminder_time)
            )
            await db.commit()
            logger.info(f"Добавлено напоминание для пользователя {user_id}")
    
    async def get_user_reminders(self, user_id: int):
        """Получение всех напоминаний пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                'SELECT id, task, reminder_time, is_completed FROM reminders WHERE user_id = ? ORDER BY reminder_time',
                (user_id,)
            )
            return await cursor.fetchall()
    
    async def get_pending_reminders(self):
        """Получение ожидающих напоминаний (в течение следующих 5 минут)"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                '''SELECT id, user_id, task, reminder_time FROM reminders 
                   WHERE is_completed = 0 AND reminder_time <= datetime("now", "+5 minutes") 
                   ORDER BY reminder_time''',
            )
            return await cursor.fetchall()
    
    async def mark_as_completed(self, reminder_id: int):
        """Пометка напоминания как выполненного"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'UPDATE reminders SET is_completed = 1 WHERE id = ?',
                (reminder_id,)
            )
            await db.commit()
            logger.info(f"Напоминание {reminder_id} отмечено как выполненное")
    
    async def delete_reminder(self, reminder_id: int, user_id: int):
        """Удаление напоминания"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'DELETE FROM reminders WHERE id = ? AND user_id = ?',
                (reminder_id, user_id)
            )
            await db.commit()
            logger.info(f"Удалено напоминание {reminder_id} пользователя {user_id}")

# Инициализация базы данных
db = Database()

# Функции для создания клавиатур
def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Добавить задачу"), KeyboardButton(text="📋 Мои задачи")],
            [KeyboardButton(text="✅ Выполнено"), KeyboardButton(text="🗑 Удалить задачу")],
            [KeyboardButton(text="⏰ Ближайшие напоминания")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_time_keyboard():
    """Клавиатура для выбора времени"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Через 1 час", callback_data="time_1h"),
                InlineKeyboardButton(text="Через 3 часа", callback_data="time_3h")
            ],
            [
                InlineKeyboardButton(text="Завтра в это время", callback_data="time_tomorrow"),
                InlineKeyboardButton(text="Через неделю", callback_data="time_week")
            ],
            [
                InlineKeyboardButton(text="Через 30 минут", callback_data="time_30min"),
                InlineKeyboardButton(text="Через 2 часа", callback_data="time_2h")
            ],
            [
                InlineKeyboardButton(text="Указать вручную", callback_data="time_custom")
            ]
        ]
    )
    return keyboard

def get_yes_no_keyboard():
    """Клавиатура да/нет"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data="yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data="no")
            ]
        ]
    )
    return keyboard

# Функция для парсинга времени из текста
def parse_time_from_text(time_text: str):
    """Парсинг времени из текста пользователя"""
    time_text = time_text.lower().strip()
    now = datetime.now()
    
    # Проверка стандартных форматов
    patterns = [
        (r'^(\d{1,2}):(\d{2})$', lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)))),
        (r'^через (\d+) минут[уы]?$', lambda m: now + timedelta(minutes=int(m.group(1)))),
        (r'^через (\d+) час[аов]?$', lambda m: now + timedelta(hours=int(m.group(1)))),
        (r'^через (\d+) д[еья][йнь]?$', lambda m: now + timedelta(days=int(m.group(1)))),
        (r'^завтра (\d{1,2}):(\d{2})$', lambda m: (now + timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)))),
    ]
    
    for pattern, func in patterns:
        match = re.match(pattern, time_text)
        if match:
            result_time = func(match)
            # Если время уже прошло сегодня, переносим на завтра
            if result_time <= now and pattern == r'^(\d{1,2}):(\d{2})$':
                result_time += timedelta(days=1)
            return result_time
    
    # Проверка формата "дд.мм.гггг чч:мм"
    date_pattern = r'^(\d{1,2})\.(\d{1,2})\.(\d{4}) (\d{1,2}):(\d{2})$'
    match = re.match(date_pattern, time_text)
    if match:
        try:
            day, month, year, hour, minute = map(int, match.groups())
            return datetime(year, month, day, hour, minute)
        except ValueError:
            return None
    
    # Проверка ключевых слов
    keyword_mapping = {
        'через час': now + timedelta(hours=1),
        'через 2 часа': now + timedelta(hours=2),
        'через 3 часа': now + timedelta(hours=3),
        'через 30 минут': now + timedelta(minutes=30),
        'через 15 минут': now + timedelta(minutes=15),
        'завтра': now + timedelta(days=1),
        'послезавтра': now + timedelta(days=2),
        'через неделю': now + timedelta(weeks=1),
    }
    
    if time_text in keyword_mapping:
        return keyword_mapping[time_text]
    
    return None

# Команда /start
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await db.init_db()
    await message.answer(
        "👋 Привет! Я бот для напоминаний о задачах.\n\n"
        "Что я умею:\n"
        "• Добавлять задачи с напоминаниями\n"
        "• Показывать все ваши задачи\n"
        "• Отмечать задачи как выполненные\n"
        "• Удалять задачи\n\n"
        "Используйте кнопки ниже или команды:\n"
        "/add - добавить задачу\n"
        "/list - список задач\n"
        "/help - помощь",
        reply_markup=get_main_keyboard()
    )

# Команда /help
@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "📚 Справка по использованию бота:\n\n"
        "1. Чтобы добавить задачу:\n"
        "   - Нажмите '📝 Добавить задачу' или напишите /add\n"
        "   - Введите описание задачи\n"
        "   - Выберите или укажите время напоминания\n\n"
        "2. Форматы времени:\n"
        "   - '14:30' - сегодня в указанное время\n"
        "   - 'завтра 14:30'\n"
        "   - '31.12.2024 14:30'\n"
        "   - 'через 2 часа'\n"
        "   - 'через 30 минут'\n"
        "   - 'через 3 дня'\n\n"
        "3. Просмотр задач:\n"
        "   - '📋 Мои задачи' или /list - все задачи\n"
        "   - '⏰ Ближайшие напоминания' - задачи на ближайшее время\n\n"
        "4. Управление задачами:\n"
        "   - '✅ Выполнено' - отметить как выполненное\n"
        "   - '🗑 Удалить задачу' - удалить задачу\n\n"
        "5. Другие команды:\n"
        "   - /today - задачи на сегодня\n"
        "   - /week - задачи на неделю\n"
        "   - /clear - удалить все выполненные задачи",
        reply_markup=get_main_keyboard()
    )

# Команда /add
@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    """Обработчик команды /add"""
    await state.set_state(ReminderStates.waiting_for_task)
    await message.answer("Введите описание задачи:")

# Обработчик кнопки "Добавить задачу"
@router.message(lambda message: message.text == "📝 Добавить задачу")
async def add_task_start(message: Message, state: FSMContext):
    """Начало добавления задачи"""
    await state.set_state(ReminderStates.waiting_for_task)
    await message.answer("Введите описание задачи:")

# Получение описания задачи
@router.message(ReminderStates.waiting_for_task)
async def process_task_description(message: Message, state: FSMContext):
    """Обработка описания задачи"""
    await state.update_data(task=message.text)
    await state.set_state(ReminderStates.waiting_for_time)
    await message.answer(
        "Выберите время напоминания или введите его вручную:\n\n"
        "Примеры форматов:\n"
        "• 14:30\n"
        "• завтра 14:30\n"
        "• через 2 часа\n"
        "• через 30 минут\n"
        "• 31.12.2024 14:30",
        reply_markup=get_time_keyboard()
    )

# Обработка выбора времени через кнопки
@router.callback_query(lambda c: c.data.startswith('time_'))
async def process_time_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени через inline-кнопки"""
    user_data = await state.get_data()
    task = user_data['task']
    user_id = callback.from_user.id
    
    time_data = callback.data
    now = datetime.now()
    
    # Маппинг callback_data на временные интервалы
    time_mapping = {
        "time_1h": timedelta(hours=1),
        "time_2h": timedelta(hours=2),
        "time_3h": timedelta(hours=3),
        "time_30min": timedelta(minutes=30),
        "time_tomorrow": timedelta(days=1),
        "time_week": timedelta(weeks=1),
    }
    
    if time_data in time_mapping:
        reminder_time = now + time_mapping[time_data]
        reminder_time_str = reminder_time.strftime("%Y-%m-%d %H:%M:%S")
        
        await db.add_reminder(user_id, task, reminder_time_str)
        
        await callback.message.answer(
            f"✅ Задача добавлена!\n\n"
            f"📝 Задача: {task}\n"
            f"⏰ Напоминание: {reminder_time.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=get_main_keyboard()
        )
        await state.clear()
    elif time_data == "time_custom":
        await state.set_state(ReminderStates.waiting_for_date)
        await callback.message.answer(
            "Введите время в одном из форматов:\n"
            "• '14:30' - сегодня в это время\n"
            "• 'завтра 14:30'\n"
            "• '31.12.2024 14:30'\n"
            "• 'через 2 часа'\n"
            "• 'через 30 минут'"
        )
    
    await callback.answer()

# Обработка ручного ввода времени
@router.message(ReminderStates.waiting_for_time)
@router.message(ReminderStates.waiting_for_date)
async def process_custom_time(message: Message, state: FSMContext):
    """Обработка ручного ввода времени"""
    user_data = await state.get_data()
    task = user_data['task']
    user_id = message.from_user.id
    
    # Парсим время из текста
    reminder_time = parse_time_from_text(message.text)
    
    if not reminder_time:
        await message.answer(
            "Не удалось распознать время. Попробуйте еще раз.\n\n"
            "Примеры:\n"
            "• 14:30\n"
            "• завтра 14:30\n"
            "• через 2 часа\n"
            "• через 30 минут\n"
            "• 31.12.2024 14:30"
        )
        return
    
    # Если время в прошлом (для формата ЧЧ:ММ)
    if reminder_time <= datetime.now() and re.match(r'^\d{1,2}:\d{2}$', message.text):
        reminder_time += timedelta(days=1)
    
    reminder_time_str = reminder_time.strftime("%Y-%m-%d %H:%M:%S")
    
    await db.add_reminder(user_id, task, reminder_time_str)
    
    await message.answer(
        f"✅ Задача добавлена!\n\n"
        f"📝 Задача: {task}\n"
        f"⏰ Напоминание: {reminder_time.strftime('%d.%m.%Y %H:%M')}",
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
        await message.answer("У вас пока нет задач.", reply_markup=get_main_keyboard())
        return
    
    response = "📋 Ваши задачи:\n\n"
    for rem_id, task, time_str, completed in reminders:
        status = "✅" if completed else "⏳"
        try:
            time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            formatted_time = time_obj.strftime("%d.%m.%Y %H:%M")
            
            # Добавляем информацию о просрочке
            now = datetime.now()
            if not completed and time_obj < now:
                status = "🚨"
                time_difference = now - time_obj
                days = time_difference.days
                hours = time_difference.seconds // 3600
                response += f"{status} *{task}*\n"
                response += f"⏰ {formatted_time} (просрочено на {days}д {hours}ч)\n"
            else:
                response += f"{status} *{task}*\n"
                response += f"⏰ {formatted_time}\n"
            
            response += f"📌 ID: `{rem_id}`\n\n"
        except ValueError:
            response += f"{status} *{task}*\n"
            response += f"⏰ {time_str}\n"
            response += f"📌 ID: `{rem_id}`\n\n"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Кнопка "Ближайшие напоминания"
@router.message(lambda message: message.text == "⏰ Ближайшие напоминания")
async def show_upcoming_tasks(message: Message):
    """Показ ближайших напоминаний"""
    reminders = await db.get_user_reminders(message.from_user.id)
    now = datetime.now()
    
    upcoming = []
    for rem in reminders:
        rem_id, task, time_str, completed = rem
        if completed:
            continue
            
        try:
            rem_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            if rem_time >= now and rem_time <= now + timedelta(days=1):
                upcoming.append((rem_id, task, time_str, completed, rem_time))
        except ValueError:
            continue
    
    if not upcoming:
        await message.answer("На ближайшие 24 часа напоминаний нет.", reply_markup=get_main_keyboard())
        return
    
    # Сортируем по времени
    upcoming.sort(key=lambda x: x[4])
    
    response = "⏰ Ближайшие напоминания (24 часа):\n\n"
    for rem_id, task, time_str, completed, rem_time in upcoming:
        time_left = rem_time - now
        hours = int(time_left.total_seconds() // 3600)
        minutes = int((time_left.total_seconds() % 3600) // 60)
        
        response += f"📝 *{task}*\n"
        if hours > 0:
            response += f"⏰ Через {hours}ч {minutes}м\n"
        else:
            response += f"⏰ Через {minutes} минут\n"
        response += f"🕐 {rem_time.strftime('%d.%m.%Y %H:%M')}\n"
        response += f"📌 ID: `{rem_id}`\n\n"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Команда /today
@router.message(Command("today"))
async def show_today_tasks(message: Message):
    """Показ задач на сегодня"""
    reminders = await db.get_user_reminders(message.from_user.id)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    today_tasks = []
    for rem in reminders:
        rem_id, task, time_str, completed = rem
        try:
            rem_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            if today_start <= rem_time < today_end:
                today_tasks.append((rem_id, task, rem_time, completed))
        except ValueError:
            continue
    
    if not today_tasks:
        await message.answer("На сегодня задач нет.", reply_markup=get_main_keyboard())
        return
    
    response = "📅 Задачи на сегодня:\n\n"
    for rem_id, task, rem_time, completed in today_tasks:
        status = "✅" if completed else "⏳"
        time_str = rem_time.strftime("%H:%M")
        
        response += f"{status} *{task}*\n"
        response += f"⏰ {time_str}\n"
        response += f"📌 ID: `{rem_id}`\n\n"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Команда /week
@router.message(Command("week"))
async def show_week_tasks(message: Message):
    """Показ задач на неделю"""
    reminders = await db.get_user_reminders(message.from_user.id)
    now = datetime.now()
    week_end = now + timedelta(days=7)
    
    week_tasks = []
    for rem in reminders:
        rem_id, task, time_str, completed = rem
        if completed:
            continue
            
        try:
            rem_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            if now <= rem_time < week_end:
                week_tasks.append((rem_id, task, rem_time, completed))
        except ValueError:
            continue
    
    if not week_tasks:
        await message.answer("На ближайшую неделю задач нет.", reply_markup=get_main_keyboard())
        return
    
    # Группируем по дням
    tasks_by_day = {}
    for rem_id, task, rem_time, completed in week_tasks:
        day_str = rem_time.strftime("%d.%m.%Y")
        if day_str not in tasks_by_day:
            tasks_by_day[day_str] = []
        tasks_by_day[day_str].append((rem_id, task, rem_time.strftime("%H:%M"), completed))
    
    response = "📅 Задачи на неделю:\n\n"
    for day, tasks in sorted(tasks_by_day.items()):
        response += f"📌 *{day}*:\n"
        for rem_id, task, time_str, completed in tasks:
            status = "✅" if completed else "⏳"
            response += f"  {status} {task} - {time_str} (ID: `{rem_id}`)\n"
        response += "\n"
    
    await message.answer(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Кнопка "Выполнено" и обработка ID задач
@router.message(lambda message: message.text == "✅ Выполнено")
async def mark_completed_start(message: Message):
    """Начало процесса отметки задачи как выполненной"""
    await message.answer(
        "Введите ID задачи, которую хотите отметить как выполненную:\n"
        "(ID можно увидеть в списке задач)\n\n"
        "Или отправьте несколько ID через пробел",
        reply_markup=get_main_keyboard()
    )

# Кнопка "Удалить задачу" и обработка ID задач
@router.message(lambda message: message.text == "🗑 Удалить задачу")
async def delete_task_start(message: Message):
    """Начало процесса удаления задачи"""
    await message.answer(
        "Введите ID задачи, которую хотите удалить:\n"
        "(ID можно увидеть в списке задач)\n\n"
        "Или отправьте несколько ID через пробел\n"
        "Для удаления всех выполненных задач напишите 'все выполненные'",
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
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, удалить", callback_data="clear_all_completed"),
                    InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_clear")
                ]
            ]
        )
        await message.answer(
            "Вы уверены, что хотите удалить ВСЕ выполненные задачи?",
            reply_markup=keyboard
        )
        return
    
    # Разделяем ввод на отдельные ID
    task_ids = []
    for part in text.split():
        if part.isdigit():
            task_ids.append(int(part))
    
    if not task_ids:
        await message.answer("ID задач не найдены. Введите числа.", reply_markup=get_main_keyboard())
        return
    
    # Получаем все задачи пользователя для проверки
    all_reminders = await db.get_user_reminders(user_id)
    user_task_ids = {rem[0] for rem in all_reminders}
    
    # Проверяем, какие ID принадлежат пользователю
    valid_ids = [tid for tid in task_ids if tid in user_task_ids]
    
    if not valid_ids:
        await message.answer("Задачи с такими ID не найдены или не принадлежат вам.", reply_markup=get_main_keyboard())
        return
    
    # Создаем клавиатуру для выбора действия
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отметить выполненными", callback_data=f"complete_{','.join(map(str, valid_ids))}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{','.join(map(str, valid_ids))}")
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
            ]
        ]
    )
    
    await message.answer(
        f"Найдено {len(valid_ids)} задач с ID: {', '.join(map(str, valid_ids))}\n"
        f"Что вы хотите сделать?",
        reply_markup=keyboard
    )

# Обработка callback для действий с задачами
@router.callback_query(lambda c: c.data.startswith(('complete_', 'delete_', 'clear_all_completed', 'cancel_clear', 'cancel_action')))
async def process_task_action(callback: CallbackQuery):
    """Обработка действий с задачами"""
    action = callback.data
    user_id = callback.from_user.id
    
    if action == "clear_all_completed":
        # Удаление всех выполненных задач
        reminders = await db.get_user_reminders(user_id)
        completed_ids = [rem[0] for rem in reminders if rem[3]]  # rem[3] - is_completed
        
        for rem_id in completed_ids:
            await db.delete_reminder(rem_id, user_id)
        
        await callback.message.answer(f"✅ Удалено {len(completed_ids)} выполненных задач!")
        
    elif action == "cancel_clear":
        await callback.message.answer("❌ Удаление отменено.")
        
    elif action == "cancel_action":
        await callback.message.answer("❌ Действие отменено.")
        
    elif action.startswith("complete_"):
        # Отметка задач как выполненных
        ids_str = action.replace("complete_", "")
        task_ids = [int(tid) for tid in ids_str.split(",") if tid.isdigit()]
        
        for rem_id in task_ids:
            await db.mark_as_completed(rem_id)
        
        await callback.message.answer(f"✅ {len(task_ids)} задач отмечены как выполненные!")
        
    elif action.startswith("delete_"):
        # Удаление задач
        ids_str = action.replace("delete_", "")
        task_ids = [int(tid) for tid in ids_str.split(",") if tid.isdigit()]
        
        for rem_id in task_ids:
            await db.delete_reminder(rem_id, user_id)
        
        await callback.message.answer(f"🗑 {len(task_ids)} задач удалены!")
    
    await callback.answer()

# Команда /clear для удаления выполненных задач
@router.message(Command("clear"))
async def clear_completed_tasks(message: Message):
    """Удаление всех выполненных задач"""
    reminders = await db.get_user_reminders(message.from_user.id)
    completed_count = sum(1 for rem in reminders if rem[3])  # rem[3] - is_completed
    
    if completed_count == 0:
        await message.answer("Нет выполненных задач для удаления.", reply_markup=get_main_keyboard())
        return
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data="clear_all_completed"),
                InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_clear")
            ]
        ]
    )
    
    await message.answer(
        f"Найдено {completed_count} выполненных задач.\n"
        f"Вы уверены, что хотите удалить их все?",
        reply_markup=keyboard
    )

# Функция проверки и отправки напоминаний
async def check_reminders():
    """Фоновая задача для проверки и отправки напоминаний"""
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
                            await bot.send_message(
                                user_id,
                                f"🔔 *Напоминание!*\n\n"
                                f"📝 {task}\n\n"
                                f"Задача была запланирована на {rem_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                                f"Используйте команду /list для просмотра всех задач",
                                parse_mode="Markdown"
                            )
                            
                            # Помечаем задачу как выполненную после отправки напоминания
                            # (или можно создать отдельное поле "напоминание отправлено")
                            await db.mark_as_completed(rem_id)
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
            "Я не понял ваше сообщение. Используйте кнопки или команды:\n"
            "/start - начать работу\n"
            "/help - помощь\n"
            "/add - добавить задачу\n"
            "/list - список задач",
            reply_markup=get_main_keyboard()
        )

# Запуск бота
async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота...")
    
    # Инициализация базы данных
    await db.init_db()
    
    # Запуск фоновой задачи проверки напоминаний
    asyncio.create_task(check_reminders())
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Проверка наличия токена
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА_ЗДЕСЬ":
        print("=" * 60)
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
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Бот остановлен")