"""Карточка в виде Markdown для копирования в CMS или документ."""

from app.guards import chars
from app.schemas import ProductCard


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def card_to_markdown(card: ProductCard) -> str:
    status = "Черновик прошёл автоматические проверки" if card.status == "ok" else "В черновике есть замечания, см. ниже"
    lines = [
        f"# {card.name}",
        "",
        f"Производитель: {card.manufacturer}. {status}.",
        "",
    ]
    if card.warnings:
        lines += ["## Требует проверки", "", *[f"- {warning}" for warning in card.warnings], ""]
    if card.needs_clarification:
        lines += [
            "## Требует уточнения",
            "",
            *[f"- **{item.field}**: {item.reason}" for item in card.needs_clarification],
            "",
        ]
    if card.missing_fields:
        lines += ["## Нет во входных данных", "", ", ".join(card.missing_fields) + ".", ""]
    lines += [
        f"## SEO-заголовок ({chars(card.meta.title_length)})",
        "",
        card.seo_title,
        "",
        f"## SEO-описание ({chars(card.meta.description_length)})",
        "",
        card.seo_description,
        "",
        "## Ключевые характеристики",
        "",
        "| Характеристика | Значение |",
        "| --- | --- |",
        *[f"| {_cell(row.name)} | {_cell(row.value)} |" for row in card.characteristics],
        "",
        "## Поисковые запросы",
        "",
        *[f"- {query}" for query in card.search_queries],
        "",
        "## Для менеджера",
        "",
        f"**Кому подходит.** {card.commercial.audience}",
        "",
        f"**Какие задачи решает.** {card.commercial.tasks}",
        "",
    ]
    return "\n".join(lines)
