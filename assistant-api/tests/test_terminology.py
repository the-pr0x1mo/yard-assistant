import copy
import pytest

from app.terminology import Terminology, load_terminology, normalize_phrase, validate_terminology


def test_dictionary_preserves_user_content_and_free_text_placeholder():
    dictionary = load_terminology()
    assert dictionary.version == 2
    assert len(dictionary.digest) == 64
    terms = dictionary.data["terms"]
    assert terms["note"] == {}
    assert dictionary.hints("temperatura vazduha 18 stepeni").startswith("temperature_c:")
    assert terms["bee_brood_cover"]["supported"] is False
    assert "bee_covered_frames" in terms["bee_brood_cover"]["reason"]
    assert {"ram sa leglom", "ramova sa leglom", "ramovi legla", "ramova legla", "rama legla"} <= set(terms["brood_frames"]["synonyms"])
    assert set(terms["honey_bands"]["values"]) == {"nema", "slabi", "dobri", "jaki"}


@pytest.mark.parametrize("terms", [
    {"invented_field": {}}, {"bee_brood_cover": {}},
    {"brood_frames": {"canonical": "honey_frames"}},
    {"behavior": {"values": {"ljute": ["ljute"]}}},
    {"honey_bands": {"values": {"srednje": ["srednji venac"]}}},
    {"brood_frames": {"values": {"three": ["tri"]}}},
    {"behavior": {"values": {"mirne": ["mirno"], "nervozne": ["МИРНО"]}}},
    {"behavior": {"synonyms": "mirno"}}, {"behavior": {"synonyms": [""]}},
    {"behavior": {"synonyms": [3]}}, {"behavior": {"synonms": []}},
    {"behavior": {"asr_variants": ["mirana"]}},
    {"behavior": {"asr_variants": {"safe": ["mirana"]}}},
    {"behavior": {"serbian": 3}}, {"behavior": {"supported": "false"}},
    {"bee_brood_cover": {"supported": False}},
    {"bee_brood_cover": {"supported": False, "reason": 3}},
    {"bee_brood_cover": {"supported": False, "reason": "unsupported", "canonical": "bee_covered_frames"}},
    {"behavior": {"supported": False, "reason": "actually supported"}},
    {"behavior": {"values": {"mirne": ["mirana"]}, "asr_variants": {"contextual": ["mirana"]}}},
    {"honey_bands": {"values": {"dobri": ["nije los venac"]}, "uncertain": ["nije los venac"]}},
    {"open_brood": {"positive": ["ima larvi"], "unknown": ["ИМА ЛАРВИ"]}},
    {"open_brood": {"positive": ["ima larvi"], "uncertain": ["ima larvi"]}},
    {"behavior": {"asr_variants": {"contextual": ["mirana"], "uncertain": ["mirana"]}}},
    {"behavior": {"note_required": "agresivne"}},
    {"behavior": {"values": {"mirne": ["ponašanje nije provereno"]}, "unknown": ["ponašanje nije provereno"]}},
])
def test_invalid_fields_values_and_dictionary_shapes_are_rejected(terms):
    with pytest.raises(ValueError):
        validate_terminology({"version": 2, "terms": terms})


@pytest.mark.parametrize("data", [[], {}, {"version": True, "terms": {}}, {"version": 0, "terms": {}},
                                       {"version": 2, "terms": []}])
def test_invalid_dictionary_header(data):
    with pytest.raises(ValueError):
        validate_terminology(data)


def test_duplicate_keys_are_not_silently_overwritten(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"version":2,"terms":{"behavior":{},"behavior":{}}}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_terminology(path)


@pytest.mark.parametrize("field,phrase,expected", [
    ("behavior", "ljute", "nervozne"), ("behavior", "ТЕМПЕРАМЕНТ МИРАН!", "mirne"),
    ("behavior", "miran temperament", "mirne"),
    ("honey_bands", "nema venca", "nema"), ("honey_bands", "tanak venac", "slabi"),
    ("honey_bands", "srednji luk", None), ("honey_bands", "dobar venac", "dobri"),
    ("honey_bands", "veliki venac", "jaki"), ("honey_bands", "jak venac", "jaki"),
    ("honey_bands", "nije los venac", None), ("behavior", "nisu mirne", None),
    ("behavior", "temperament mirana", None), ("bee_brood_cover", "pola", None),
])
def test_exact_enum_synonym_normalization(field, phrase, expected):
    assert load_terminology().normalize_value(field, phrase) == expected


def test_hints_preserve_polarity_and_unknown_words_without_creating_facts():
    transcript = "Ларве нисам проверавао. Nema larvi. Maticu nisam tražio. Maticu nisam video."
    hints = load_terminology().hints(transcript)
    assert 'unknown=["larve nisam proveravao"]' in hints
    assert 'negative=["nema larvi"]' in hints
    assert 'unknown=["maticu nisam tražio"]' in hints
    assert 'negative=["maticu nisam video"]' in hints
    assert "honey_bands" not in hints  # A bare 'nema' is not a honey observation.
    assert transcript.startswith("Ларве")


def test_synonyms_and_asr_policies_remain_separate():
    hints = load_terminology().hints("Ima zatvrno glijedla. Matice vidjena, temperament mirana.")
    assert 'asr_uncertain=["zatvrno glijedla"]' in hints
    assert 'asr_contextual=["matice vidjena"]' in hints
    assert 'asr_contextual=["temperament mirana"]' in hints
    assert "zatvrno glijedla" not in load_terminology().data["terms"]["capped_brood"]["synonyms"]


def test_matching_uses_word_boundaries_and_does_not_dump_entire_dictionary():
    dictionary = load_terminology()
    assert dictionary.hints("prelarve larveni mirnovanje") == ""
    hints = dictionary.hints("Tri rama sa leglom.")
    assert hints.startswith("brood_frames:")
    assert "honey_bands" not in hints and "queen_seen" not in hints
    assert len(hints) < 150
    assert normalize_phrase("ПЧЕЛЕ, viđene!") == "pcele vidjene"


def test_dictionary_digest_changes_when_vocabulary_changes():
    original = load_terminology()
    changed = copy.deepcopy(original.data)
    changed["terms"]["brood_frames"]["synonyms"].append("dodatni primer")
    assert Terminology(changed).digest != original.digest
