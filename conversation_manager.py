# conversation_manager.py - управление историей диалогов пользователей.

# История хранится в оперативной памяти процесса (обычный словарь Python).

# Ключ словаря - chat_id пользователя, значение - список сообщений в формате,
# совместимом с Groq/OpenAI Chat Completions API:
#    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]

from collections import defaultdict, deque
from typing import Deque, Dict, List, Literal, Optional

from config import HISTORY_LIMIT

# Тип одного сообщения в истории
Message = Dict[str, str]

class ConversationManager:
    """
    Класс для хранения и управления историей диалогов по каждому chat_id отдельно.

    Используем defaultdict с deque(maxlen=HISTORY_LIMIT), чтобы история
    автоматически "обрезалась" по последним HISTORY_LIMIT сообщениям
    без ручного контроля переполнения.

    Дополнительно храним имя пользователя (из Telegram-профиля) по chat_id,
    чтобы бот мог обращаться к пользователю по имени в ответах.
    """

    def __init__(self, history_limit: int = HISTORY_LIMIT) -> None:
        self._history_limit = history_limit
        # defaultdict сам создаст пустую deque при первом обращении к новому chat_id
        self._storage: Dict[int, Deque[Message]] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        # Имя пользователя (first_name из Telegram) по chat_id.
        # Обновляется при каждом сообщении на случай, если пользователь сменил имя в Telegram.
        self._user_names: Dict[int, str] = {}

    def add_message(self, chat_id: int, role: Literal["user", "assistant"], content: str) -> None:
        """
        Добавляет одно сообщение в историю диалога пользователя.

        :param chat_id: идентификатор чата (пользователя) в Telegram
        :param role: роль отправителя сообщения - "user" или "assistant"
        :param content: текст сообщения
        """
        self._storage[chat_id].append({"role": role, "content": content})

    def get_history(self, chat_id: int) -> List[Message]:
        """
        Возвращает историю диалога пользователя в виде списка (копии),
        готовую для передачи в Groq API.

        :param chat_id: идентификатор чата
        :return: список сообщений [{"role": ..., "content": ...}, ...]
        """
        return list(self._storage[chat_id])

    def clear_history(self, chat_id: int) -> None:
        """
        Полностью очищает историю диалога для указанного chat_id.
        Имя пользователя при этом НЕ стирается - /clear чистит только
        контекст диалога, а не знание бота о том, как зовут пользователя.

        :param chat_id: идентификатор чата
        """
        self._storage[chat_id].clear()

    def set_user_name(self, chat_id: int, name: str) -> None:
        """
        Сохраняет (или обновляет) имя пользователя для данного chat_id.

        :param chat_id: идентификатор чата
        :param name: имя пользователя (обычно first_name из Telegram)
        """
        if name:
            self._user_names[chat_id] = name

    def get_user_name(self, chat_id: int) -> Optional[str]:
        """
        Возвращает сохранённое имя пользователя, если оно известно.

        :param chat_id: идентификатор чата
        :return: имя пользователя или None, если ещё не сохранено
        """
        return self._user_names.get(chat_id)

# Единственный экземпляр менеджера истории на весь процесс бота (простой синглтон).
# Импортируется в handlers.py, чтобы все хендлеры работали с одним и тем же хранилищем.
conversation_manager = ConversationManager()