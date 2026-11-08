import pytest

from app.errors import LLMError
from app.input_checks import assess
from app.pipeline import MAX_ATTEMPTS, generate_card
from app.schemas import NO_DATA, Clarification, ExtractedSpec
from tests.helpers import FakeDrafter, make_draft, make_product

UNAVAILABLE = LLMError("llm_unavailable", 502, "Сервис недоступен.")
TOO_LONG_TITLE = "Манометр DM 02 ".ljust(90, "ы")


def run(*responses, product=None):
    drafter = FakeDrafter(*responses)
    return generate_card(assess(product or make_product()), drafter), drafter


def values(card) -> dict[str, str]:
    return {row.name: row.value for row in card.characteristics}


def test_clean_draft_is_returned_after_one_attempt():
    card, drafter = run(make_draft())
    assert card.status == "ok"
    assert card.warnings == []
    assert card.meta.attempts == 1
    assert len(drafter.calls) == 1


def test_card_identifies_the_product():
    card, _ = run(make_draft())
    assert card.name == "Манометр показывающий DM 02"
    assert card.manufacturer == "Манотомь"


def test_missing_manufacturer_is_marked_on_card():
    card, _ = run(make_draft(), product=make_product(manufacturer=None))
    assert card.manufacturer == NO_DATA


def test_meta_reports_lengths():
    card, _ = run(make_draft())
    assert card.meta.title_length == len(card.seo_title)
    assert card.meta.description_length == len(card.seo_description)
    assert card.meta.model == "fake-model"


def test_specs_are_copied_by_code_not_by_model():
    card, _ = run(make_draft())
    assert values(card)["диапазон измерений"] == "0–1,6 МПа"
    assert values(card)["класс точности"] == "1,5"


def test_absent_expected_characteristics_get_no_data_mark():
    card, _ = run(make_draft())
    row = next(row for row in card.characteristics if row.name == "Питание")
    assert (row.value, row.source) == (NO_DATA, "none")


def test_blank_spec_gets_no_data_mark():
    product = make_product(specs={"присоединение": "", "класс точности": "1,5"})
    draft = make_draft(
        seo_title="Манометр показывающий DM 02",
        search_queries=["манометр DM 02", "манометр показывающий", "манометр Манотомь"],
    )
    card, _ = run(draft, product=product)
    assert values(card)["присоединение"] == NO_DATA
    assert "присоединение" in card.missing_fields


def test_failed_check_triggers_retry_with_feedback():
    card, drafter = run(make_draft(seo_title=TOO_LONG_TITLE), make_draft())
    assert card.status == "ok"
    assert card.meta.attempts == 2
    assert "90 символов" in drafter.calls[1][1]
    assert TOO_LONG_TITLE in drafter.calls[1][1]


def test_retries_are_limited_and_problems_stay_visible():
    bad = make_draft(seo_title=TOO_LONG_TITLE)
    card, drafter = run(*[bad] * MAX_ATTEMPTS)
    assert len(drafter.calls) == MAX_ATTEMPTS
    assert card.status == "needs_attention"
    assert any("90 символов" in warning for warning in card.warnings)


def test_title_is_never_cut_silently():
    bad = make_draft(seo_title=TOO_LONG_TITLE)
    card, _ = run(*[bad] * MAX_ATTEMPTS)
    assert card.seo_title == TOO_LONG_TITLE.strip()


def test_retry_keeps_draft_with_fewer_problems():
    better = make_draft(seo_title=TOO_LONG_TITLE)
    worse = make_draft(seo_title=TOO_LONG_TITLE, search_queries=["один"])
    card, _ = run(better, worse, worse)
    assert card.search_queries == better.search_queries


def test_first_call_error_propagates():
    with pytest.raises(LLMError):
        run(UNAVAILABLE)


def test_error_during_retry_returns_existing_draft_with_warning():
    card, _ = run(make_draft(seo_title=TOO_LONG_TITLE), UNAVAILABLE)
    assert card.status == "needs_attention"
    assert any("Сервис недоступен" in warning for warning in card.warnings)


def test_verified_extracted_spec_fills_expected_field():
    product = make_product(
        description="Прибор работает от напряжения питания 24 В и измеряет давление."
    )
    spec = ExtractedSpec(name="Питание", value="24 В", quote="напряжения питания 24 В")
    card, _ = run(make_draft(extracted_specs=[spec]), product=product)
    row = next(row for row in card.characteristics if row.name == "Питание")
    assert (row.value, row.source) == ("24 В", "description")
    assert "Питание" not in card.missing_fields


def test_invented_extracted_spec_is_dropped_with_warning():
    spec = ExtractedSpec(name="Масса", value="2 кг", quote="масса 2 кг")
    card, _ = run(make_draft(extracted_specs=[spec]))
    assert "Масса" not in values(card)
    assert card.status == "needs_attention"
    assert any("Масса" in warning for warning in card.warnings)


def test_extracted_spec_does_not_override_spec_value():
    product = make_product(description="Класс точности 2,5 указан в старом паспорте прибора.")
    spec = ExtractedSpec(name="Класс точности", value="2,5", quote="Класс точности 2,5")
    card, _ = run(make_draft(extracted_specs=[spec]), product=product)
    assert values(card)["класс точности"] == "1,5"
    assert "Класс точности" not in values(card)


def test_model_reported_conflict_needs_clarification():
    issue = Clarification(field="класс точности", reason="В specs 1,5, в описании 2,5.")
    card, _ = run(make_draft(data_issues=[issue]))
    assert issue in card.needs_clarification
    assert card.status == "needs_attention"


def test_input_clarification_sets_needs_attention():
    product = make_product(description="Прибор предназначен для измерения давления...")
    card, _ = run(make_draft(), product=product)
    assert card.status == "needs_attention"
    assert card.needs_clarification[0].field == "Описание"


def test_missing_fields_alone_do_not_block_status():
    card, _ = run(make_draft())
    assert "Питание" in card.missing_fields
    assert card.status == "ok"
