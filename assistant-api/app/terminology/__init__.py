"""Validated, versioned vocabulary hints; never rewrites or extracts source facts."""
import json
import re
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from app.normalization import plain_text
from app.schemas import InspectionData

DICTIONARY_PATH = Path(__file__).with_name("sr_beekeeping.json")
PHRASE_LISTS = {"synonyms", "positive", "negative", "unknown", "uncertain", "note_required"}
TERM_KEYS = PHRASE_LISTS | {"canonical", "serbian", "values", "asr_variants", "supported", "reason"}


def normalize_phrase(text: str) -> str:
    """Match accents, Cyrillic and punctuation without changing the transcript."""
    return re.sub(r"[^a-z0-9]+", " ", plain_text(text)).strip()


def _phrases(value, label):
    if not isinstance(value, list) or any(not isinstance(v, str) or not normalize_phrase(v) for v in value):
        raise ValueError(f"{label} must be a list of nonempty phrases")


def validate_terminology(data: dict) -> dict:
    """Check every supported field/value against the current Pydantic contract."""
    if not isinstance(data, dict) or set(data) != {"version", "terms"}:
        raise ValueError("Dictionary requires version and terms")
    if type(data["version"]) is not int or data["version"] < 1 or not isinstance(data["terms"], dict):
        raise ValueError("Invalid dictionary version or terms")
    schema_fields = InspectionData.model_json_schema()["properties"]
    for field, term in data["terms"].items():
        if not isinstance(term, dict) or set(term) - TERM_KEYS:
            raise ValueError(f"Invalid terminology entry: {field}")
        if "supported" in term and type(term["supported"]) is not bool:
            raise ValueError(f"Invalid supported flag: {field}")
        for key in ("canonical", "serbian", "reason"):
            if key in term and (not isinstance(term[key], str) or not term[key].strip()):
                raise ValueError(f"Invalid {field}.{key}")
        if term.get("supported") is False:
            if field in InspectionData.model_fields or not term.get("reason") or set(term) - {"supported", "reason", "serbian"}:
                raise ValueError(f"Unsupported terms need a reason and cannot declare mappings: {field}")
            continue
        if field not in InspectionData.model_fields or term.get("canonical", field) != field:
            raise ValueError(f"Unknown or mismatched canonical field: {field}")
        for key in PHRASE_LISTS & term.keys():
            _phrases(term[key], f"{field}.{key}")
        variants = term.get("asr_variants", {})
        if not isinstance(variants, dict) or set(variants) - {"contextual", "uncertain"}:
            raise ValueError(f"Invalid ASR variants: {field}")
        for kind, phrases in variants.items():
            _phrases(phrases, f"{field}.asr_variants.{kind}")
        values = term.get("values", {})
        if not isinstance(values, dict):
            raise ValueError(f"Invalid enum mappings: {field}")
        enum = next((part["enum"] for part in schema_fields[field].get("anyOf", [])
                     if "enum" in part), None)
        seen = {}
        for value, phrases in values.items():
            if enum is None or value not in enum:
                raise ValueError(f"Invalid enum value: {field}.{value}")
            try:
                InspectionData.model_validate({field: value})
            except ValidationError as exc:
                raise ValueError(f"Invalid schema value: {field}.{value}") from exc
            _phrases(phrases, f"{field}.{value}")
            for phrase in [value, *phrases]:
                normalized = normalize_phrase(phrase)
                if normalized in seen and seen[normalized] != value:
                    raise ValueError(f"Ambiguous synonym in {field}: {phrase}")
                seen[normalized] = value
        trusted = set(seen) | {normalize_phrase(p) for p in term.get("synonyms", [])}
        if "serbian" in term:
            trusted.add(normalize_phrase(term["serbian"]))
        policies = {}
        for kind in ("positive", "negative", "unknown", "uncertain"):
            for phrase in term.get(kind, []):
                normalized = normalize_phrase(phrase)
                if normalized in policies and policies[normalized] != kind:
                    raise ValueError(f"Conflicting observation policies: {field}.{phrase}")
                policies[normalized] = kind
        trusted |= {p for p, kind in policies.items() if kind in {"positive", "negative"}}
        uncertain = term.get("unknown", []) + term.get("uncertain", []) + [
            p for phrases in variants.values() for p in phrases
        ]
        if trusted & {normalize_phrase(p) for p in uncertain}:
            raise ValueError(f"Unknown/uncertain/ASR phrases cannot also be trusted synonyms: {field}")
        if {normalize_phrase(p) for p in variants.get("contextual", [])} & {
            normalize_phrase(p) for p in variants.get("uncertain", [])
        }:
            raise ValueError(f"Conflicting ASR policies: {field}")
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate dictionary key: {key}")
        result[key] = value
    return result


class Terminology:
    def __init__(self, data):
        self.data = validate_terminology(data)
        self.version = data["version"]
        self.digest = sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self._matchers = {}
        for field, term in data["terms"].items():
            if not term or term.get("supported") is False:
                continue
            groups = {"serbian": [term["serbian"]]} if "serbian" in term else {}
            groups.update({kind: term[kind] for kind in (
                "synonyms", "positive", "negative", "unknown", "uncertain", "note_required"
            ) if kind in term})
            groups.update(term.get("values", {}))
            groups.update({f"asr_{kind}": phrases for kind, phrases in term.get("asr_variants", {}).items()})
            # Keep sentence/clause delimiters: "ima. Larvi nema" is not "ima larvi".
            separator = r"[^\w.!?;:,\r\n]+"
            self._matchers[field] = [
                (kind, phrase, re.compile(r"(?<!\w)" + separator.join(
                    re.escape(word) for word in normalize_phrase(phrase).split()
                ) + r"(?!\w)"))
                for kind, phrases in groups.items() for phrase in phrases
            ]

    def normalize_value(self, field: str, phrase: str) -> str | None:
        """Resolve an exact, trusted enum synonym only; this is not a fact extractor."""
        term = self.data["terms"].get(field, {})
        normalized = normalize_phrase(phrase)
        for value, phrases in term.get("values", {}).items():
            if normalized in {normalize_phrase(p) for p in [value, *phrases]}:
                return value
        return None

    def hints(self, transcript: str) -> str:
        """Select vocabulary, retaining longer policies and separate occurrences.

        This is phrase selection, not a clause parser or an evidence classifier.
        A negation not listed in the resource still needs model interpretation.
        """
        text = plain_text(transcript)
        lines = []
        for field, matchers in self._matchers.items():
            matches = [(kind, phrase, match.start(), match.end())
                       for kind, phrase, pattern in matchers for match in pattern.finditer(text)]
            selected = {}
            for kind, phrase, start, end in matches:
                # Notes may accompany an enum (e.g. strong aggression). Otherwise a
                # longer phrase suppresses its inner synonyms at this occurrence.
                if any(other_start <= start and end <= other_end
                       and (other_end - other_start > end - start
                            or (other_start == start and other_end == end
                                and kind in {"serbian", "synonyms"}
                                and other_kind not in {"serbian", "synonyms"}))
                       and (kind == "note_required") == (other_kind == "note_required")
                       for other_kind, _, other_start, other_end in matches):
                    continue
                selected.setdefault(kind, {})[phrase] = None
            if selected:
                lines.append(f"{field}: " + "; ".join(
                    f"{kind}={json.dumps(list(phrases), ensure_ascii=False, separators=(',', ':'))}"
                    for kind, phrases in selected.items()))
        return "\n".join(lines)


@lru_cache(maxsize=4)
def load_terminology(path: Path = DICTIONARY_PATH) -> Terminology:
    return Terminology(json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object))
