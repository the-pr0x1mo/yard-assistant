"""Hive assignment must be supported by transcript evidence, never a model guess."""
import json

import pytest

from app import db, services
from app.normalization import normalize_hive_id, transcript_hive_ids
from app.pipeline import process_log


@pytest.mark.parametrize("text,expected", [
    ("Košnica 3", "H3"),
    ("Otvaram košnicu 3", "H3"),
    ("Celzijos ovih otvaram košnicu 3.", "H3"),
    ("Košnica broj tri", "H3"),
    ("Treće društvo", "H3"),
    ("Pregledam društvo H3", "H3"),
    ("Otvaram treću košnicu", "H3"),
    ("U trećoj košnici ima larvi", "H3"),
    ("Pregled trećeg društva", "H3"),
    ("U društvu broj tri ima larvi", "H3"),
    ("Radim sa društvom 3", "H3"),
    ("У кошници број три има ларви.", "H3"),
    ("Отварам трећу кошницу.", "H3"),
    ("H3", "H3"), ("H 3", "H3"), ("H-003", "H3"), ("H–3", "H3"),
    ("3. društvo", "H3"),
    ("Otvaram 3. košnicu", "H3"),
    ("Dvadeset treća košnica", "H23"),
    ("Košnicu broj trideset i dva", "H32"),
])
def test_explicit_serbian_hive_references(text, expected):
    assert transcript_hive_ids(text) == {expected}


@pytest.mark.parametrize("label", ["košnicu broj tri", "treću košnicu", "trećeg društva", "H–3"])
def test_model_label_canonicalization_uses_same_numbering(label):
    assert normalize_hive_id(label) == "H3"


@pytest.mark.parametrize("text", [
    "Danas nema novosti.",
    "Danas je 29. oktobar 2026. Temperatura 23°C. Tri rama sa leglom, četiri sa medom.",
    "U košnici 3 rama sa leglom i 4 rama sa medom.",
    "U društvu 3 ulice pčela.",
    "U košnici 23°C. Pregled pre 7 dana.",
    "U košnici 23 stepena Celzijusa.",
    "Košnica 23,5 stepeni.",
    "Košnica 29.10.2026. Pregled u 14:30.",
    "Košnica 29. oktobar 2026.",
    "Imam tri društva i 4 košnice.",
    "23 stepena, 3 rama legla, 4 rama meda, 2 dana od pregleda.",
    "Unos polena 2 od 3. Košnica je teška.",
    "Danas je 29. Košnica je teška.",
    "Košnica 3,4.",
    "Košnica sto tri.",
    "Košnica dvadeset jedanaest.",
])
def test_other_numbers_never_verify_a_model_guess(text):
    assert transcript_hive_ids(text) == set()
    payload = services.parse_payload('{"hive":{"hive_id":"H1"},"inspection":{}}', text)
    assert payload.hive.hive_id == "UNKNOWN"


@pytest.mark.parametrize("text", [
    "Košnica 3 i košnica 4.",
    "Košnicu 3 ili društvo H4.",
    "Košnice 3 i 4.",
    "Društva tri ili četiri.",
    "Košnice 3, 4.",
    "Košnice 3-4.",
    "H3 ili 4.",
    "Treća i četvrta košnica.",
    "Treće ili četvrto društvo.",
    "Treća košnica broj četiri.",
])
def test_multiple_or_alternative_identifiers_remain_unknown(text):
    assert transcript_hive_ids(text) == {"H3", "H4"}
    payload = services.parse_payload('{"hive":{"hive_id":"H3"},"inspection":{}}', text)
    assert payload.hive.hive_id == "UNKNOWN"


def test_repeated_same_hive_and_separate_frame_counts_are_unambiguous():
    text = "Košnica 3. 4 rama meda. U košnici H3 ima 3 rama legla. Unos polena 2 od 3. Košnica je teška."
    assert transcript_hive_ids(text) == {"H3"}


@pytest.mark.parametrize("version", services.PROMPT_VERSIONS)
@pytest.mark.parametrize("model_id", [None, "UNKNOWN", "H3"])
def test_transcript_identity_is_authoritative_over_missing_model_id(ollama, version, model_id):
    raw = json.dumps({"hive": {"hive_id": model_id}, "inspection": {}})
    ollama(raw)
    result = services.ollama_extract("Celzijos ovih otvaram košnicu 3.", prompt_version=version)
    assert result.status == "completed"
    assert result.payload.hive.hive_id == "H3"
    assert result.metadata["hive_identity"]["status"] == "verified"
    assert result.metadata["hive_identity"]["transcript_ids"] == ["H3"]
    assert result.model_response == raw


@pytest.mark.parametrize("version", services.PROMPT_VERSIONS)
def test_model_h1_conflicts_with_explicit_transcript_h3(ollama, version):
    raw = '{"hive":{"hive_id":"H1"},"inspection":{}}'
    ollama(raw)
    result = services.ollama_extract("Otvaram košnicu 3.", prompt_version=version)
    assert result.status == "failed"
    assert result.payload is None
    assert result.error.code == "hive_id_conflict"
    assert result.metadata["hive_identity"]["transcript_ids"] == ["H3"]
    assert result.metadata["hive_identity"]["model_hive_id"] == "H1"
    assert result.model_response == raw


@pytest.mark.parametrize("text,model_id,status,assigned", [
    ("Celzijos ovih otvaram košnicu 3.", "H1", "conflict", None),
    ("Celzijos ovih otvaram košnicu 3.", None, "verified", "H3"),
    ("Košnice 3 i 4.", "H1", "multiple", "UNKNOWN"),
    ("Tri rama sa leglom, temperatura 23°C.", "H1", "unverified", "UNKNOWN"),
    ("Danas sam obišao pčelinjak.", None, "missing", "UNKNOWN"),
])
def test_identity_decision_and_original_response_are_persisted(database, ollama, text, model_id, status, assigned):
    raw = json.dumps({"hive": {"hive_id": model_id}, "inspection": {"open_brood": None}})
    ollama(raw)
    log_id = db.save_raw_hive_log(text)
    result = process_log(log_id)
    attempt = db.query("SELECT * FROM extraction_attempts")[0]
    assert attempt["model_response"] == raw
    assert db.get_log(log_id)["raw_transcript"] == text
    identity = json.loads(attempt["metadata_json"])["hive_identity"]
    assert identity["status"] == status
    assert identity["resolved_hive_id"] == assigned
    assert identity["model_hive_id"] == (model_id or "UNKNOWN")
    assert identity["review_required"] == (status != "verified")
    assert not db.query("SELECT * FROM hives WHERE hive_id='H1'")
    if status == "conflict":
        assert result["status"] == attempt["status"] == "failed"
        assert result["error"]["code"] == attempt["error_code"] == "hive_id_conflict"
        assert attempt["payload_json"] is None
        assert db.list_recent_inspections() == []
        # A later valid extraction retains the rejected attempt and original text.
        ollama('{"hive":{"hive_id":"H3"},"inspection":{}}')
        assert process_log(log_id)["status"] == "completed"
        assert db.get_inspection_for_log(log_id)["hive_id"] == "H3"
        assert len(db.query("SELECT * FROM extraction_attempts")) == 2
    else:
        inspection = db.get_inspection_for_log(log_id)
        assert result["status"] == "completed"
        assert inspection["hive_id"] == assigned
        assert inspection["confirmation_status"] == "unreviewed"
        assert inspection["open_brood"] is None
