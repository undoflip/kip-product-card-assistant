"""Общие заготовки для тестов."""

from app.schemas import CommercialBlock, LLMDraft, ProductInput

FILLER = (
    "Манометр показывающий помогает контролировать избыточное давление на технологических линиях. "
)


def make_product(**overrides) -> ProductInput:
    data = {
        "name": "Манометр показывающий DM 02",
        "manufacturer": "Манотомь",
        "specs": {
            "диапазон измерений": "0–1,6 МПа",
            "класс точности": "1,5",
            "присоединение": "G1/2",
            "диаметр корпуса": "100 мм",
        },
        "description": "Прибор предназначен для измерения избыточного давления неагрессивных сред.",
    }
    return ProductInput(**{**data, **overrides})


def make_draft(**overrides) -> LLMDraft:
    data = {
        "seo_title": "Манометр показывающий DM 02 Манотомь 0–1,6 МПа",
        "seo_description": (FILLER * 10)[:900],
        "extracted_specs": [],
        "search_queries": ["манометр DM 02", "манометр 1,6 МПа", "манометр показывающий G1/2"],
        "commercial": CommercialBlock(audience="Службы КИПиА.", tasks="Контроль давления."),
        "data_issues": [],
    }
    return LLMDraft(**{**data, **overrides})


class FakeDrafter:
    """Отдаёт заранее заданные ответы по очереди и запоминает запросы."""

    model = "fake-model"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, system: str, user: str) -> LLMDraft:
        self.calls.append((system, user))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
