import logging
import asyncio
import json
import os

from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.client.bot import DefaultBotProperties
from dotenv import load_dotenv

# ===== НАСТРОЙКИ =====
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")        # <-- Токен бота
DATA_FILE = 'tasks_data.json'      # Имя файла, где будут храниться задачи

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(level=logging.INFO) # Выводим служебную информацию в консоль

# ===== СОЗДАНИЕ ОБЪЕКТОВ ДЛЯ БОТА =====
# Здесь мы создаём объект бота и указываем, чтобы все сообщения поддерживали HTML-разметку
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher() # Диспетчер — связывает сообщения пользователей и наши функции

# ===== ФУНКЦИИ ДЛЯ СОХРАНЕНИЯ И ЗАГРУЗКИ ЗАДАЧ =====

def load_tasks():
    """Загружает задачи из файла при запуске бота."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)   # Читаем и преобразуем из JSON в Python-словарь
    return {}

def save_tasks(tasks):
    """Сохраняет все задачи в файл после любого изменения."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2) # Сохраняем красиво и в юникоде

# Глобальная переменная — тут все задачи пользователей
user_tasks = load_tasks()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def parse_deadline(args):
    """
    Находит в списке аргументов дату в формате 'дд.мм.гггг чч:мм' или только дату.
    Возвращает datetime и список оставшихся аргументов.
    """
    for i in range(len(args)):
        try:
            # Пробуем найти дату и время
            dt = datetime.strptime(' '.join(args[i:i+2]), "%d.%m.%Y %H:%M")
            return dt, args[:i] + args[i+2:]
        except:
            pass
        try:
            # Пробуем найти только дату
            dt = datetime.strptime(args[i], "%d.%m.%Y")
            return dt, args[:i] + args[i+1:]
        except:
            pass
    return None, args # Если не нашли, возвращаем None

def format_task(idx, t):
    """
    Красиво оформляет задачу для вывода пользователю.
    idx — номер задачи, t — словарь с данными по задаче.
    """
    status = "✅" if t.get('done', False) else "❌"    # Статус задачи (выполнена/не выполнена)
    # Значок приоритета
    prio = {"low": "🟢", "normal": "🟡", "high": "🔴"}.get(t.get('priority', 'normal'), "🟡")
    # Строка с дедлайном, если он есть
    deadline = t.get('deadline')
    deadline_str = ""
    if deadline:
        try:
            d = datetime.fromisoformat(deadline)
            deadline_str = f"\n      <i>⏰ {d.strftime('%d.%m.%Y %H:%M')}</i>"
        except:
            pass
    return f"<b>{idx}.</b> {prio} {t['task']}{deadline_str} {status}"

def sort_tasks(tasks):
    """
    Сортировка задач: сначала невыполненные, потом по дедлайну, потом по приоритету.
    """
    def key(t):
        done = t.get('done', False)
        deadline = t.get('deadline')
        if deadline:
            deadline_dt = datetime.fromisoformat(deadline)
        else:
            deadline_dt = datetime(2100,1,1) # Если дедлайна нет — ставим "далёкое будущее"
        prio = {"high": 0, "normal": 1, "low": 2}
        return (done, deadline_dt, prio.get(t.get('priority', 'normal'), 1))
    return sorted(tasks, key=key)

def find_task(user_id, num):
    """
    Возвращает задачу по номеру (или None, если некорректный номер).
    """
    tasks = user_tasks.get(str(user_id), [])
    if 1 <= num <= len(tasks):
        return tasks[num-1]
    else:
        return None

async def send_reminder(user_id, idx, t):
    """
    Отправляет напоминание пользователю о задаче.
    """
    deadline = t.get('deadline')
    if deadline:
        d = datetime.fromisoformat(deadline)
        await bot.send_message(
            user_id,
            f"⏰ <b>Напоминание!</b>\nЗадача №{idx}: <b>{t['task']}</b>\n"
            f"Срок: {d.strftime('%d.%m.%Y %H:%M')}"
        )

# ====== ФОНОВАЯ ПРОВЕРКА ДЕДЛАЙНОВ И НАПОМИНАНИЙ ======

