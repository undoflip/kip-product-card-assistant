import pytest

from app.guards import chars, check_draft, verify_extracted
from app.schemas import CommercialBlock, ExtractedSpec
from tests.helpers import FILLER, make_draft, make_product


def description_with(text: str) -> str:
    return (text + " " + FILLER * 10)[:900]


def problems_for(product=None, **draft_fields) -> list[str]:
    return check_draft(make_draft(**draft_fields), product or make_product())


def test_clean_draft_has_no_problems():
    assert problems_for() == []


# Длины и количество


@pytest.mark.parametrize("length, ok", [(70, True), (71, False)])
def test_title_limit(length, ok):
    title = "Манометр DM 02 ".ljust(length, "ы")
    assert (problems_for(seo_title=title) == []) is ok


@pytest.mark.parametrize("length, ok", [(799, False), (800, True), (1200, True), (1201, False)])
def test_description_limits(length, ok):
    text = "ы" * length  # без пробелов: strip() не должен менять длину
    assert (problems_for(seo_description=text) == []) is ok


def test_length_problem_states_actual_size():
    problems = problems_for(seo_description=(FILLER * 20)[:500])
    assert any("500" in problem and "800" in problem for problem in problems)


def test_surrounding_spaces_do_not_count_towards_length():
    text = (FILLER * 20)[:799] + "   "
    assert problems_for(seo_description=text) != []


@pytest.mark.parametrize(
    "queries",
    [
        ["манометр", "манометр DM 02"],
        ["манометр", "манометр DM 02", "манометр G1/2", "манометр Манотомь", "датчик", "прибор"],
        ["манометр", "манометр", "манометр DM 02"],
        ["манометр", "  ", "манометр DM 02"],
    ],
)
def test_query_count_and_uniqueness(queries):
    assert problems_for(search_queries=queries) != []


def test_empty_commercial_block_is_a_problem():
    assert problems_for(commercial=CommercialBlock(audience=" ", tasks="Контроль.")) != []


# Выдуманные значения


@pytest.mark.parametrize(
    "invented",
    [
        "Рабочее давление достигает 1,5 МПа.",  # число есть во входе, но как класс точности
        "Эквивалент диапазона составляет 16 бар.",  # пересчёт единиц
        "Масса прибора 50 кг.",
        "Выдерживает 25 циклов.",  # голое число
        "Диаметр корпуса 150 мм.",
        "Диапазон до 2,5 мегапаскаля.",
    ],
)
def test_invented_values_are_flagged(invented):
    assert problems_for(seo_description=description_with(invented)) != []


@pytest.mark.parametrize(
    "fact",
    [
        "Диапазон измерений 0–1,6 МПа.",
        "Диапазон измерений от 0 до 1,6 МПа.",
        "Давление до 1.6 мпа.",
        "Класс точности 1,5.",
        "Присоединение G1/2.",
        "Диаметр корпуса 100 мм.",
        "Модель DM 02.",
    ],
)
def test_values_from_input_pass(fact):
    assert problems_for(seo_description=description_with(fact)) == []


def test_latin_and_cyrillic_units_are_the_same():
    product = make_product(specs={"питание": "24 V"})
    assert problems_for(product, seo_title="Датчик DM 02", search_queries=["датчик DM 02", "датчик", "прибор"],
                        seo_description=description_with("Питание 24 В.")) == []


def test_value_inside_description_is_allowed():
    product = make_product(description="Прибор выдерживает перегрузку 25 % от верхнего предела измерений.")
    assert problems_for(product, seo_description=description_with("Допустимая перегрузка 25 %.")) == []


@pytest.mark.parametrize(
    "claim",
    [
        "Соответствует ГОСТ.",
        "Степень защиты IP65.",
        "Выход RS-485 и Modbus.",
        "Корпус из нержавеющей стали.",
        "Прибор внесён в Госреестр СИ.",
        "Первичная поверка включена.",
        "Гарантия производителя.",
        "Взрывозащищённое исполнение.",
        "Имеет сертификат соответствия.",
        "Обеспечивает высокую точность.",
    ],
)
def test_unconfirmed_claims_are_flagged(claim):
    assert problems_for(seo_description=description_with(claim)) != []


