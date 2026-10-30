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
for number, stem in enumerate(
    ["prv", "drug", "trec", "cetvrt", "pet", "sest", "sedm", "osm", "devet", "deset"], 1
):
    for ending in ("a", "o", "i"):
        NUMBERS[stem + ending] = number

NUMBER_WORDS = "|".join(sorted(NUMBERS, key=len, reverse=True))
NUMBER = rf"(?:h\s*-?\s*\d+|\d+|(?:{NUMBER_WORDS})(?:\s+(?:i\s+)?(?:{NUMBER_WORDS}))?)"
HIVE = r"(?:drustvo|kosnica)"
IDENTIFIER = re.compile(rf"\b{HIVE}\s+(?:broj\s+)?(?P<after>{NUMBER})\b|\b(?P<before>{NUMBER})\s+{HIVE}\b")


def _number(value: str) -> int | None:
    digits = re.fullmatch(r"(?:h\s*-?\s*)?(\d+)", value)
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
    matches = [m.group("after") or m.group("before") for m in IDENTIFIER.finditer(text)]
    matches += re.findall(r"\bh\s*-?\s*\d+\b", text)
    return {f"H{n}" for value in matches if (n := _number(value)) is not None}


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
