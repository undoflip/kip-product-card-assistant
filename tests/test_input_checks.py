import json

import pytest

from app.errors import InputError
from app.input_checks import assess, parse_product

VALID = {
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


def parse(data) -> object:
    return parse_product(json.dumps(data, ensure_ascii=False))


def test_valid_json_is_parsed():
    product = parse(VALID)
    assert product.name == "Манометр показывающий DM 02"
    assert product.specs["класс точности"] == "1,5"


UNPROCESSABLE_JSON = {
    "deep_nesting": "[" * 90_000,
    "huge_integer": '{"name": "x", "specs": {"a": ' + "1" * 5000 + "}}",
    "nan": '{"name": "x", "specs": {"a": NaN}}',
    "infinity": '{"name": "x", "specs": {"a": Infinity}}',
    "float_overflow": '{"name": "x", "specs": {"a": 1e400}}',
    "lone_surrogate": '{"name": "\\ud800", "specs": {"a": "1"}}',
}


@pytest.mark.parametrize("raw", UNPROCESSABLE_JSON.values(), ids=UNPROCESSABLE_JSON.keys())
def test_json_that_python_cannot_process_reports_invalid_json(raw):
    with pytest.raises(InputError) as exc:
        parse_product(raw)
    assert exc.value.code == "invalid_json"


def test_utf8_bom_from_windows_editors_is_accepted():
    assert parse_product(b"\xef\xbb\xbf" + json.dumps(VALID).encode()).name == VALID["name"]


@pytest.mark.parametrize("raw", ["{broken", "", "   ", '{"name": "x",}'])
def test_broken_json_reports_invalid_json(raw):
    with pytest.raises(InputError) as exc:
        parse_product(raw)
    assert exc.value.code == "invalid_json"
    assert exc.value.status == 400


@pytest.mark.parametrize("raw", ["[]", "42", '"text"', "null", "[{}, {}]"])
def test_non_object_json_reports_invalid_structure(raw):
    with pytest.raises(InputError) as exc:
        parse_product(raw)
    assert exc.value.code == "invalid_structure"
    assert exc.value.status == 422


@pytest.mark.parametrize(
    "patch, field",
    [
        ({"specs": ["0–1,6 МПа"]}, "specs"),
        ({"specs": {"класс": {"вложенный": "объект"}}}, "specs"),
        ({"specs": {"класс": True}}, "specs"),
        ({"name": 123}, "name"),
        ({"description": ["текст"]}, "description"),
    ],
)
def test_wrong_field_types_name_the_field(patch, field):
    with pytest.raises(InputError) as exc:
        parse({**VALID, **patch})
    assert exc.value.code == "invalid_structure"
    assert any(field in detail for detail in exc.value.details)


def test_numeric_spec_values_become_strings():
    product = parse({**VALID, "specs": {"диаметр, мм": 100, "класс точности": 1.5}})
    assert product.specs == {"диаметр, мм": "100", "класс точности": "1.5"}


@pytest.mark.parametrize(
    "blank", ["", "   ", "-", "—", "н/д", "Н/Д", "n/a", "нет данных", "данных нет", "tbd", None]
)
def test_placeholder_spec_value_counts_as_missing(blank):
    report = assess(parse({**VALID, "specs": {**VALID["specs"], "класс точности": blank}}))
    assert "класс точности" not in report.product.specs
    assert "Класс точности" in report.missing_fields


def test_real_value_net_is_kept():
    """«нет» — это факт о приборе (например, интерфейсов нет), а не пропуск."""
    report = assess(parse({**VALID, "specs": {**VALID["specs"], "интерфейсы": "нет"}}))
    assert report.product.specs["интерфейсы"] == "нет"
    assert "Интерфейсы" not in report.missing_fields


def test_absent_name_stops_generation():
    with pytest.raises(InputError) as exc:
        assess(parse({**VALID, "name": "  "}))
    assert exc.value.code == "insufficient_data"
    assert exc.value.status == 422
    assert "name" in exc.value.details[0]


def test_no_specs_and_no_description_stops_generation():
    with pytest.raises(InputError) as exc:
        assess(
            parse(
                {
                    "name": "Манометр",
                    "manufacturer": "X",
                    "specs": {"класс": ""},
                    "description": " ",
                }
            )
        )
    assert exc.value.code == "insufficient_data"


def test_missing_manufacturer_and_description_are_reported_but_allowed():
    report = assess(parse({"name": "Манометр", "specs": {"класс точности": "1,5"}}))
    assert "Производитель" in report.missing_fields
    assert "Описание" in report.missing_fields


def test_expected_characteristics_are_reported_when_absent():
    report = assess(parse(VALID))
    assert {"Питание", "Тип корпуса", "Интерфейсы"} <= set(report.missing_fields)
    assert "Диапазон измерений" not in report.missing_fields
    assert "Класс точности" not in report.missing_fields


def test_case_of_spec_key_does_not_matter_for_expected_fields():
    report = assess(
        parse({**VALID, "specs": {"Напряжение питания": "24 В", "ТИП КОРПУСА": "Щитовой"}})
    )
    assert "Питание" not in report.missing_fields
    assert "Тип корпуса" not in report.missing_fields


def test_case_diameter_does_not_fill_case_type():
    report = assess(parse(VALID))
    assert "Тип корпуса" in report.missing_fields


@pytest.mark.parametrize("ending", ["...", "…", "… "])
def test_truncated_description_needs_clarification(ending):
    report = assess(
        parse({**VALID, "description": "Прибор предназначен для измерения давления" + ending})
    )
    assert [c.field for c in report.needs_clarification] == ["Описание"]
    assert "обрезан" in report.needs_clarification[0].reason


def test_very_short_description_needs_clarification():
    report = assess(parse({**VALID, "description": "Манометр."}))
    assert [c.field for c in report.needs_clarification] == ["Описание"]


def test_measured_value_without_unit_needs_clarification():
    report = assess(parse({**VALID, "specs": {"диапазон измерений": "1,6"}}))
    assert [c.field for c in report.needs_clarification] == ["диапазон измерений"]
    assert "единиц" in report.needs_clarification[0].reason


def test_accuracy_class_without_unit_is_fine():
    report = assess(parse(VALID))
    assert report.needs_clarification == []


@pytest.mark.parametrize("name", ["12345", "!!!", "-5156", "00-00 / 1,5"])
def test_name_without_letters_stops_generation(name):
    with pytest.raises(InputError) as exc:
        assess(parse({**VALID, "name": name}))
    assert exc.value.code == "insufficient_data"
    assert exc.value.status == 422
    assert "name" in exc.value.details[0]


@pytest.mark.parametrize("name", ["ТМ-210Р.00", "DM 02", "МКД 4-20", "G1"])
def test_model_designations_with_letters_are_accepted(name):
    assert assess(parse({**VALID, "name": name})).product.name == name


def test_manufacturer_without_letters_counts_as_missing():
    report = assess(parse({**VALID, "manufacturer": "-5156"}))
    assert report.product.manufacturer is None
    assert "Производитель" in report.missing_fields


def test_description_without_letters_counts_as_missing():
    report = assess(parse({**VALID, "description": "2435"}))
    assert report.product.description is None
    assert "Описание" in report.missing_fields
    assert report.needs_clarification == []


def test_spec_key_without_letters_is_dropped_and_reported():
    specs = {**VALID["specs"], "321": "543"}
    report = assess(parse({**VALID, "specs": specs}))
    assert "321" not in report.product.specs
    assert [c.field for c in report.needs_clarification] == ["321"]
    assert "без букв" in report.needs_clarification[0].reason


def test_blank_spec_with_letterless_key_is_not_listed_as_missing():
    report = assess(parse({**VALID, "specs": {**VALID["specs"], "321": ""}}))
    assert "321" not in report.missing_fields


def test_numeric_spec_values_under_named_keys_are_kept():
    report = assess(parse({**VALID, "specs": {"количество входов": "8"}}))
    assert report.product.specs == {"количество входов": "8"}


def test_input_with_no_words_except_name_stops_generation():
    garbage = {
        "name": "кавыыавы",
        "manufacturer": "-5156",
        "specs": {"321": "543", "432": "5432"},
        "description": "2435",
    }
    with pytest.raises(InputError) as exc:
        assess(parse(garbage))
    assert exc.value.code == "insufficient_data"
    assert exc.value.status == 422
