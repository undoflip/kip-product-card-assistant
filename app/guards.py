"""Детерминированные проверки ответа модели: длины, значения, неподтверждённые утверждения."""

import re

from app.schemas import ExtractedSpec, LLMDraft, ProductInput

TITLE_MAX = 70
DESCRIPTION_MIN = 800
DESCRIPTION_MAX = 1200
QUERIES_MIN = 3
QUERIES_MAX = 5

# Подписи понятны и менеджеру в предупреждениях, и модели при повторе.
TITLE_LABEL = "SEO-заголовок (seo_title)"
DESCRIPTION_LABEL = "SEO-описание (seo_description)"
QUERIES_LABEL = "Поисковые запросы (search_queries)"
COMMERCIAL_LABEL = "Блок для менеджера (commercial)"

NUMBER = r"\d+(?:\.\d+)?"
# (?<!\d) не даёт начинать разбор с середины числа: иначе длинная строка цифр обрабатывается за квадратичное время.
NUMBER_WITH_WORD = re.compile(rf"(?<!\d)({NUMBER})\s*([a-zа-я°%][a-zа-я0-9/²°]*|%)")
RANGE_WITH_WORD = re.compile(
    rf"(?<!\d)({NUMBER})\s*(?:-|\.\.\.|…|до)\s*\+?-?{NUMBER}\s*([a-zа-я°%][a-zа-я0-9/²°]*|%)"
)
MODEL_TOKEN = re.compile(r"[a-zа-я0-9./-]+")
LATIN_OR_DIGIT = re.compile(r"[a-z0-9]")

# Однобуквенные единицы (в, а, м, с, г) намеренно не сравниваются парой:
# «DM 02 в корпусе» неотличимо от вольт. Для них работает проверка самого числа.
UNIT_ALIASES = {
    "мпа": ("мпа", "mpa"),
    "кпа": ("кпа", "kpa"),
    "па": ("па", "pa"),
    "бар": ("бар", "бара", "баров", "bar"),
    "атм": ("атм",),
    "кгс/см2": ("кгс/см2", "кгс/см²"),
    "мм": ("мм", "mm"),
    "см": ("см", "cm"),
    "мкм": ("мкм",),
    "кг": ("кг", "kg"),
    "ма": ("ма", "ma"),
    "мв": ("мв", "mv"),
    "вт": ("вт",),
    "квт": ("квт", "kw"),
    "гц": ("гц", "hz"),
    "кгц": ("кгц",),
    "ом": ("ом",),
    "мс": ("мс",),
    "мин": ("мин",),
    "%": ("%",),
    "°c": ("°c", "°с"),
}
UNITS = {alias: unit for unit, aliases in UNIT_ALIASES.items() for alias in aliases}
# fmt: off
UNIT_WORD_STEMS = {
    "мегапаскал": "мпа", "килопаскал": "кпа", "паскал": "па", "миллиметр": "мм",
    "сантиметр": "см", "килограмм": "кг", "миллиампер": "ма", "процент": "%",
}
# fmt: on

# Утверждения, которые нельзя писать без подтверждения во входных данных.
UNCONFIRMED_CLAIMS = {
    "ГОСТ": r"гост",
    "ТУ": r"\bту\b",
    "степень защиты IP": r"\bip\s?\d",
    "интерфейс RS-485": r"rs-?\s?485",
    "интерфейс RS-232": r"rs-?\s?232",
    "протокол Modbus": r"modbus",
    "протокол HART": r"\bhart\b",
    "Profibus/Profinet": r"profibus|profinet",
    "Ethernet": r"ethernet",
    "USB": r"\busb\b",
    "беспроводная связь": r"bluetooth|wi-?fi",
    "материал: нержавеющая сталь": r"нержаве",
    "материал: латунь": r"латун",
    "материал: бронза": r"бронз",
    "материал: алюминий": r"алюмин",
    "взрывозащита": r"взрывозащищ|взрывобезопас|\bex\b",
    "пыле- и влагозащита": r"пылезащищ|влагозащищ|герметичн",
    "виброустойчивость": r"виброустойчив|вибростойк",
    "агрессивные среды": r"\bагрессивн",
    "сертификация": r"сертифик|декларац",
    "Госреестр СИ": r"госреестр|реестр\w* средств",
    "поверка": r"поверк|поверо",
    "гарантия": r"гаранти",
    "срок службы": r"срок\w* службы",
    "происхождение": r"отечественн|российск\w+ производ",
    "оценка точности": r"высок\w* точност",
}
NO_DATA_PHRASE = re.compile(r"данных нет|нет данных")


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е").replace("\u00a0", " ")
    text = re.sub(r"[–—−]", "-", text)
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _canonical_unit(word: str) -> str | None:
    if word in UNITS:
        return UNITS[word]
    return next((unit for stem, unit in UNIT_WORD_STEMS.items() if word.startswith(stem)), None)


def _value_pairs(text: str) -> set[tuple[str, str]]:
    pairs = set()
    for pattern in (NUMBER_WITH_WORD, RANGE_WITH_WORD):
        for number, word in pattern.findall(text):
            unit = _canonical_unit(word)
            if unit:
                pairs.add((number, unit))
    return pairs


