from app.input_checks import assess
from app.pipeline import generate_card
from app.render import card_to_markdown
from app.schemas import Clarification
from tests.helpers import FakeDrafter, make_draft, make_product


def render(draft=None, product=None) -> str:
    card = generate_card(assess(product or make_product()), FakeDrafter(draft or make_draft()))
    return card_to_markdown(card)


def test_all_required_blocks_are_present():
    text = render()
    for heading in ("SEO-заголовок", "SEO-описание", "Ключевые характеристики", "Поисковые запросы", "Для менеджера"):
        assert heading in text


def test_generated_content_is_present():
    draft = make_draft()
    text = render(draft)
    assert draft.seo_title in text
    assert draft.seo_description in text
    assert draft.commercial.audience in text
    assert all(query in text for query in draft.search_queries)


def test_lengths_are_shown_for_manual_check():
    assert "900 символов" in render()


def test_absent_characteristic_shows_no_data_in_table():
    assert "| Питание | данных нет |" in render()


def test_pipe_in_value_does_not_break_table():
    product = make_product(specs={"присоединение": "G1/2 | M20"})
    draft = make_draft(
        seo_title="Манометр показывающий DM 02",
        search_queries=["манометр DM 02", "манометр показывающий", "манометр Манотомь"],
    )
    assert "| присоединение | G1/2 \\| M20 |" in render(draft, product)


def test_problems_are_listed_when_present():
    issue = Clarification(field="класс точности", reason="В specs 1,5, в описании 2,5.")
    text = render(make_draft(data_issues=[issue]))
    assert "Требует уточнения" in text
    assert "В specs 1,5, в описании 2,5." in text


def test_clean_card_has_no_warning_section():
    assert "Требует проверки" not in render()


def test_status_line_reads_as_a_sentence():
    issue = Clarification(field="класс точности", reason="В specs 1,5, в описании 2,5.")
    assert "В черновике есть замечания" in render(make_draft(data_issues=[issue]))


def test_length_in_heading_agrees_with_number():
    assert "(32 символа)" in render(make_draft(seo_title="Манометр показывающий DM 02 G1/2"))
