"""Сборка карточки: вызов модели, проверки, повторы и итоговый результат."""

from typing import Protocol

from app.errors import LLMError
from app.guards import check_draft, normalize, verify_extracted
from app.input_checks import Assessment, expected_name_for
from app.prompts import SYSTEM_PROMPT, build_repair_message, build_user_message
from app.schemas import (
    NO_DATA,
    CardMeta,
    Characteristic,
    ExtractedSpec,
    LLMDraft,
    ProductCard,
    ProductInput,
)

MAX_ATTEMPTS = 3


class Drafter(Protocol):
    model: str

    def __call__(self, system: str, user: str) -> LLMDraft: ...


def generate_card(assessment: Assessment, drafter: Drafter) -> ProductCard:
    product = assessment.product
    warnings = []

    draft = drafter(SYSTEM_PROMPT, build_user_message(assessment))
    problems = check_draft(draft, product)
    attempts = 1
    while problems and attempts < MAX_ATTEMPTS:
        try:
            candidate = drafter(SYSTEM_PROMPT, build_repair_message(assessment, draft, problems))
        except LLMError as exc:
            warnings.append(f"Повторная генерация не удалась: {exc.message}")
            break
        attempts += 1
        candidate_problems = check_draft(candidate, product)
        if len(candidate_problems) <= len(problems):
            draft, problems = candidate, candidate_problems

    verified, rejected = verify_extracted(draft.extracted_specs, product)
    specs = _drop_known(verified, product)
    characteristics, missing = _build_characteristics(product, specs, assessment.missing_fields)
    clarifications = assessment.needs_clarification + [
        issue for issue in draft.data_issues if issue not in assessment.needs_clarification
    ]
    warnings = problems + rejected + warnings

    title = draft.seo_title.strip()
    description = draft.seo_description.strip()
    return ProductCard(
        status="needs_attention" if warnings or clarifications else "ok",
        name=product.name,
        manufacturer=product.manufacturer or NO_DATA,
        seo_title=title,
        seo_description=description,
        characteristics=characteristics,
        search_queries=[query.strip() for query in draft.search_queries],
        commercial=draft.commercial,
        missing_fields=missing,
        needs_clarification=clarifications,
        warnings=warnings,
        meta=CardMeta(
            title_length=len(title),
            description_length=len(description),
            attempts=attempts,
            model=drafter.model,
        ),
    )


def _spec_identity(name: str) -> str:
    return expected_name_for(name) or normalize(name)


def _drop_known(specs: list[ExtractedSpec], product: ProductInput) -> list[ExtractedSpec]:
    """Значение из specs главнее: описание его не перекрывает, расхождение модель отмечает в data_issues."""
    known = {_spec_identity(key) for key in product.specs}
    return [spec for spec in specs if _spec_identity(spec.name) not in known]


def _build_characteristics(
    product: ProductInput, extracted: list[ExtractedSpec], missing_fields: list[str]
) -> tuple[list[Characteristic], list[str]]:
    rows = [
        Characteristic(name=key, value=value, source="specs")
        for key, value in product.specs.items()
    ]
    rows += [
        Characteristic(name=spec.name, value=spec.value, source="description") for spec in extracted
    ]

    filled = {_spec_identity(spec.name) for spec in extracted}
    missing = [field for field in missing_fields if _spec_identity(field) not in filled]
    rows += [
        Characteristic(name=field, value=NO_DATA, source="none")
        for field in missing
        if field not in ("Производитель", "Описание")
    ]
    return rows, missing
