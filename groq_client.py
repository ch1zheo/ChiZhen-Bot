# groq_client.py - Асинхронный клиент для обращения к Groq API
# (эндпоинт chat/completions, OpenAI-совместимый формат).

# Используется aiohttp для неблокирующих HTTP-запросов, чтобы бот
# не "зависал" на время ожидания ответа от нейросети.

import logging
from typing import List, Dict, Optional

import aiohttp

from config import (
    GROQ_API_KEY,
    GROQ_API_URL,
    GROQ_MODEL,
    MAX_TOKENS,
    TEMPERATURE,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# Таймаут на весь запрос к Groq API.
# Разбит на составляющие, чтобы не зависнуть навечно при обрыве соединения.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=10)

class GroqAPIError(Exception):
    """Базовое исключение для всех ошибок при обращении к Groq API."""
    pass

class GroqRateLimitError(GroqAPIError):
    """Исключение для случая превышения лимита запросов."""
    pass

class GroqTimeoutError(GroqAPIError):
    """Исключение для случая, когда запрос к Groq не успел выполниться вовремя."""
    pass

async def get_groq_response(history: List[Dict[str, str]], user_name: Optional[str] = None) -> str:
    """Отправляет историю диалога в Groq API и возвращает текст ответа модели."""

    # Если имя пользователя известно - добавляем его к системному промпту
    # отдельным абзацем. Делаем это здесь (а не храним в config.py), т.к.
    # системный промпт общий для всех, а имя это персональное для конкретного chat_id.
    system_content = SYSTEM_PROMPT
    if user_name:
        system_content += (
            f"\n\nПользователя, с которым ты сейчас общаешься, зовут {user_name}. "
            f"Обращайся к нему по имени естественно и уместно (не в каждом "
            f"сообщении и не навязчиво), например, в приветствии или когда "
            f"это подчёркивает персональное обращение."
            f"Обязательно обращайся к нему на Вы."
        )

    # Собираем полный список сообщений: системный промпт + история диалога
    messages = [{"role": "system", "content": system_content}, *history]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }

    # Далее - обработка разных ошибок, даём информацию явно, чтобы дать пользователю
    # понятное сообщение об ошибке, а не голый traceback.
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError) as parse_error:
                        logger.error("Неожиданный формат ответа Groq: %s", data)
                        raise GroqAPIError("Groq вернул ответ в неожиданном формате") from parse_error
                    return content.strip()

                elif response.status == 429:
                    logger.warning("Groq API: 429 (Превышен лимит запросов)")
                    raise GroqRateLimitError(
                        "Превышен лимит запросов к Groq API. Попробуйте немного позже."
                    )

                elif response.status == 401:
                    logger.error("Groq API: 401 (Неверный API-ключ)")
                    raise GroqAPIError("Неверный ключ Groq API. Проверьте GROQ_API_KEY в .env.")

                else:
                    error_text = await response.text()
                    logger.error("Groq API вернул ошибку %s: %s", response.status, error_text)
                    raise GroqAPIError(f"Groq API вернул ошибку (код {response.status})")

    except aiohttp.ServerTimeoutError as e:
        logger.error("Таймаут при обращении к Groq API: %s", e)
        raise GroqTimeoutError("Groq API не ответил вовремя. Попробуйте ещё раз.") from e

    except TimeoutError as e:
        # На случай, если сработает общий таймаут aiohttp.ClientTimeout
        logger.error("Таймаут при обращении к Groq API: %s", e)
        raise GroqTimeoutError("Groq API не ответил вовремя. Попробуйте ещё раз.") from e

    except aiohttp.ClientError as e:
        # Любые прочие сетевые ошибки (обрыв соединения, DNS и т.д.)
        logger.error("Сетевая ошибка при обращении к Groq API: %s", e)
        raise GroqAPIError("Не удалось связаться с Groq API. Проверьте подключение к интернету.") from e