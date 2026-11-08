"""Модели данных: вход, ответ LLM и итоговая карточка."""

from typing import Literal

from pydantic import BaseModel, field_validator

NO_DATA = "данных нет"


class ProductInput(BaseModel):
    name: str | None = None
    manufacturer: str | None = None
    specs: dict[str, str] = {}
    description: str | None = None

    @field_validator("specs", mode="before")
    @classmethod
    def normalize_specs(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("specs must be an object")
        normalized = {}
        for key, item in value.items():
            if item is None:
                normalized[key] = ""
            elif isinstance(item, str):
                normalized[key] = item
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                normalized[key] = str(item)
            else:
                raise ValueError(f"unsupported value for {key}")
        return normalized


class Clarification(BaseModel):
    field: str
    reason: str


class ExtractedSpec(BaseModel):
    """Характеристика, найденная моделью в описании. quote сверяется с исходным текстом."""

    name: str
    value: str
    quote: str


class CommercialBlock(BaseModel):
    audience: str
    tasks: str


class LLMDraft(BaseModel):
    """Схема структурированного ответа модели."""

    seo_title: str
    seo_description: str
    extracted_specs: list[ExtractedSpec]
    search_queries: list[str]
    commercial: CommercialBlock
    data_issues: list[Clarification]


class Characteristic(BaseModel):
    name: str
    value: str
    source: Literal["specs", "description", "none"]


class CardMeta(BaseModel):
    title_length: int
    description_length: int
    attempts: int
    model: str


class ProductCard(BaseModel):
    status: Literal["ok", "needs_attention"]
    name: str
    manufacturer: str
    seo_title: str
    seo_description: str
    characteristics: list[Characteristic]
    search_queries: list[str]
    commercial: CommercialBlock
    missing_fields: list[str]
    needs_clarification: list[Clarification]
    warnings: list[str]
    meta: CardMeta
