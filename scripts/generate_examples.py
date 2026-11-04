"""Генерирует карточки для всех JSON-файлов из папки и печатает итог по каждому запуску.

    python -m scripts.generate_examples
    python -m scripts.generate_examples --input-dir examples/edge_cases --output-dir examples/edge_cases/output --runs 3
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.errors import ServiceError
from app.input_checks import assess, parse_product
from app.llm import create_drafter
from app.pipeline import Drafter, generate_card
from app.render import card_to_markdown


def generate_all(input_dir: Path, output_dir: Path, drafter: Drafter, runs: int) -> list[dict]:
    """Сохраняет результат первого запуска: так пример в репозитории не выбран из лучших."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for path in sorted(input_dir.glob("*.json")):
        assessment = assess(parse_product(path.read_bytes()))
        for run in range(1, runs + 1):
            card = generate_card(assessment, drafter)
            if run == 1:
                data = json.dumps(card.model_dump(), ensure_ascii=False, indent=2) + "\n"
                (output_dir / path.name).write_text(data, encoding="utf-8")
                (output_dir / path.with_suffix(".md").name).write_text(card_to_markdown(card), encoding="utf-8")
            summaries.append(
                {
                    "file": path.name,
                    "run": run,
                    "status": card.status,
                    "title": card.meta.title_length,
                    "description": card.meta.description_length,
                    "attempts": card.meta.attempts,
                    "warnings": len(card.warnings),
                    "clarifications": len(card.needs_clarification),
                }
            )
            print(summaries[-1], flush=True)
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("examples/input"))
    parser.add_argument("--output-dir", type=Path, default=Path("examples/output"))
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    # В консоли Windows кодировка по умолчанию портит кириллицу.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    load_dotenv()
    try:
        generate_all(args.input_dir, args.output_dir, create_drafter(), args.runs)
    except ServiceError as exc:
        print(f"Ошибка: {exc.message}", *exc.details, sep="\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