def _source_text(product: ProductInput) -> str:
    parts = [product.name, product.manufacturer, product.description]
    parts += [f"{key} {value}" for key, value in product.specs.items()]
    return normalize(" \n ".join(part for part in parts if part))


def _generated_fields(draft: LLMDraft) -> dict[str, str]:
    return {
        TITLE_LABEL: draft.seo_title,
        DESCRIPTION_LABEL: draft.seo_description,
        QUERIES_LABEL: " ; ".join(draft.search_queries),
        COMMERCIAL_LABEL: f"{draft.commercial.audience} {draft.commercial.tasks}",
    }


def chars(count: int) -> str:
    last_two, last = count % 100, count % 10
    if last == 1 and last_two != 11:
        return f"{count} символ"
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return f"{count} символа"
    return f"{count} символов"


def _check_shape(draft: LLMDraft) -> list[str]:
    problems = []
    title = len(draft.seo_title.strip())
    if not 0 < title <= TITLE_MAX:
        problems.append(f"{TITLE_LABEL}: {chars(title)}, допустимо до {TITLE_MAX}.")
    length = len(draft.seo_description.strip())
    if length < DESCRIPTION_MIN:
        problems.append(
            f"{DESCRIPTION_LABEL}: {chars(length)}, нужно {DESCRIPTION_MIN}–{DESCRIPTION_MAX}. "
            f"Добавьте минимум {chars(DESCRIPTION_MIN - length)} без новых фактов."
        )
    elif length > DESCRIPTION_MAX:
        problems.append(
            f"{DESCRIPTION_LABEL}: {chars(length)}, нужно {DESCRIPTION_MIN}–{DESCRIPTION_MAX}. "
            f"Сократите минимум на {chars(length - DESCRIPTION_MAX)}."
        )
    queries = [normalize(query) for query in draft.search_queries]
    if not QUERIES_MIN <= len(queries) <= QUERIES_MAX:
        problems.append(
            f"{QUERIES_LABEL}: получено {len(queries)}, нужно {QUERIES_MIN}–{QUERIES_MAX}."
        )
    if "" in queries or len(set(queries)) != len(queries):
        problems.append(f"{QUERIES_LABEL}: есть пустые или повторяющиеся запросы.")
    if not draft.commercial.audience.strip() or not draft.commercial.tasks.strip():
        problems.append(f"{COMMERCIAL_LABEL}: нужно заполнить и audience, и tasks.")
    return problems


def _check_facts(draft: LLMDraft, product: ProductInput) -> list[str]:
    source = _source_text(product)
    source_numbers = set(re.findall(NUMBER, source))
    source_pairs = _value_pairs(source)
    problems = []
    for field, raw in _generated_fields(draft).items():
        text = normalize(raw)
        pairs = _value_pairs(text)
        for number, unit in sorted(pairs - source_pairs):
            problems.append(f"{field}: значения «{number} {unit}» нет во входных данных.")
        paired = {number for number, _ in pairs}
        unknown_numbers = sorted(set(re.findall(NUMBER, text)) - source_numbers - paired)
        problems.extend(
            f"{field}: числа «{number}» нет во входных данных." for number in unknown_numbers
        )
        for label, pattern in UNCONFIRMED_CLAIMS.items():
            if re.search(pattern, text) and not re.search(pattern, source):
                problems.append(f"{field}: утверждение «{label}» не подтверждено входными данными.")
    for field, raw in ((TITLE_LABEL, draft.seo_title), (DESCRIPTION_LABEL, draft.seo_description)):
        if NO_DATA_PHRASE.search(normalize(raw)):
            problems.append(f"{field}: в публичном тексте не должно быть фразы «данных нет».")
    title = normalize(draft.seo_title)
    # В скобках и после них в названиях из каталога идут параметры исполнения, а не обозначение модели.
    model_tokens = MODEL_TOKEN.findall(normalize(product.name or "").split("(")[0])
    problems.extend(
        f"{TITLE_LABEL}: обозначение модели «{token}» нужно написать как во входных данных."
        for token in model_tokens
        if LATIN_OR_DIGIT.search(token) and token not in title
    )
    return problems


def check_draft(draft: LLMDraft, product: ProductInput) -> list[str]:
    """Возвращает список нарушений. Пустой список — черновик прошёл все проверки."""
    return _check_shape(draft) + _check_facts(draft, product)


def verify_extracted(
    specs: list[ExtractedSpec], product: ProductInput
) -> tuple[list[ExtractedSpec], list[str]]:
    """Оставляет только характеристики, чьё значение дословно подтверждается описанием."""
    description = normalize(product.description or "")
    verified, rejected = [], []
    for spec in specs:
        quote, value = normalize(spec.quote), normalize(spec.value)
        if quote and value and quote in description and value in quote:
            verified.append(spec)
        else:
            rejected.append(
                f"Характеристика «{spec.name}» отброшена: значение не подтверждено описанием."
            )
    return verified, rejected
