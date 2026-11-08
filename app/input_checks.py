"""Разбор входного JSON и оценка полноты данных. LLM здесь не участвует."""

import json
import math
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.errors import InputError
from app.schemas import Clarification, ProductInput

PLACEHOLDERS = {
    "",
    "-",
    "–",
    "—",
    "?",
    "н/д",
    "нд",
    "n/a",
    "na",
    "null",
    "none",
    "tbd",
    "нет данных",
    "данных нет",
}

# Характеристики, которые задание называет типовыми для прибора.
# Значение — проверка, относится ли ключ из specs к этой характеристике.
EXPECTED_CHARACTERISTICS = {
    "Диапазон измерений": lambda key: "диапазон" in key,
    "Класс точности": lambda key: "класс точности" in key or key == "точность",
    "Питание": lambda key: "питан" in key,
    "Тип корпуса": lambda key: key in {"корпус", "тип корпуса", "исполнение корпуса"},
    "Интерфейсы": lambda key: "интерфейс" in key,
}

MEASURED_KEY = re.compile(
    r"диапазон|диаметр|напряжен|давлен|температур|длин|масс|вес|ток|мощност|частот"
)
BARE_NUMBER = re.compile(r"[\d\s.,–—-]+")
TRUNCATED = re.compile(r"(\.\.\.|…)\s*$")
MIN_DESCRIPTION_LENGTH = 40

FIELD_HINTS = {
    "name": "поле name должно быть строкой",
    "manufacturer": "поле manufacturer должно быть строкой",
    "description": "поле description должно быть строкой",
    "specs": 'поле specs должно быть объектом вида {"характеристика": "значение"}, значения — строки или числа',
}


@dataclass
class Assessment:
    product: ProductInput
    missing_fields: list[str]
    needs_clarification: list[Clarification]


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} не входит в стандарт JSON")


def _parse_finite_float(text: str) -> float:
    # 1e400 json разбирает в бесконечность, а в карточку она попала бы строкой «inf».
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"число {text} вне допустимого диапазона")
    return value


def parse_product(raw: str | bytes) -> ProductInput:
    try:
        data = json.loads(raw, parse_constant=_reject_constant, parse_float=_parse_finite_float)
        # Одиночный суррогат (U+D800 и подобные) нельзя закодировать в UTF-8 для запроса к LLM.
        json.dumps(data, ensure_ascii=False).encode()
    # ValueError включает ошибки разбора, кодировки и слишком длинные числа.
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, json.JSONDecodeError):
            message = (
                f"Некорректный JSON (строка {exc.lineno}, позиция {exc.colno}). "
                "Проверьте кавычки и запятые."
            )
        else:
            message = "Некорректный JSON: недопустимое число или символ, либо слишком глубокая вложенность."
        raise InputError("invalid_json", 400, message) from exc
    if not isinstance(data, dict):
        raise InputError("invalid_structure", 422, "Ожидается JSON-объект с данными одного товара.")
    try:
        return ProductInput.model_validate(data)
    except ValidationError as exc:
        fields = dict.fromkeys(str(error["loc"][0]) for error in exc.errors())
        raise InputError(
            "invalid_structure",
            422,
            "Неверная структура данных о товаре.",
            [FIELD_HINTS[field] for field in fields],
        ) from exc


def is_blank(value: str | None) -> bool:
    return value is None or value.strip().lower() in PLACEHOLDERS


def expected_name_for(spec_key: str) -> str | None:
    """Какой типовой характеристике соответствует ключ из specs."""
    key = spec_key.strip().lower()
    return next((name for name, matches in EXPECTED_CHARACTERISTICS.items() if matches(key)), None)


def _has_letter(text: str) -> bool:
    return any(char.isalpha() for char in text)


def _lacks_words(value: str | None) -> bool:
    # Отсеиваем только заведомый мусор: отличить бессмыслицу от обозначения вроде «ЗОТ» код не может.
    return is_blank(value) or not _has_letter(value)


def assess(product: ProductInput) -> Assessment:
    specs = {
        key.strip(): value.strip()
        for key, value in product.specs.items()
        if not is_blank(value) and _has_letter(key)
    }
    blank_specs = [
        key.strip() for key, value in product.specs.items() if is_blank(value) and _has_letter(key)
    ]
    letterless_keys = [key.strip() for key in product.specs if key.strip() and not _has_letter(key)]
    manufacturer = None if _lacks_words(product.manufacturer) else product.manufacturer.strip()
    description = None if _lacks_words(product.description) else product.description.strip()

    if _lacks_words(product.name):
        raise InputError(
            "insufficient_data",
            422,
            "Не указано название товара: в нём должны быть буквы.",
            ["name: укажите название товара"],
        )
    if not specs and not description:
        raise InputError(
            "insufficient_data",
            422,
            "Недостаточно данных: нет ни характеристик, ни описания.",
            [
                "specs, description: заполните хотя бы одно из полей",
                "описание и названия характеристик без букв не учитываются",
            ],
        )

    missing = []
    if not manufacturer:
        missing.append("Производитель")
    if not description:
        missing.append("Описание")
    filled = {expected_name_for(key) for key in specs}
    missing += [name for name in EXPECTED_CHARACTERISTICS if name not in filled]
    missing += [key for key in blank_specs if expected_name_for(key) is None]

    clean = ProductInput(
        name=product.name.strip(), manufacturer=manufacturer, specs=specs, description=description
    )
    ignored = [
        Clarification(field=key, reason="Название характеристики без букв, строка не учтена.")
        for key in letterless_keys
    ]
    return Assessment(clean, missing, _find_clarifications(specs, description) + ignored)


def _find_clarifications(specs: dict[str, str], description: str | None) -> list[Clarification]:
    found = []
    if description and TRUNCATED.search(description):
        found.append(
            Clarification(
                field="Описание",
                reason="Текст обрезан многоточием, нужен полный фрагмент паспорта.",
            )
        )
    elif description and len(description) < MIN_DESCRIPTION_LENGTH:
        found.append(
            Clarification(
                field="Описание", reason="Описание слишком короткое, текст получится общим."
            )
        )
    for key, value in specs.items():
        if "," not in key and MEASURED_KEY.search(key.lower()) and BARE_NUMBER.fullmatch(value):
            found.append(Clarification(field=key, reason="Значение указано без единиц измерения."))
    return found
