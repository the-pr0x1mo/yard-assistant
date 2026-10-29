import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import requests

from app import db, main
from app.db_cli import SEED_TRANSCRIPT
from app.pipeline import process_log


@pytest.mark.parametrize("route", ["/api/voice", "/voice"])
def test_voice_persists_raw_before_request(client, ollama, whisper, route):
    request, response = ollama()
    def inspect_before_model(*args, **kwargs):
        logs = db.list_recent_logs()
        assert len(logs) == 1
        assert logs[0]["raw_transcript"] == SEED_TRANSCRIPT
        assert logs[0]["extraction_status"] == "pending"
        assert db.list_recent_inspections() == []
        return response
    request.side_effect = inspect_before_model
    result = client.post(route, files={"file": ("../../note.webm", b"original audio", "audio/webm")})
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == body["extraction_status"] == body["normalization_status"] == "completed"
    assert body["confirmation_status"] == "unreviewed"
    assert body["preview"]["raw_transcript"] == SEED_TRANSCRIPT
    assert body["preview"]["structured"]["hive"]["hive_id"] == "H1"
    assert client.get(f'/api/logs/{body["id"]}/audio').content == b"original audio"
    row = db.list_recent_inspections()[0]
    assert row["raw_log_id"] == body["id"]
    assert row["inspection_type"] is None
    assert row["inspected_at"] == db.get_log(body["id"])["created_at"]
    assert client.get(f'/logs/{body["id"]}').status_code == 200
    assert client.post(f'/api/inspections/{row["inspection_id"]}/confirm').json()["confirmation_status"] == "confirmed"
    confirmed_at = db.get_inspection_for_log(body["id"])["confirmed_at"]
    client.post(f'/api/inspections/{row["inspection_id"]}/confirm')
    assert db.get_inspection_for_log(body["id"])["confirmed_at"] == confirmed_at


@pytest.mark.parametrize("mode", ["timeout", "connection", "invalid_json", "validation"])
def test_failure_retains_source_and_is_visible(client, ollama, whisper, mode):
    if mode == "timeout":
        ollama(error=requests.Timeout())
    elif mode == "connection":
        ollama(error=requests.ConnectionError())
    elif mode == "invalid_json":
        ollama("not json")
    else:
        ollama('{"hive":{"hive_id":"H1"},"inspection":{"queen_seen":9}}')
    response = client.post("/api/voice", files={"file": ("test.webm", b"audio")})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == body["extraction_status"] == "failed"
    assert body["normalization_status"] == "pending"
    assert body["inspection_id"] is None
    assert body["preview"]["structured"] is None
    assert db.get_log(body["id"])["raw_transcript"] == SEED_TRANSCRIPT
    assert not db.list_recent_inspections()
    assert db.query("SELECT * FROM hives") == []
    detail = client.get(f'/api/logs/{body["id"]}').json()
    assert detail["attempts"][0]["status"] == "failed"
    assert detail["error"]
    assert client.get('/transcripts').status_code == 200


def test_normalized_write_rollback_retains_candidate(client, ollama, whisper, monkeypatch):
    ollama()
    original = db.create_inspection
    def broken(*args):
        original(*args)
        raise sqlite3.IntegrityError("simulated error")
    monkeypatch.setattr(db, "create_inspection", broken)
    response = client.post("/api/voice", files={"file": ("test.webm", b"audio")})
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "failed"
    assert result["extraction_status"] == "completed"
    assert result["normalization_status"] == "failed"
    assert not db.query("SELECT * FROM inspections")
    assert not db.query("SELECT * FROM hives")
    attempt = db.query("SELECT * FROM extraction_attempts")[0]
    assert attempt["model_response"]
    assert json.loads(attempt["payload_json"])["inspection"]["brood_frames"] == 4
    assert db.get_log(result["id"])["raw_transcript"] == SEED_TRANSCRIPT
    monkeypatch.setattr(db, "create_inspection", original)
    retry = client.post(f'/api/logs/{result["id"]}/reprocess').json()
    assert retry["status"] == "completed"
    assert len(db.query("SELECT * FROM extraction_attempts")) == 2
    assert len(db.list_recent_inspections()) == 1