def test_claim_confirmed_by_input_passes():
    product = make_product(description="Прибор имеет степень защиты IP65 и корпус из нержавеющей стали.")
    text = description_with("Степень защиты IP65, корпус из нержавеющей стали.")
    assert problems_for(product, seo_description=text) == []


@pytest.mark.parametrize(
    "fields",
    [
        {"seo_title": "Манометр DM 02 на 16 бар"},
        {"search_queries": ["манометр DM 02", "манометр 16 бар", "манометр G1/2"]},
        {"commercial": CommercialBlock(audience="Службы КИПиА.", tasks="Контроль давления до 16 бар.")},
    ],
)
def test_every_generated_field_is_checked(fields):
    assert any("16" in problem for problem in problems_for(**fields))


def test_no_data_phrase_is_not_allowed_in_public_text():
    assert problems_for(seo_description=description_with("Питание: данных нет.")) != []


def test_altered_model_name_in_title_is_flagged():
    assert problems_for(seo_title="Манометр показывающий ДМ 02 Манотомь") != []


# Характеристики из описания


def test_extracted_spec_with_exact_quote_is_verified():
    product = make_product(description="Прибор имеет степень защиты  IP65\nпо стандарту.")
    spec = ExtractedSpec(name="Степень защиты", value="IP65", quote="степень защиты IP65")
    verified, rejected = verify_extracted([spec], product)
    assert verified == [spec]
    assert rejected == []


def test_extracted_spec_with_invented_quote_is_rejected():
    spec = ExtractedSpec(name="Степень защиты", value="IP65", quote="степень защиты IP65")
    verified, rejected = verify_extracted([spec], make_product())
    assert verified == []
    assert "Степень защиты" in rejected[0]


def test_extracted_spec_value_must_be_inside_quote():
    product = make_product(description="Прибор имеет степень защиты IP54.")
    spec = ExtractedSpec(name="Степень защиты", value="IP65", quote="степень защиты IP54")
    verified, rejected = verify_extracted([spec], product)
    assert verified == []
    assert rejected


def test_extracted_spec_needs_non_empty_quote():
    spec = ExtractedSpec(name="Среда", value="", quote="")
    verified, rejected = verify_extracted([spec], make_product())
    assert verified == []
    assert rejected


@pytest.mark.parametrize(
    "count, expected",
    [
        (1, "1 символ"),
        (2, "2 символа"),
        (5, "5 символов"),
        (11, "11 символов"),
        (14, "14 символов"),
        (21, "21 символ"),
        (42, "42 символа"),
        (112, "112 символов"),
        (1063, "1063 символа"),
    ],
)
def test_chars_agrees_with_number(count, expected):
    assert chars(count) == expected


def test_parameters_in_brackets_are_not_part_of_model_designation():
    product = make_product(
        name="Манометр сварочный ТМ-210Р.00(0-2,5МПа) M12x1,5.2,5.",
        specs={"диапазон показаний": "0–2,5 МПа", "резьба": "M12×1,5"},
        description="Манометр измеряет давление жидких и газообразных сред в баллонных редукторах.",
    )
    title = "Манометр сварочный ТМ-210Р.00 Манотомь, 0–2,5 МПа, M12×1,5"
    problems = problems_for(product, seo_title=title, search_queries=["манометр ТМ-210Р.00", "манометр сварочный", "манометр Манотомь"])
    assert not [problem for problem in problems if "обозначение модели" in problem]


def test_model_designation_before_brackets_is_still_checked():
    product = make_product(name="Манометр сварочный ТМ-210Р.00(0-2,5МПа)")
    problems = problems_for(product, seo_title="Манометр сварочный TM-210P.00 Манотомь")
    assert any("обозначение модели" in problem for problem in problems)
