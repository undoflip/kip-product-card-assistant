import json

from scripts.generate_examples import generate_all
from tests.helpers import FakeDrafter, make_draft

PRODUCT = {
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


def write_input(directory, name="product.json", data=None):
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(json.dumps(data or PRODUCT, ensure_ascii=False), encoding="utf-8")


def test_writes_json_and_markdown_for_each_input(tmp_path):
    write_input(tmp_path / "in")
    summaries = generate_all(tmp_path / "in", tmp_path / "out", FakeDrafter(make_draft()), runs=1)
    card = json.loads((tmp_path / "out" / "product.json").read_text(encoding="utf-8"))
    assert card["status"] == "ok"
    assert (tmp_path / "out" / "product.md").read_text(encoding="utf-8").startswith("# Манометр")
    assert summaries[0]["status"] == "ok"
    assert summaries[0]["file"] == "product.json"


def test_several_runs_report_each_but_save_the_first(tmp_path):
    write_input(tmp_path / "in")
    first = make_draft(seo_title="Манометр показывающий DM 02 первый")
    second = make_draft(seo_title="Манометр показывающий DM 02 второй")
    summaries = generate_all(tmp_path / "in", tmp_path / "out", FakeDrafter(first, second), runs=2)
    assert [summary["run"] for summary in summaries] == [1, 2]
    card = json.loads((tmp_path / "out" / "product.json").read_text(encoding="utf-8"))
    assert card["seo_title"] == first.seo_title


def test_summary_counts_warnings(tmp_path):
    write_input(tmp_path / "in")
    bad = make_draft(seo_title="Манометр показывающий DM 02 на 16 бар")
    summaries = generate_all(tmp_path / "in", tmp_path / "out", FakeDrafter(bad, bad, bad), runs=1)
    assert summaries[0]["status"] == "needs_attention"
    assert summaries[0]["warnings"] > 0
    assert summaries[0]["attempts"] == 3
