"""Exercise vocabulary selection and exact normalization, without model claims."""
import json

import pytest

from app import services
from app.schemas import InspectionData
from app.terminology import Terminology, load_terminology


def field_hint(field, transcript):
    return next((line for line in load_terminology().hints(transcript).splitlines()
                 if line.startswith(f"{field}:")), "")


@pytest.mark.parametrize("field,transcript,kind", [
    ("temperature_c", "Temperatura vazduha 18,5 stepeni.", "serbian"),
    ("days_since_last_inspection", "Sedam dana od prethodnog pregleda.", "synonyms"),
    ("inspection_type", "Danas je kompletan pregled.", "potpuni"),
    ("bee_streets", "Osam zauzetih ulica.", "synonyms"),
    ("bee_covered_frames", "Šest ramova pokrivenih pčelama.", "synonyms"),
    ("beekeeper_strength", "Društvo je srednje jako.", "srednje"),
    ("weight_class", "Košnica je srednje teška.", "srednja"),
    ("brood_frames", "Pet ramova s leglom.", "synonyms"),
    ("open_brood", "Видео сам ларве.", "positive"),
    ("capped_brood", "Ima poklopljenog legla.", "positive"),
    ("brood_pattern", "Leglo je rastrkano.", "rastrkano"),
    ("queen_seen", "Nasao sam maticu.", "positive"),
    ("eggs_seen", "Ima jajasaca.", "positive"),
    ("queen_cells", "Ima zapocetih maticnjaka.", "zapoceti"),
    ("honey_frames", "Pet ramova s medom.", "synonyms"),
    ("pollen_frames", "Pet ramova sa pergom.", "synonyms"),
    ("reserves_estimate", "Zalihe su dovoljne.", "dovoljno"),
    ("pollen_intake", "Unos polena ocenjen 2 od 3.", "synonyms"),
    ("behavior", "Pčele su uznemirene.", "nervozne"),
    ("flight_activity", "Let ocenjen 4 od 5.", "synonyms"),
    ("dead_bees_front", "Nekoliko mrtvih pčela ispred košnice.", "malo"),
    ("free_space", "Previše slobodnog prostora.", "previse"),
    ("swarm_signs", "Društvo ima rojevni nagon.", "positive"),
    ("varroa_level", "Srednji nivo varoe.", "srednje"),
    ("deformed_bees", "Video sam pčele sa deformisanim krilima.", "positive"),
    ("diarrhea", "Vidljivi tragovi proliva.", "positive"),
    ("humidity_issue", "Ima kondenzacije u košnici.", "positive"),
    ("super_added", "Stavio sam nastavak.", "positive"),
    ("foundation_added", "Dodao sam jednu satnu osnovu.", "positive"),
    ("actions_taken", "Prihranio sam društvo.", "positive"),
    ("trend_flight", "Let se pojačava.", "raste"),
    ("trend_weight", "Košnica gubi na težini.", "gubi"),
])
def test_field_vocabulary_selects_relevant_policy(field, transcript, kind):
    assert f"{kind}=" in field_hint(field, transcript)
    prompt = services.build_system_prompt(transcript)
    assert field_hint(field, transcript) in prompt


@pytest.mark.parametrize("field,phrase,value", [
    ("inspection_type", "pregled spolja", "spoljni"),
    ("inspection_type", "kratak pregled", "brzi"),
    ("weight_class", "КОШНИЦА ЈЕ ВЕОМА ТЕШКА", "vrlo_teska"),
    ("beekeeper_strength", "vrlo jako drustvo", "veoma_jako"),
    ("brood_pattern", "šareno leglo", "rastrkano"),
    ("queen_cells", "poklopljeni maticnjaci", "zatvoreni"),
    ("queen_cells", "nema matičnjaka", "nema"),
    ("reserves_estimate", "ZALIHE SU NISKE!", "nisko"),
    ("free_space", "nema slobodnog prostora", "nema"),
    ("dead_bees_front", "nema mrtvih pčela ispred košnice", "0"),
    ("varroa_level", "мало варое", "malo"),
    ("trend_flight", "let je nepromenjen", "isto"),
    ("trend_weight", "težina raste", "dobija"),
    ("honey_bands", "nema mednog venca", "nema"),
    ("honey_bands", "tanak medni venac", "slabi"),
    ("honey_bands", "dobar medni venac", "dobri"),
    ("honey_bands", "veliki medni venac", "jaki"),
])
def test_completed_enum_vocabulary_normalizes_to_schema(field, phrase, value):
    result = load_terminology().normalize_value(field, phrase)
    assert result == value
    assert getattr(InspectionData.model_validate({field: result}), field) == value
    assert f"{value}=" in field_hint(field, phrase)


