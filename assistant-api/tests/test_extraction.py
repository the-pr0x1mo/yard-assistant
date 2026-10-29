import json
from unittest.mock import Mock

import pytest
import requests
from pydantic import ValidationError

from app import services
from app.db_cli import SEED_TRANSCRIPT
from app.normalization import normalize_hive_id, transcript_hive_ids
from app.schemas import HiveInspectionPayload, InspectionData


@pytest.mark.parametrize("text,expected", [
    ("Društvo broj 1", "H1"), ("Društvo 1", "H1"), ("Prvo društvo", "H1"),
    ("Prva košnica", "H1"), ("Košnica broj jedan", "H1"), ("Košnica H-1", "H1"),
    ("Treća košnica", "H3"), ("Друштво број два", "H2"), ("Друга кошница", "H2"),
    ("H-012", "H12"), ("Košnica broj dvadeset jedan", "H21"), ("Društvo 105", "H105"),
    ("Košnica broj trideset i dva", "H32"),
])
def test_hive_numbering(text, expected):
    assert normalize_hive_id(text) == expected
    assert transcript_hive_ids(text + ". Matica viđena.") == {expected}


def test_sparse_missing_and_ambiguous_hive():
    payload = services.parse_payload('{"hive":{"hive_id":null},"inspection":{}}', "Matica viđena.")
    assert payload.hive.hive_id == "UNKNOWN"
    assert all(v is None for v in payload.inspection.model_dump().values())
    payload = services.parse_payload('{"hive":{"hive_id":"H1"},"inspection":{}}', "Društvo 1 i društvo 2.")
    assert payload.hive.hive_id == "UNKNOWN"
    with pytest.raises(ValueError):
        services.parse_payload('{"hive":{"hive_id":"H2"},"inspection":{}}', "Društvo broj 1.")


@pytest.mark.parametrize("hive", ["foo", "H0", "", 1, True, "H1 trailing"])
def test_invalid_identifier(hive):
    with pytest.raises(ValueError):
        normalize_hive_id(hive)


@pytest.mark.parametrize("facts", [
    {"brood_frames": -1}, {"brood_frames": 1.5}, {"queen_seen": 2}, {"queen_seen": True},
    {"queen_seen": "1"}, {"flight_activity": 6}, {"pollen_intake": 4},
    {"temperature_c": float('nan')}, {"behavior": "calm"}, {"recommended_action": "prihrana"},
    {"ready_for_winter": 1}, {"food_score": 50}, {"inspected_at": "invented"},
])
def test_factual_schema_rejects_invalid_and_analytical_fields(facts):
    with pytest.raises(ValidationError):
        InspectionData.model_validate(facts)


def test_log25_contract(ollama):
    request, _ = ollama()
    result = services.ollama_extract(SEED_TRANSCRIPT)
    assert result.status == "completed"
    assert result.error is None
    assert result.payload.hive.hive_id == "H1"
    facts = result.payload.inspection
    assert (facts.behavior, facts.queen_seen, facts.brood_frames, facts.open_brood,
            facts.capped_brood, facts.honey_frames) == ("mirne", 1, 4, 1, 1, 5)
    assert facts.eggs_seen is None
    assert facts.inspection_type is None
    assert facts.reserves_estimate is None
    assert "Pogača pojedena do pola" in facts.note
    assert "sveže zasijanog" in facts.note
    body = request.call_args.kwargs["json"]
    assert body["format"] == HiveInspectionPayload.model_json_schema()
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["model"] == services.OLLAMA_MODEL
    assert body["system"] == services.build_system_prompt(SEED_TRANSCRIPT)
    for key in ("total_duration", "prompt_eval_duration", "eval_duration", "prompt_eval_count", "eval_count"):
        assert key in result.metadata
    for key in ("request_ms", "validation_ms", "duration_ms"):
        assert result.metadata[key] >= 0


def test_explicit_json_mode(ollama, monkeypatch):
    monkeypatch.setattr(services, "OLLAMA_FORMAT", "json")
    request, _ = ollama()
    assert services.ollama_extract(SEED_TRANSCRIPT).status == "completed"
    assert request.call_args.kwargs["json"]["format"] == "json"
    assert request.call_count == 1


@pytest.mark.parametrize("content,code", [
    ("", "empty_response"), ("   ", "empty_response"), ("not json", "invalid_json"),
    ('```json\n{}\n```', "invalid_json"), ('[]', "invalid_structure"), ('null', "invalid_structure"),
    ('{}', "validation_error"), ('{"hive":{},"inspection":{}}', "validation_error"),
    ('{"hive":{"hive_id":"H1"},"inspection":{"brood_frames":-1}}', "validation_error"),
])
def test_failed_model_output(ollama, content, code):
    request, _ = ollama(content)
    result = services.ollama_extract(SEED_TRANSCRIPT)
    assert result.status == "failed"
    assert result.payload is None
    assert result.error.code == code
    assert request.call_count == 1


@pytest.mark.parametrize("envelope,code", [
    ({"response": None}, "invalid_structure"), ({"response": {}}, "invalid_structure"),
    ([1], "invalid_structure"), ({"wrong": "shape"}, "invalid_structure"),
    ({"response": "{}", "done": False}, "incomplete_response"),
    ({"response": "{}", "done": True, "done_reason": "length"}, "incomplete_response"),
])
def test_failed_envelope(ollama, envelope, code):
    ollama(envelope=envelope)
    assert services.ollama_extract(SEED_TRANSCRIPT).error.code == code


@pytest.mark.parametrize("error,code", [
    (requests.Timeout(), "timeout"), (requests.ConnectionError(), "connection_error"),
    (requests.RequestException(), "request_error"), (RuntimeError("private details"), "internal_error"),
])
def test_request_failures(ollama, error, code):
    ollama(error=error)
    result = services.ollama_extract(SEED_TRANSCRIPT)
    assert result.status == "failed"
    assert result.payload is None
    assert result.error.code == code
    assert "private details" not in result.model_dump_json()


def test_http_error_and_invalid_http_json(ollama):
    _, response = ollama()
    response.raise_for_status.side_effect = requests.HTTPError(response=Mock(status_code=503))
    assert services.ollama_extract(SEED_TRANSCRIPT).error.code == "http_error"
    _, response = ollama()
    response.json.side_effect = ValueError()
    assert services.ollama_extract(SEED_TRANSCRIPT).error.code == "invalid_response"


def test_schema_json_contract():
    schema = HiveInspectionPayload.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["hive", "inspection"]
    assert "metrics" not in schema["properties"]
    assert "inspected_at" not in schema["$defs"]["InspectionData"]["properties"]
