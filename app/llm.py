"""Вызов Claude и перевод ошибок SDK в сообщения для пользователя."""

import os

import anthropic

from app.errors import LLMError
from app.schemas import LLMDraft

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_BASE_URL = "https://api.anthropic.com"
MAX_TOKENS = 16000
TIMEOUT_SECONDS = 120


class ClaudeDrafter:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client
        self.model = model

    def __call__(self, system: str, user: str) -> LLMDraft:
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "medium"},
                output_format=LLMDraft,
            )
        except anthropic.APIStatusError as exc:
            raise _translate_status_error(exc) from exc
        except anthropic.APIConnectionError as exc:  # включает таймауты
            raise LLMError("llm_unavailable", 502, "Не удалось связаться с сервисом LLM. Повторите позже.") from exc
        except ValueError as exc:  # parse() не смог разобрать JSON: обрезанный ответ или несоответствие схеме
            raise LLMError("llm_bad_response", 502, "Модель вернула неполный или некорректный ответ.") from exc

        if response.stop_reason == "refusal":
            raise LLMError("llm_refusal", 502, "Модель отказалась обрабатывать эти данные.")
        if response.parsed_output is None:
            raise LLMError("llm_bad_response", 502, "Модель вернула неполный или некорректный ответ.")
        return response.parsed_output


def _translate_status_error(exc: anthropic.APIStatusError) -> LLMError:
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return LLMError("llm_auth", 502, "Ключ API неверный или у него нет доступа к модели. Проверьте ANTHROPIC_API_KEY.")
    if isinstance(exc, anthropic.NotFoundError):
        return LLMError("llm_model_not_found", 502, "Модель не найдена или недоступна. Проверьте ANTHROPIC_MODEL.")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("llm_rate_limit", 429, "Превышен лимит запросов к LLM. Повторите через минуту.")
    if isinstance(exc, anthropic.BadRequestError):
        return LLMError("llm_bad_request", 502, "Сервис LLM отклонил запрос. Подробности в логе сервера.")
    if exc.status_code >= 500:
        return LLMError("llm_unavailable", 502, "Сервис LLM временно недоступен. Повторите позже.")
    return LLMError("llm_error", 502, f"Сервис LLM вернул ошибку {exc.status_code}.")


def create_drafter() -> ClaudeDrafter:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise LLMError(
            "missing_api_key",
            503,
            "Не задан ANTHROPIC_API_KEY. Создайте файл .env со строкой ANTHROPIC_API_KEY=ваш_ключ.",
        )
    # Адрес задаётся явно: SDK иначе возьмёт ANTHROPIC_BASE_URL из окружения и отправит ключ туда.
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        timeout=TIMEOUT_SECONDS,
    )
    return ClaudeDrafter(client, os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL))
