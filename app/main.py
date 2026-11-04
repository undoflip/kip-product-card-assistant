"""HTTP-сервис: страница с формой и эндпоинт генерации карточки."""

import logging
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from app.errors import InputError, ServiceError
from app.input_checks import assess, parse_product
from app.llm import create_drafter
from app.pipeline import Drafter, generate_card
from app.render import card_to_markdown

load_dotenv()

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 100_000
INDEX_PAGE = Path(__file__).parent / "static" / "index.html"


def _error_response(status: int, code: str, message: str, details: list[str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or []}},
    )


def create_app(drafter_factory: Callable[[], Drafter] = create_drafter) -> FastAPI:
    app = FastAPI(title="AI-помощник для товарных описаний")

    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return _error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Необработанная ошибка", exc_info=exc)
        return _error_response(500, "internal_error", "Внутренняя ошибка сервиса. Подробности в логе сервера.")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(INDEX_PAGE)

    @app.post("/api/generate")
    async def generate(request: Request) -> dict:
        # Тело разбираем сами: FastAPI отдал бы на битый JSON свою ошибку на английском.
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise InputError("body_too_large", 413, f"Данные больше {MAX_BODY_BYTES // 1000} КБ. Сократите описание.")
        assessment = assess(parse_product(body))
        drafter = drafter_factory()
        card = await run_in_threadpool(generate_card, assessment, drafter)
        return {"card": card.model_dump(), "markdown": card_to_markdown(card)}

    return app


app = create_app()