@pytest.mark.parametrize("field,absent,unchecked,kind", [
    ("open_brood", "Nema larvi", "Larve nisam proveravao", "negative"),
    ("capped_brood", "Nema poklopljenog legla", "Zatvoreno leglo nije provereno", "negative"),
    ("queen_seen", "Maticu nisam video", "Maticu nisam tražio", "negative"),
    ("eggs_seen", "Nema jajašaca", "Jaja nisu proverena", "negative"),
    ("queen_cells", "Nema matičnjaka", "Nisam proverio matičnjake", "nema"),
    ("swarm_signs", "Nema rojevnog nagona", "Znake rojenja nisam proveravao", "negative"),
    ("varroa_level", "Nema varoe", "Varou nisam proveravao", "nema"),
    ("deformed_bees", "Nema deformisanih pčela", "Deformisane pčele nisam proveravao", "negative"),
    ("diarrhea", "Nema tragova proliva", "Proliv nisam proveravao", "negative"),
    ("humidity_issue", "Nema problema sa vlagom", "Vlagu nisam proveravao", "negative"),
    ("super_added", "Nastavak nisam dodao", "Treba dodati nastavak", "negative"),
    ("foundation_added", "Nisam dodao satne osnove", "Treba dodati satne osnove", "negative"),
])
def test_absence_and_unverified_selection_stay_distinct(field, absent, unchecked, kind):
    absence_hint = field_hint(field, absent)
    assert f"{kind}=" in absence_hint
    unknown_hint = field_hint(field, unchecked)
    assert "unknown=" in unknown_hint
    assert "positive=" not in unknown_hint
    assert "negative=" not in unknown_hint
    assert load_terminology().normalize_value(field, unchecked) is None


@pytest.mark.parametrize("phrase", [
    "srednji venac", "srednji luk", "srednji medni venac", "osrednji venac",
    "los venac", "nije los venac", "venac je prisutan",
])
def test_descriptive_honey_bands_do_not_acquire_an_assessment(phrase):
    assert load_terminology().normalize_value("honey_bands", phrase) is None
    hint = field_hint("honey_bands", phrase)
    assert "uncertain=" in hint
    assert all(f"{value}=" not in hint for value in ("nema", "slabi", "dobri", "jaki"))


def test_longer_phrases_suppress_inner_values_at_each_occurrence():
    assert 'veoma_jako=["vrlo jako društvo"]' in field_hint("beekeeper_strength", "Vrlo jako društvo")
    assert '; jako=' not in field_hint("beekeeper_strength", "Vrlo jako društvo")
    hint = field_hint("open_brood", "Nisam siguran da ima larvi")
    assert "unknown=" in hint and "positive=" not in hint
    hint = field_hint("open_brood", "Nisam siguran da ima larvi. Ima larvi.")
    assert "unknown=" in hint and "positive=" in hint
    # Keep separate phrases for model interpretation; do not resolve contradictions here.
    hint = field_hint("open_brood", "Ima larvi. Nema larvi.")
    assert "positive=" in hint and "negative=" in hint


@pytest.mark.parametrize("boundary", [".", ",", ";", ":", "!", "?", "\n"])
def test_phrase_matching_cannot_cross_a_clause_boundary(boundary):
    assert "positive=" not in field_hint("open_brood", f"Ima{boundary} larvi nema.")


def test_substrings_and_unrelated_words_do_not_select_vocabulary():
    assert load_terminology().hints("prelarve larveni mirnovanje matičar grabežljiv") == ""
    assert "queen_seen" not in load_terminology().hints("Matičnjaci su zatvoreni.")
    assert "varroa_level" not in load_terminology().hints("Nema larvi.")


@pytest.mark.parametrize("phrase", ["ljute", "agresivne", "izrazito agresivne"])
def test_aggression_uses_closest_enum_and_requires_source_note(phrase):
    assert load_terminology().normalize_value("behavior", phrase.split()[-1]) == "nervozne"
    hint = field_hint("behavior", f"Pčele su {phrase}.")
    assert 'nervozne=' in hint and f'note_required=["{phrase}"]' in hint
    assert 'note_required=' not in field_hint("behavior", "Pčele su nervozne.")


