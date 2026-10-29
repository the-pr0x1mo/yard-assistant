"""Deterministic Serbian hive numbering; ambiguity never selects a random hive."""
import re
import unicodedata

CYRILLIC = dict(zip(
    "абвгдђежзијклљмнњопрстћуфхцчџш",
    ["a", "b", "v", "g", "d", "dj", "e", "z", "z", "i", "j", "k", "l", "lj",
     "m", "n", "nj", "o", "p", "r", "s", "t", "c", "u", "f", "h", "c", "c", "dz", "s"],
))


def plain_text(text: str) -> str:
    text = "".join(CYRILLIC.get(c, c) for c in text.lower()).replace("đ", "dj")
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


NUMBERS = {"jedan": 1, "jedna": 1, "jedno": 1, "dva": 2, "dve": 2,
           "tri": 3, "cetiri": 4, "pet": 5, "sest": 6, "sedam": 7,
           "osam": 8, "devet": 9, "deset": 10, "jedanaest": 11,
           "dvanaest": 12, "trinaest": 13, "cetrnaest": 14, "petnaest": 15,
           "sesnaest": 16, "sedamnaest": 17, "osamnaest": 18, "devetnaest": 19,
           "dvadeset": 20, "trideset": 30, "cetrdeset": 40, "pedeset": 50,
           "sezdeset": 60, "sedamdeset": 70, "osamdeset": 80, "devedeset": 90,
           "sto": 100}
ORDINALS = {}
for number, stem in enumerate(
    ["prv", "drug", "trec", "cetvrt", "pet", "sest", "sedm", "osm", "devet", "deset"], 1
):
    for ending in ("a", "o", "i", "u", "e", "og", "oga", "om", "ome", "oj",
                   "eg", "ega", "em", "emu"):
        ORDINALS[stem + ending] = number
NUMBERS.update(ORDINALS)

NUMBER_WORDS = "|".join(sorted(NUMBERS, key=len, reverse=True))
ORDINAL_WORDS = "|".join(sorted(ORDINALS, key=len, reverse=True))
H_NUMBER = r"h\s*[-‐‑–—]?\s*\d+"
TENS = "|".join(word for word, n in NUMBERS.items() if 20 <= n < 100 and n % 10 == 0)
UNITS = "|".join(sorted((word for word, n in NUMBERS.items() if n < 10), key=len, reverse=True))
COMPOUND = rf"(?:{TENS})\s+(?:i\s+)?(?:{UNITS})"
NUMBER = rf"(?:{H_NUMBER}|\d+|{COMPOUND}|{NUMBER_WORDS})"
# Singular case forms, including accusative (opening a hive) and locative.
HIVE = r"(?:drustv(?:o|a|u|om)|kosnic(?:a|u|e|i|om))"
# A cardinal before the noun is a count ("tri društva"), not a label.
ORDINAL = rf"(?:\d+\.|(?:(?:{TENS})\s+(?:i\s+)?)?(?:{ORDINAL_WORDS}))"
AFTER_IDENTIFIER = rf"\b{HIVE}\s+(?:broj\s+)?(?P<after>{NUMBER})\b"
BEFORE_IDENTIFIER = rf"\b(?P<before>{ORDINAL})\s+{HIVE}\b"
IDENTIFIER = re.compile(AFTER_IDENTIFIER + "|" + BEFORE_IDENTIFIER)
ADDITIONAL_ID = re.compile(rf"(?:\s+(?:i|ili)\s+|\s*[,/–—-]\s*)(?P<number>{NUMBER})\b")
ORDINAL_LIST = re.compile(
    rf"\b(?P<list>{ORDINAL}(?:(?:\s+(?:i|ili)\s+|\s*,\s*){ORDINAL})+)\s+{HIVE}\b"
)
UNPARSED_NUMBER = re.compile(rf"\s+(?:{NUMBER_WORDS}|\d+)\b")
MEASUREMENT = re.compile(
    r"\s*(?:°\s*c\b|%|(?:ram(?:a|ova|ovi)?|ulic(?:a|e|u)|stepen\w*|celzij\w*|"
    r"c|kg|g|ml|l|dana?|dan|godin\w*|sati?|minut\w*|pcel\w*)\b)"
)
DATE_MONTH = re.compile(
    r"\.?\s*(?:januar\w*|februar\w*|mart\w*|april\w*|maj\w*|jun\w*|jul\w*|"
    r"avgust\w*|septemb\w*|oktob\w*|novemb\w*|decemb\w*)\b"
)


def _number(value: str) -> int | None:
    digits = re.fullmatch(r"(?:h\s*[-‐‑–—]?\s*)?(\d+)\.?", value)
    if digits:
        number = int(digits.group(1))
        return number if number > 0 else None
    parts = [p for p in value.split() if p != "i"]
    if len(parts) == 1:
        return NUMBERS.get(parts[0])
    if len(parts) == 2:
        a, b = (NUMBERS.get(p, 0) for p in parts)
        if a >= 20 and a % 10 == 0 and 0 < b < 10:
            return a + b
    return None


def transcript_hive_ids(transcript: str) -> set[str]:
    text = plain_text(transcript)
    ids = set()

    def add(value, end):
        # Adjacent units/dates distinguish "u košnici 3 rama" from "košnicu 3".
        # Never take the integer prefix of a decimal, date or time as an ID.
        tail = text[end:]
        if re.match(r"[.,:]\d", tail):
            return False
        if not value.startswith("h") and (
            MEASUREMENT.match(tail) or DATE_MONTH.match(tail) or UNPARSED_NUMBER.match(tail)
        ):
            return False
        if (number := _number(value)) is not None:
            ids.add(f"H{number}")
            return True
        return False

    def add_after(value, end):
        if not add(value, end):
            return
        # A shared noun still identifies multiple hives: "košnice 1 i 2".
        while (additional := ADDITIONAL_ID.match(text, end)) is not None:
            add(additional.group("number"), additional.end())
            end = additional.end()

    # Scan both orders independently so overlapping references cannot hide a conflict
    # (e.g. "treća košnica broj četiri").
    for match in re.finditer(AFTER_IDENTIFIER, text):
        add_after(match.group("after"), match.end())
    for match in re.finditer(BEFORE_IDENTIFIER, text):
        value = match.group("before")
        if value[0].isdigit():
            prefix = text[:match.start("before")]
            # "unos polena 2 od 3. Košnica je teška" ends a scale, not H3.
            if not re.search(r"(?:^|[.!?;:\n])\s*$|\b(?:otvaram|pregledam|pregled|u|na|iz|kod)\s+$", prefix):
                continue
        add(value, match.end("before"))
    for match in ORDINAL_LIST.finditer(text):
        for ordinal in re.finditer(rf"\b{ORDINAL}(?=\s|,|$)", match.group("list")):
            number = _number(ordinal.group())
            if number is not None:
                ids.add(f"H{number}")
    for match in re.finditer(rf"\b{H_NUMBER}\b", text):
        add_after(match.group(), match.end())
    return ids


def normalize_hive_id(value) -> str:
    if value is None or value == "UNKNOWN":
        return "UNKNOWN"
    if not isinstance(value, str):
        raise ValueError("Hive identifier must be text or null")
    text = plain_text(value.strip())
    number = _number(text)
    if number:
        return f"H{number}"
    matches = list(IDENTIFIER.finditer(text))
    if len(matches) == 1 and matches[0].span() == (0, len(text)):
        number = _number(matches[0].group("after") or matches[0].group("before"))
        if number:
            return f"H{number}"
    raise ValueError("Unrecognized hive identifier")