async def reminders_loop():
    """
    Фоновая задача — каждую минуту проверяет все задачи всех пользователей
    и шлёт напоминание, если осталось 30 минут до дедлайна.
    """
    while True:
        now = datetime.now()
        for user_id, tasks in user_tasks.items():
            for idx, t in enumerate(tasks, 1):
                # Напоминаем только если задача не выполнена, дедлайн есть и напоминание ещё не отправлено
                if not t.get('done', False) and t.get('deadline') and not t.get('reminded', False):
                    d = datetime.fromisoformat(t['deadline'])
                    if now + timedelta(minutes=30) >= d > now:
                        await send_reminder(user_id, idx, t)
                        t['reminded'] = True # Помечаем, что напоминание уже отправлено
                        save_tasks(user_tasks)
        await asyncio.sleep(60) # Проверяем каждую минуту

# ====== КОМАНДЫ БОТА ======

@dp.message(Command(commands=["start", "help"]))
async def send_welcome(message: Message):
    """
    Отправляет справку о командах.
    """
    text = (
        "<b>Я бот для задач с дедлайнами и напоминаниями!</b>\n"
        "<b>Доступные команды:</b>\n"
        "/add &lt;задача&gt; [дд.мм.гггг чч:мм] [low|normal|high] — добавить задачу (можно без даты и приоритета)\n"
        "/list — список задач\n"
        "/done &lt;номер&gt; — отметить выполненной\n"
        "/delete &lt;номер&gt; — удалить задачу\n"
        "/edit &lt;номер&gt; &lt;новый текст&gt; — изменить текст задачи\n"
        "/deadline &lt;номер&gt; &lt;дата/время&gt; — изменить дедлайн\n"
        "/priority &lt;номер&gt; &lt;low|normal|high&gt; — изменить приоритет\n"
        "/search &lt;текст&gt; — найти задачи\n"
        "/clear — очистить все задачи\n"
        "/help — справка"
    )
    await message.answer(text)

@dp.message(Command(commands=["add"]))
async def add_task(message: Message):
    """
    Добавляет новую задачу.
    Возможные параметры: текст, дедлайн (опционально), приоритет (опционально).
    """
    args = message.text.partition(' ')[2].strip()
    if not args:
        await message.answer("Пример: /add купить хлеб 10.06.2026 20:00 high")
        return
    arg_list = args.split()
    # Пытаемся найти дату/время
    deadline, arg_list = parse_deadline(arg_list)
    # Пытаемся найти приоритет в конце
    priority = 'normal'
    if arg_list and arg_list[-1] in ['low', 'normal', 'high']:
        priority = arg_list[-1]
        arg_list = arg_list[:-1]
    # Всё остальное — текст задачи
    task_text = ' '.join(arg_list)
    if not task_text:
        await message.answer("Укажите текст задачи перед дедлайном и приоритетом.")
        return
    user_id = str(message.from_user.id)
    user_tasks.setdefault(user_id, [])
    # Формируем словарь задачи
    task = {'task': task_text, 'done': False, 'priority': priority}
    if deadline:
        task['deadline'] = deadline.isoformat()
    user_tasks[user_id].append(task)
    save_tasks(user_tasks)
    reply = f"Добавлена задача: <b>{task_text}</b>\nПриоритет: <i>{priority}</i>"
    if deadline:
        reply += f"\nДедлайн: <b>{deadline.strftime('%d.%m.%Y %H:%M')}</b>"
    await message.answer(reply)

@dp.message(Command(commands=["list"]))
async def list_tasks(message: Message):
    """
    Показывает все задачи пользователя: отсортированы по дедлайну, приоритету и статусу.
    """
    user_id = str(message.from_user.id)
    tasks = user_tasks.get(user_id, [])
    if not tasks:
        await message.answer("Список задач пуст.")
        return
    srt = sort_tasks(tasks)
    text_lines = [format_task(i+1, t) for i, t in enumerate(srt)]
    await message.answer('\n'.join(text_lines))

@dp.message(Command(commands=["done"]))
async def done_task(message: Message):
    """
    Отмечает задачу выполненной по номеру.
    """
    arg = message.text.partition(' ')[2].strip()
    user_id = str(message.from_user.id)
    tasks = user_tasks.get(user_id, [])
    if not arg or not arg.isdigit():
        await message.answer("Используй: /done 2")
        return
    num = int(arg)
    if 1 <= num <= len(tasks):
        tasks[num-1]['done'] = True
        save_tasks(user_tasks)
        await message.answer(f"Задача №{num} отмечена как выполненная.")
    else:
        await message.answer("Некорректный номер задачи.")