def test_failed_reprocessing_then_no_duplicate_or_overwrite(client, ollama):
    log_id = db.save_raw_hive_log(SEED_TRANSCRIPT)
    ollama(error=requests.Timeout())
    first = process_log(log_id)
    assert first["status"] == "failed"
    request, _ = ollama()
    second = process_log(log_id)
    assert second["status"] == "completed"
    third = client.post(f"/api/logs/{log_id}/reprocess").json()
    assert third["inspection_id"] == second["inspection_id"]
    assert request.call_count == 1
    assert len(db.list_recent_inspections()) == 1
    attempts = db.query("SELECT * FROM extraction_attempts ORDER BY attempt_id")
    assert [a["status"] for a in attempts] == ["failed", "completed"]


def test_concurrent_claim_and_pending_recovery(client):
    log_id = db.save_raw_hive_log(SEED_TRANSCRIPT)
    def claim():
        try:
            return db.start_attempt(log_id)
        except db.ProcessingBusy:
            return "busy"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert results.count("busy") == 1
    assert client.post(f"/api/logs/{log_id}/reprocess").status_code == 409
    assert db.recover_pending() == 1
    assert db.recover_pending() == 0
    assert db.get_log(log_id)["error_code"] == "interrupted"
    assert db.start_attempt(log_id) is not None


def test_status_write_failure_reports_saved_id(client, whisper, ollama, monkeypatch):
    ollama()
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(db, "record_extraction", broken)
    monkeypatch.setattr(db, "fail_attempt", broken)
    response = client.post("/api/voice", files={"file": ("test.webm", b"audio")})
    assert response.status_code == 503
    result = response.json()
    assert result["id"]
    assert result["error"]["code"] == "status_persistence_error"
    assert db.get_log(result["id"])["raw_transcript"] == SEED_TRANSCRIPT


def test_raw_write_failure_never_calls_model(client, whisper, ollama, monkeypatch):
    request, _ = ollama()
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(db, "save_raw_hive_log", broken)
    response = client.post("/api/voice", files={"file": ("test.webm", b"audio")})
    assert response.status_code == 503
    assert "id" not in response.json()
    request.assert_not_called()


def test_whisper_exact_text_and_cleanup(client, whisper, ollama):
    ollama()
    text = "  Društvo broj 1.\n  Matica vidjena.  "
    whisper.transcribe.return_value = ([SimpleNamespace(text=text[:10]), SimpleNamespace(text=text[10:])], SimpleNamespace(language="sr"))
    result = client.post("/api/voice", files={"file": ("voice.wav", b"audio")}).json()
    assert db.get_log(result["id"])["raw_transcript"] == text
    import os
    assert not os.path.exists(whisper.transcribe.call_args.args[0])


def test_empty_audio_and_failed_transcription(client, whisper, ollama):
    request, _ = ollama()
    assert client.post("/api/voice", files={"file": ("x", b"")}).status_code == 400
    whisper.transcribe.return_value = ([], SimpleNamespace(language="sr"))
    assert client.post("/api/voice", files={"file": ("x", b"audio")}).status_code == 400
    whisper.transcribe.side_effect = RuntimeError("decoder error")
    assert client.post("/api/voice", files={"file": ("x", b"audio")}).status_code == 422
    request.assert_not_called()
    assert db.query("SELECT * FROM hive_logs") == []


def test_missing_records(client):
    assert client.get('/api/logs/999').status_code == 404
    assert client.get('/api/logs/999/audio').status_code == 404
    assert client.post('/api/logs/999/reprocess').status_code == 404
    assert client.post('/api/inspections/999/confirm').status_code == 404


def test_routine_logs_do_not_contain_transcript_or_output(database, ollama, caplog):
    ollama()
    caplog.set_level("INFO")
    process_log(db.save_raw_hive_log(SEED_TRANSCRIPT))
    assert "Društvo" not in caplog.text
    assert "Pogača" not in caplog.text
    assert "brood_frames" not in caplog.text
    assert '"request_ms"' in caplog.text
    assert '"persistence_ms"' in caplog.text