def test_queen_vocabulary_is_not_evidence_and_eggs_do_not_select_queen_hint():
    assert field_hint("queen_seen", "Matica.") == 'queen_seen: synonyms=["matica"]'
    assert field_hint("queen_seen", "Ima jaja i larvi.") == ""
    assert "positive=" not in field_hint("queen_seen", "Možda sam video maticu.")
    assert "positive=" not in field_hint("queen_seen", "Nisam siguran da sam video maticu.")


@pytest.mark.parametrize("field,phrase", [
    ("varroa_level", "ima varoe"), ("varroa_level", "tretirano protiv varoe"),
    ("pollen_intake", "slab unos polena"), ("pollen_intake", "nema unosa polena"),
    ("flight_activity", "nema izleta"), ("diarrhea", "mrlje na letu"),
    ("humidity_issue", "buđ na ramu"), ("foundation_added", "dodao sam satne osnove"),
    ("inspection_type", "detaljan pregled"),
])
def test_descriptions_without_schema_equivalent_remain_unclassified(field, phrase):
    assert load_terminology().normalize_value(field, phrase) is None
    assert "uncertain=" in field_hint(field, phrase)


def test_bare_varroa_and_treatment_establish_no_severity_mapping():
    hint = field_hint("varroa_level", "Obavio sam tretman protiv varoe.")
    assert 'synonyms=["varoe"]' in hint
    assert not any(f"{value}=" in hint for value in ("nema", "malo", "srednje", "jako"))
    assert "positive=" in field_hint("actions_taken", "Obavio sam tretman protiv varoe.")
    assert "unknown=" in field_hint("actions_taken", "Planiram tretman protiv varoe.")


def test_completed_addition_and_intention_select_different_policies():
    assert "positive=" in field_hint("super_added", "Dodao sam nastavak.")
    hint = field_hint("super_added", "Planiram da dodam nastavak.")
    assert "unknown=" in hint and "positive=" not in hint


def test_unsupported_brood_coverage_and_free_text_round_trip_without_new_field():
    phrase = "Pčele pokrivaju pola legla"
    assert load_terminology().normalize_value("bee_brood_cover", phrase) is None
    assert field_hint("bee_covered_frames", phrase) == ""
    raw = {"hive": {"hive_id": "H1"}, "inspection": {"note": phrase}}
    payload = services.parse_payload(json.dumps(raw), f"Košnica 1. {phrase}")
    assert payload.inspection.note == phrase
    assert payload.inspection.bee_covered_frames is None
    raw["inspection"]["bee_brood_cover"] = 0.5
    with pytest.raises(ValueError):
        services.parse_payload(json.dumps(raw), "Košnica 1.")


def test_empty_placeholder_is_valid_and_emits_no_hints():
    dictionary = Terminology({"version": 2, "terms": {"temperature_c": {}, "note": {}}})
    assert dictionary.hints("Temperatura vazduha 15 stepeni.") == ""
    assert dictionary.normalize_value("temperature_c", "stepeni") is None


def test_absent_flags_selects_only_the_observations_actually_mentioned():
    text = ("Košnica 6. Nema deformisanih pčela, nema proliva, nema problema sa vlagom. "
            "Nema znakova rojenja. Nastavak nisam dodao.")
    hints = load_terminology().hints(text)
    assert {line.split(":", 1)[0] for line in hints.splitlines()} == {
        "deformed_bees", "diarrhea", "humidity_issue", "swarm_signs", "super_added"}
    assert all(": negative=" in line for line in hints.splitlines())
    # Independent observations keep their own policies in the presence of negatives.
    assert 'positive=["ima larvi"]' in field_hint("open_brood", text + " Ima larvi.")
    assert 'positive=["matica viđena"]' in field_hint("queen_seen", text + " Matica viđena.")
    assert "negative=" not in field_hint("queen_seen", text + " Maticu nisam tražio.")


@pytest.mark.parametrize("field,phrase,kind", [
    ("capped_brood", "zatvoranog legla", "asr_uncertain"),
    ("eggs_seen", "zasijanog", "uncertain"),
    ("queen_seen", "makica vidjena", "asr_uncertain"),
])
def test_log2_asr_uncertainty_is_not_a_positive_or_negative_observation(field, phrase, kind):
    hint = field_hint(field, phrase)
    assert f'{kind}=["{phrase}"]' in hint
    assert "positive=" not in hint and "negative=" not in hint
    assert load_terminology().normalize_value(field, phrase) is None
