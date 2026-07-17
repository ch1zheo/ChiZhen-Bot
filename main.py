# main.py - точка входа для бота ChiZhen.

# Здесь настраивается логирование, создаются объекты Bot и Dispatcher,
# подключается роутер с хендлерами и запускается polling.

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN
from handlers import router

def setup_logging() -> None:
    """Настраивает базовое логирование с уровнем INFO для всего приложения."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

async def main() -> None:
    """Основная асинхронная функция: инициализация и запуск бота."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Запуск бота ChiZhen...")

    # Создаём объект бота. Намеренно НЕ задаём parse_mode (HTML/Markdown),
    # чтобы избежать ошибок парсинга, если ответ модели содержит спецсимволы
    # вроде "<", ">" или "*" - отправляем ответы как обычный текст.
    bot = Bot(token=BOT_TOKEN)

    # Dispatcher - центральный диспетчер обновлений в aiogram 3.x
    dp = Dispatcher()

    # Подключаем роутер со всеми хендлерами (команды + текстовые сообщения)
    dp.include_router(router)

    try:
        # Удаляем возможный webhook и накопленные апдейты перед стартом polling,
        # чтобы не обрабатывать старые/дублирующиеся сообщения после перезапуска
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Бот ChiZhen успешно запущен и слушает сообщения (polling)")
        await dp.start_polling(bot)
    finally:
        # Корректно закрываем сессию бота при остановке
        await bot.session.close()
        logger.info("Бот ChiZhen остановлен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен вручную")
