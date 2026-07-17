# handlers.py - Обработчики команд (/start, /clear) и обычных текстовых
# сообщений пользователя для бота ChiZhen.

import logging

from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ChatAction

from config import TELEGRAM_MAX_MESSAGE_LENGTH, TRUNCATE_SUFFIX
from conversation_manager import conversation_manager
from groq_client import get_groq_response, GroqRateLimitError, GroqTimeoutError, GroqAPIError
from safety import check_message_safety

logger = logging.getLogger(__name__)

# Router - способ регистрации хендлеров в aiogram 3.x
# (подключается к Dispatcher в main.py через dp.include_router)
router = Router(name="chizhen_router")

@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Обработчик команды /start. Узнаёт имя пользователя и отправляет персональное первое сообщение."""

    chat_id = message.chat.id

    # Достаём имя пользователя из Telegram-профиля (first_name почти всегда
    # присутствует; на случай отсутствия - падаем обратно на None).
    user_name = message.from_user.first_name if message.from_user else None
    conversation_manager.set_user_name(chat_id, user_name)

    greeting = f"Привет, {user_name}!" if user_name else "Привет!"
    welcome_text = (
        f"{greeting} Я ChiZhen - универсальный ИИ-ассистент. "
        "Просто напишите мне сообщение, и я отвечу. "
        "Используйте /clear, чтобы очистить историю диалога."
    )
    await message.answer(welcome_text)
    logger.info("Пользователь %s (%s) запустил бота (/start)", chat_id, user_name)

@router.message(Command("clear"))
async def handle_clear(message: Message) -> None:
    """Обработчик команды /clear. Очищает историю диалога текущего пользователя."""

    conversation_manager.clear_history(message.chat.id)
    await message.answer("🧹 История очищена!")
    logger.info("История диалога очищена для пользователя %s", message.chat.id)

def _truncate_response(text: str) -> str:
    """
    Обрезает ответ модели, если он превышает лимит длины сообщения Telegram.

    :param text: исходный текст ответа
    :return: текст, безопасный для отправки в Telegram (с учётом суффикса обрезки)
    """
    if len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        return text

    # Оставляем место под суффикс "... (обрезано)", чтобы итоговая длина не превысила лимит Telegram
    cut_length = TELEGRAM_MAX_MESSAGE_LENGTH - len(TRUNCATE_SUFFIX)
    return text[:cut_length] + TRUNCATE_SUFFIX

@router.message(F.text)
async def handle_text_message(message: Message) -> None:
    """
    Обработчик обычных текстовых сообщений пользователя.

    Логика:
    1. Добавляем сообщение пользователя в историю диалога.
    2. Показываем статус "печатает..." пока ждём ответ от Groq.
    3. Отправляем историю в Groq API и получаем ответ.
    4. Сохраняем ответ ассистента в историю.
    5. Отправляем ответ пользователю.
    6. Обрабатываем возможные ошибки.
    """
    chat_id = message.chat.id
    user_text = message.text

    # Обновляем сохранённое имя пользователя на случай, если это первое сообщение без /start, или пользователь сменил имя в Telegram-профиле.
    # Если from_user почему-то отсутствует в апдейте - используем ранее сохранённое имя (fallback), чтобы не терять персонализацию.
    if message.from_user and message.from_user.first_name:
        user_name = message.from_user.first_name
        conversation_manager.set_user_name(chat_id, user_name)
    else:
        user_name = conversation_manager.get_user_name(chat_id)

    # 0. Локальная проверка на джейлбрейк / запрос вредоносного контента.
    # Если сообщение подозрительное - отвечаем отказом и НЕ отправляем его в Groq API вообще (экономим запросы и исключаем риск "уболтать" модель).
    # Само подозрительное сообщение также не сохраняем в историю, чтобы оно не "давило" на контекст следующих запросов.
    refusal = check_message_safety(user_text)
    if refusal is not None:
        await message.answer(refusal)
        return

    # 1. Сохраняем сообщение пользователя в историю
    conversation_manager.add_message(chat_id, "user", user_text)

    # 2. Показываем в чате статус "печатает...", чтобы пользователь видел, что бот обрабатывает запрос, а не завис
    await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # 3. Получаем актуальную историю (уже включает только что добавленное сообщение)
        history = conversation_manager.get_history(chat_id)
        assistant_reply = await get_groq_response(history, user_name=user_name)

        # 4. Сохраняем ответ ассистента в историю для дальнейшего контекста
        conversation_manager.add_message(chat_id, "assistant", assistant_reply)

        # 5. Отправляем (с обрезкой, если ответ слишком длинный)
        safe_reply = _truncate_response(assistant_reply)
        await message.answer(safe_reply)

    except GroqRateLimitError as e:
        logger.warning("Rate limit при обработке сообщения от %s: %s", chat_id, e)
        await message.answer(
            "⏳ Сейчас слишком много запросов к ChiZhen. Пожалуйста, попробуйте чуть позже."
        )

    except GroqTimeoutError as e:
        logger.warning("Таймаут при обработке сообщения от %s: %s", chat_id, e)
        await message.answer(
            "⌛ ChiZhen не ответил вовремя. Попробуйте отправить сообщение ещё раз."
        )

    except GroqAPIError as e:
        logger.error("Ошибка Groq API при обработке сообщения от %s: %s", chat_id, e)
        await message.answer(
            "⚠️ Произошла ошибка при обращении к ChiZhen. Попробуйте немного позже."
        )

    except Exception as e:
        # Ловим любые непредвиденные ошибки, чтобы бот не "падал" целиком
        logger.exception("Непредвиденная ошибка при обработке сообщения от %s: %s", chat_id, e)
        await message.answer(
            "😔 Что-то пошло не так. Попробуйте ещё раз или используйте /clear, если проблема повторяется."
        )
