"""Ошибки сервиса: каждая несёт HTTP-статус и сообщение для контент-менеджера."""


class ServiceError(Exception):
    def __init__(self, code: str, status: int, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.details = details or []


class InputError(ServiceError):
    """Входные данные нельзя обработать, LLM не вызывается."""


class LLMError(ServiceError):
    """LLM не вернула пригодный ответ."""