@dp.message(Command(commands=["delete"]))
async def delete_task(message: Message):
    """
    Удаляет задачу по номеру.
    """
    arg = message.text.partition(' ')[2].strip()
    user_id = str(message.from_user.id)
    tasks = user_tasks.get(user_id, [])
    if not arg or not arg.isdigit():
        await message.answer("Используй: /delete 2")
        return
    num = int(arg)
    if 1 <= num <= len(tasks):
        removed = tasks.pop(num-1)
        save_tasks(user_tasks)
        await message.answer(f"Задача №{num} удалена: {removed['task']}")
    else:
        await message.answer("Некорректный номер задачи.")

@dp.message(Command(commands=["edit"]))
async def edit_task(message: Message):
    """
    Меняет текст задачи по номеру.
    """
    arg = message.text.partition(' ')[2].strip()
    user_id = str(message.from_user.id)
    tasks = user_tasks.get(user_id, [])
    if not arg or not arg.split()[0].isdigit():
        await message.answer("Используй: /edit 2 новый текст задачи")
        return
    parts = arg.split()
    num = int(parts[0])
    new_text = ' '.join(parts[1:])
    if 1 <= num <= len(tasks):
        old_text = tasks[num-1]['task']
        tasks[num-1]['task'] = new_text
        save_tasks(user_tasks)
        await message.answer(f"Задача №{num} изменена:\n<b>Было:</b> {old_text}\n<b>Стало:</b> {new_text}")
    else:
        await message.answer("Некорректный номер задачи.")

@dp.message(Command(commands=["deadline"]))
async def set_deadline(message: Message):
    """
    Устанавливает или меняет дедлайн задачи.
    """
    arg = message.text.partition(' ')[2].strip()
    user_id = str(message.from_user.id)
    tasks = user_tasks.get(user_id, [])
    parts = arg.split()
    if not parts or not parts[0].isdigit():
        await message.answer("Используй: /deadline 2 10.06.2026 21:00")
        return
    num = int(parts[0])
    if 1 <= num <= len(tasks):
        deadline, _ = parse_deadline(parts[1:])
        if deadline:
            tasks[num-1]['deadline'] = deadline.isoformat()
            tasks[num-1]['reminded'] = False # Сбросить напоминание, если дедлайн сменился
            save_tasks(user_tasks)
            await message.answer(f"Дедлайн задачи №{num} установлен: <b>{deadline.strftime('%d.%m.%Y %H:%M')}</b>")
        else:
            await message.answer("Не удалось распознать дату/время.")
    else:
        await message.answer("Некорректный номер задачи.")

@dp.message(Command(commands=["priority"]))
async def set_priority(message: Message):
    """
    Меняет приоритет задачи.
    """
    arg = message.text.partition(' ')[2].strip()
    user_id = str(message.from_user.id)
    tasks = user_tasks.get(user_id, [])
    parts = arg.split()
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in ['low', 'normal', 'high']:
        await message.answer("Используй: /priority 2 high")
        return
    num = int(parts[0])
    if 1 <= num <= len(tasks):
        tasks[num-1]['priority'] = parts[1]
        save_tasks(user_tasks)
        await message.answer(f"Приоритет задачи №{num} изменён на <i>{parts[1]}</i>.")
    else:
        await message.answer("Некорректный номер задачи.")

@dp.message(Command(commands=["clear"]))
async def clear_tasks(message: Message):
    """
    Очищает все задачи пользователя.
    """
    user_id = str(message.from_user.id)
    if user_tasks.get(user_id):
        user_tasks[user_id] = []
        save_tasks(user_tasks)
        await message.answer("Список задач очищен.")
    else:
        await message.answer("Список задач и так пуст.")

@dp.message(Command(commands=["search"]))
async def search_task(message: Message):
    """
    Ищет задачи по ключевым словам.
    """
    arg = message.text.partition(' ')[2].strip().lower()
    user_id = str(message.from_user.id)
    tasks = user_tasks.get(user_id, [])
    if not arg:
        await message.answer("Укажите слово для поиска: /search хлеб")
        return
    found = []
    for i, t in enumerate(tasks, 1):
        if arg in t['task'].lower():
            found.append(format_task(i, t))
    if found:
        await message.answer("Найдено:\n" + '\n'.join(found))
    else:
        await message.answer("По вашему запросу ничего не найдено.")

# ====== ЗАПУСК ======
async def main():
    # Запускаем фоновую задачу для напоминаний
    asyncio.create_task(reminders_loop())
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())