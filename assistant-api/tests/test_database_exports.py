import base64
import csv
import io
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.db_cli import main as cli, reset_database, seed, SEED_TRANSCRIPT
from app.pipeline import process_log


def test_initialization_repeatable_and_existing_records_unchanged(database):
    seed()
    before = db.export_all_data_json()
    db.db_init()
    db.db_init()
    assert db.export_all_data_json() == before
    with db.connection() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with pytest.raises(RuntimeError, match="empty"):
        seed()


def test_unversioned_database_refused_without_mutation(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE hive_logs(id INTEGER PRIMARY KEY, raw_transcript TEXT)")
        conn.execute("INSERT INTO hive_logs VALUES(25, 'synthetic legacy note')")
    before = path.read_bytes()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    with pytest.raises(RuntimeError, match="incompatible"):
        db.db_init()
    with pytest.raises(RuntimeError, match="incompatible"):
        with TestClient(main.app):
            pass
    assert path.read_bytes() == before


def test_startup_does_not_create_database(tmp_path, monkeypatch):
    path = tmp_path / "absent.sqlite"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    with pytest.raises(RuntimeError, match="not initialized"):
        with TestClient(main.app):
            pass
    assert not path.exists()


def test_explicit_reset_backup_and_reseed(database):
    seed()
    before = db.export_all_data_json()
    backup = database / "before-reset.sqlite"
    reset_database(backup)
    assert db.query("SELECT * FROM hive_logs") == []
    db.check_schema()
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT raw_transcript FROM hive_logs").fetchone()[0] == SEED_TRANSCRIPT
    seed()
    assert db.export_all_data_json() == before
    with pytest.raises(RuntimeError, match="new file"):
        reset_database(backup)


def test_explicit_reset_can_replace_legacy_copy(tmp_path, monkeypatch):
    path = tmp_path / "legacy-copy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE old_synthetic(value TEXT)")
        conn.execute("INSERT INTO old_synthetic VALUES('keep in backup')")
    monkeypatch.setattr(db, "DB_PATH", str(path))
    backup = tmp_path / "legacy-backup.sqlite"
    reset_database(backup)
    db.check_schema()
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT * FROM old_synthetic").fetchone()[0] == "keep in backup"


def test_reset_requires_confirmation_and_stop_flags(database):
    seed()
    with pytest.raises(SystemExit) as exc:
        cli(["reset", "--backup", str(database / "backup.sqlite")])
    assert exc.value.code == 2
    assert len(db.list_recent_logs()) == 1


def test_sqlite_constraints_and_atomic_rollback(database, ollama):
    ollama()
    process_log(db.save_raw_hive_log(SEED_TRANSCRIPT))
    with pytest.raises(sqlite3.IntegrityError):
        with db.connection() as conn:
            conn.execute("UPDATE inspections SET brood_frames=-1")
    with pytest.raises(sqlite3.IntegrityError):
        with db.connection() as conn:
            conn.execute("UPDATE inspections SET raw_log_id=999")
    assert db.list_recent_inspections()[0]["brood_frames"] == 4


def test_json_complete_history_audio_and_metadata(client, ollama):
    ollama()
    log_id = db.save_raw_hive_log(SEED_TRANSCRIPT, audio_bytes=b'original', audio_content_type='audio/webm', metadata={'duration_ms': 12})
    process_log(log_id)
    data = client.get('/export/json').json()
    assert data["schema_version"] == 2
    assert data["hive_logs"][0]["raw_transcript"] == SEED_TRANSCRIPT
    assert base64.b64decode(data["hive_logs"][0]["audio_base64"]) == b"original"
    assert data["inspections"][0]["raw_log_id"] == log_id
    assert data["extraction_attempts"][0]["model_response"]
    assert json.loads(data["extraction_attempts"][0]["metadata_json"])["prompt_eval_count"] == 50
    assert json.loads(data["hive_logs"][0]["whisper_metadata_json"])["duration_ms"] == 12
    assert 'inspection_metrics' not in data


def test_csv_all_history_vs_latest_snapshot(client, ollama):
    ollama()
    for _ in range(3):
        process_log(db.save_raw_hive_log(SEED_TRANSCRIPT))
    response = client.get('/export/inspections.csv')
    assert response.content.startswith(b'\xef\xbb\xbf')
    rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(rows) == 3
    assert len({r['inspection_id'] for r in rows}) == 3
    assert len({r['raw_log_id'] for r in rows}) == 3
    assert rows[0]['brood_frames'] == '4'
    assert rows[0]['confirmation_status'] == 'unreviewed'
    assert rows[0]['extraction_status'] == 'completed'
    assert rows[0]['inspection_type'] == ''
    latest = client.get('/export/csv')
    latest_rows = list(csv.DictReader(io.StringIO(latest.content.decode('utf-8-sig'))))
    assert len(latest_rows) == 1
    assert latest_rows[0]['hive_id'] == 'H1'
    assert latest_rows[0]['strength_score'] == ''
    assert list(latest_rows[0]) == db.DASHBOARD_CSV_FIELDS


@pytest.mark.parametrize('value', ['=HYPERLINK("x")', '+cmd', '-cmd', '@SUM(A1)', '\t=1', '\r=1', '\n=1', '  =1', '\x00=1'])
def test_formula_injection(value):
    assert main.safe_csv_value(value).startswith("'")


def test_csv_quotes_and_serbian_text(client):
    seed()
    note = '=cmd, "Pogača"\nnovi red'
    with db.connection() as conn:
        conn.execute('UPDATE inspections SET note=?', (note,))
        conn.execute('UPDATE hives SET name=?', (note,))
    historical = list(csv.DictReader(io.StringIO(client.get('/export/inspections.csv').content.decode('utf-8-sig'))))
    latest = list(csv.DictReader(io.StringIO(client.get('/export/csv').content.decode('utf-8-sig'))))
    assert historical[0]['note'] == "'" + note
    assert latest[0]['name'] == "'" + note
    # Non-CSV formats preserve originals, not spreadsheet escaping.
    assert client.get('/export/json').json()['inspections'][0]['note'] == note


def test_sqlite_snapshot_with_wal_and_pending_failure_export(client, database):
    seed()
    with db.connection() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("INSERT INTO hive_logs(created_at,raw_transcript) VALUES('2026-01-01', 'pending record')")
    response = client.get('/export/sqlite')
    assert response.status_code == 200
    copy = database / 'export.sqlite'
    copy.write_bytes(response.content)
    with sqlite3.connect(copy) as conn:
        assert conn.execute('SELECT COUNT(*) FROM hive_logs').fetchone()[0] == 2
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_empty_exports_and_pages(client):
    for route in ['/', '/voice', '/hives', '/inspections', '/transcripts', '/stats', '/hives/H1',
                  '/health', '/export/json', '/export/csv', '/export/inspections.csv', '/export/sqlite']:
        assert client.get(route).status_code == 200, route
    seed()
    for route in ['/hives', '/inspections', '/transcripts', '/stats', '/hives/H1', '/logs/1']:
        assert client.get(route).status_code == 200, route
