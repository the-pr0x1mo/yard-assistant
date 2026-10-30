import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import requests

from app import db, main
from app.db_cli import SEED_TRANSCRIPT, seed
from app.pipeline import read_review
from app.schemas import ReviewConfirmation


def prepare(client):
    response = client.post('/api/voice', files={'file': ('../../note.webm', b'original audio', 'audio/webm')})
    assert response.status_code == 200
    return response.json()


def approval(review, **changes):
    body = {'review_token': review['review_token'], 'inspected_at': review['inspected_at'],
            'hive': {'hive_id': 'H1', 'name': 'Voćnjak', 'create': True},
            'inspection': review['preview']['structured']['inspection']}
    body.update(changes)
    return body


def counts():
    return [db.query(f'SELECT COUNT(*) n FROM {table}')[0]['n']
            for table in ('hives', 'hive_logs', 'extraction_attempts', 'inspections')]


@pytest.mark.parametrize('route', ['/api/voice', '/voice'])
def test_voice_and_discard_never_write(client, whisper, ollama, route):
    request, response = ollama()
    def before_extraction(*args, **kwargs):
        assert counts() == [0, 0, 0, 0]
        return response
    request.side_effect = before_extraction
    result = client.post(route, files={'file': ('a.webm', b'audio')}).json()
    assert result['status'] == 'review'
    assert result['inspection_id'] is result['id'] is None
    assert result['preview']['raw_transcript'] == SEED_TRANSCRIPT
    assert result['preview']['structured']['inspection']['brood_frames'] == 4
    assert counts() == [0, 0, 0, 0]
    del result
    client.get('/voice')  # navigate away/discard
    assert counts() == [0, 0, 0, 0]
    assert not os.path.exists(whisper.transcribe.call_args.args[0])


def test_atomic_confirmation_and_idempotent_retry(client, whisper, ollama):
    ollama()
    review = prepare(client)
    body = approval(review)
    result = client.post('/api/reviews/confirm', json=body)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert counts() == [1, 1, 1, 1]
    assert client.post('/api/reviews/confirm', json=body).json() == saved
    assert counts() == [1, 1, 1, 1]
    row = db.list_recent_inspections()[0]
    assert row['confirmation_status'] == 'confirmed' and row['confirmed_at']
    assert row['eggs_seen'] is row['temperature_c'] is None
    log = db.query('SELECT * FROM hive_logs')[0]
    assert log['raw_transcript'] == SEED_TRANSCRIPT
    assert log['audio_bytes'] is log['audio_content_type'] is None
    assert db.query('PRAGMA user_version')[0]['user_version'] == 2
    assert client.get(f"/api/logs/{saved['id']}/audio").status_code == 404


def test_concurrent_confirmation_serialized(client, whisper, ollama):
    ollama()
    review = prepare(client)
    source, body = read_review(review['review_token']), ReviewConfirmation(**approval(review))
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: db.save_review(source, body), range(2)))
    assert ids[0] == ids[1]
    assert counts() == [1, 1, 1, 1]


@pytest.mark.parametrize('mode', ['timeout', 'connection', 'invalid_json', 'validation'])
def test_failed_extraction_manual_confirmation(client, whisper, ollama, mode):
    if mode == 'timeout': ollama(error=requests.Timeout())
    elif mode == 'connection': ollama(error=requests.ConnectionError())
    elif mode == 'invalid_json': ollama('not json')
    else: ollama('{"hive":{"hive_id":"H1"},"inspection":{"queen_seen":9}}')
    review = prepare(client)
    assert review['extraction_status'] == 'failed'
    assert all(v is None for v in review['preview']['structured']['inspection'].values())
    assert counts() == [0, 0, 0, 0]
    body = approval(review, inspection={'queen_seen': 0, 'brood_frames': 0, 'honey_frames': None})
    assert client.post('/api/reviews/confirm', json=body).status_code == 200
    row = db.list_recent_inspections()[0]
    assert row['queen_seen'] == row['brood_frames'] == 0
    assert row['honey_frames'] is None
    attempt = db.query('SELECT * FROM extraction_attempts')[0]
    assert attempt['status'] == attempt['extraction_status'] == 'failed'
    assert attempt['normalization_status'] == 'completed'
    assert attempt['error_code']
    assert db.get_log(row['raw_log_id'])['extraction_status'] == 'failed'


def test_rollback_then_retry_preserves_card(client, whisper, ollama, monkeypatch):
    ollama()
    body = approval(prepare(client))
    original = db.insert_approved
    def fail(*args):
        original(*args)
        raise sqlite3.IntegrityError('simulated')
    monkeypatch.setattr(db, 'insert_approved', fail)
    assert client.post('/api/reviews/confirm', json=body).status_code == 503
    assert counts() == [0, 0, 0, 0]
    monkeypatch.setattr(db, 'insert_approved', original)
    assert client.post('/api/reviews/confirm', json=body).status_code == 200
    assert counts() == [1, 1, 1, 1]


def test_update_same_id_immutable_links_transcript_and_hive_rename(client):
    seed()
    before = db.list_recent_inspections()[0]
    key = before['inspection_id']
    correction = {'inspected_at':'2026-10-30', 'inspection': {'queen_seen':0, 'honey_frames':None, 'note':'Ispravka'}}
    result = client.put(f'/api/inspections/{key}', json=correction)
    assert result.status_code == 200
    after = result.json()
    for field in ('inspection_id', 'raw_log_id', 'extraction_attempt_id', 'hive_id', 'confirmed_at'):
        assert after[field] == before[field]
        assert client.put(f'/api/inspections/{key}', json={**correction,field:'bad'}).status_code == 422
    assert after['queen_seen'] == 0 and after['honey_frames'] is None
    assert counts() == [1, 1, 1, 1]
    assert client.patch('/api/hives/H1', json={'name':'Bagrem'}).status_code == 200
    assert client.patch('/api/hives/H1', json={'name':'X', 'hive_id':'H2'}).status_code == 422
    assert db.get_hive('H1')['name'] == 'Bagrem'
    assert client.get('/api/hives').json() == [{'hive_id':'H1','name':'Bagrem'}]
    assert db.get_log(before['raw_log_id'])['raw_transcript'] == SEED_TRANSCRIPT
    assert client.put(f'/api/inspections/{key}', json={**correction, 'raw_transcript':'changed'}).status_code == 422
    assert client.get(f"/logs/{before['raw_log_id']}").status_code == 200
    assert client.post(f"/api/logs/{before['raw_log_id']}/reprocess").json()['inspection_id'] == key


def test_select_existing_and_new_unique_custom_hive(client, whisper, ollama):
    seed(); ollama()
    review = prepare(client)
    body = approval(review, hive={'hive_id':'H1','name':'Lipa', 'create':True})
    assert client.post('/api/reviews/confirm', json=body).status_code == 409
    assert counts() == [1,1,1,1]
    body['hive']['create'] = False
    assert client.post('/api/reviews/confirm', json=body).status_code == 200
    assert counts() == [1,2,2,2]
    custom = approval(prepare(client), hive={'hive_id':'yard-A_2','name':'Nova','create':True})
    assert client.post('/api/reviews/confirm', json=custom).status_code == 200
    assert db.get_hive('yard-A_2')['name'] == 'Nova'
    assert client.get('/api/logs/3').status_code == 200


@pytest.mark.parametrize('changes', [
    {'hive':{'hive_id':'UNKNOWN','create':True}}, {'hive':{'hive_id':'bad/id','create':True}},
    {'inspected_at':'bad'}, {'inspected_at':'2026-02-30'}, {'inspected_at':''},
    {'inspection':{'brood_frames':-1}}, {'inspection':{'brood_frames':1.5}},
    {'inspection':{'queen_seen':False}}, {'inspection':{'queen_seen':2}},
    {'inspection':{'flight_activity':6}}, {'inspection':{'pollen_intake':4}},
    {'inspection':{'behavior':'unknown'}}, {'inspection':{'honey_frames':2**64}},
    {'inspection':{'temperature_c':'NaN'}}, {'raw_transcript':'forged'},
])
def test_invalid_confirmation_no_writes(client, whisper, ollama, changes):
    ollama()
    body = approval(prepare(client), **changes)
    assert client.post('/api/reviews/confirm', json=body).status_code == 422
    assert counts() == [0,0,0,0]


def test_signed_source_cannot_be_changed(client, whisper, ollama):
    ollama()
    review = prepare(client)
    body = approval(review)
    body['review_token'] = body['review_token'][:-4] + 'abcd'
    assert client.post('/api/reviews/confirm', json=body).status_code == 409
    assert counts() == [0,0,0,0]


def test_whisper_exact_text_and_failure_cleanup(client, whisper, ollama):
    ollama()
    text = '  Društvo broj 1.\n  Matica vidjena.  '
    whisper.transcribe.return_value = ([SimpleNamespace(text=text[:10]), SimpleNamespace(text=text[10:])], SimpleNamespace(language='sr'))
    review = prepare(client)
    assert review['preview']['raw_transcript'] == text
    assert client.post('/api/reviews/confirm',json=approval(review)).status_code == 200
    assert db.get_log(1)['raw_transcript'] == text
    assert not os.path.exists(whisper.transcribe.call_args.args[0])
    whisper.transcribe.side_effect = RuntimeError('decoder')
    assert client.post('/api/voice', files={'file':('x',b'audio')}).status_code == 422
    assert not os.path.exists(whisper.transcribe.call_args.args[0])
    assert counts() == [1,1,1,1]


def test_empty_audio_transcript_and_upload_limit(client, whisper, ollama):
    request, _ = ollama()
    assert client.post('/api/voice',files={'file':('x',b'')}).status_code == 400
    whisper.transcribe.return_value = ([], SimpleNamespace(language='sr'))
    assert client.post('/api/voice',files={'file':('x',b'audio')}).status_code == 400
    assert client.post('/api/voice',files={'file':('x',b'a'*(32*1024*1024+1))}).status_code == 413
    request.assert_not_called()
    assert counts() == [0,0,0,0]


def test_legacy_unreviewed_hidden_and_explicitly_confirmed(client, whisper, ollama):
    seed()
    with db.connection() as conn:
        conn.execute("UPDATE inspections SET confirmation_status='unreviewed', confirmed_at=NULL")
    assert db.list_recent_inspections() == []
    assert db.list_hive_inspections('H1') == []
    assert db.list_hive_dashboard()[0]['inspection_id'] is None
    assert client.get('/export/json').json()['inspections'] == []
    assert db.get_stats_summary()['total_inspections'] == 0
    assert client.get('/logs/1').status_code == 200
    assert client.post('/api/inspections/1/confirm').status_code == 200
    assert db.list_recent_inspections()[0]['inspection_id'] == 1
    # Legacy failed source reprocessing is also ephemeral until confirmation.
    log_id = db.save_raw_hive_log('Legacy transcript')
    ollama()
    review = client.post(f'/api/logs/{log_id}/reprocess').json()
    assert counts() == [1,2,1,1]
    assert client.post('/api/reviews/confirm', json=approval(review,hive={'hive_id':'H1'})).status_code == 200
    assert counts() == [1,2,2,2]
    assert db.get_inspection_for_log(log_id)['confirmation_status'] == 'confirmed'


def test_missing_records(client):
    for route in ['/api/logs/999','/api/logs/999/audio']:
        assert client.get(route).status_code == 404
    assert client.post('/api/logs/999/reprocess').status_code == 404
    assert client.post('/api/inspections/999/confirm').status_code == 404
    assert client.patch('/api/hives/missing', json={'name':'X'}).status_code == 404
    assert client.put('/api/inspections/999',json={'inspected_at':'2026-01-01','inspection':{}}).status_code == 404


def test_review_form_covers_contract(client):
    from app.schemas import InspectionData
    spec = client.get('/api/inspection-fields').json()
    keys = spec['compact'] + [k for group in spec['groups'].values() for k in group]
    assert set(keys) == set(InspectionData.model_fields)
    assert len(keys) == len(set(keys))
    script = client.get('/static/review-card.js').text
    for forbidden in ['localStorage','sessionStorage','document.cookie']:
        assert forbidden not in script
    assert 'beforeunload' in script and 'pagehide' in script


def test_current_corrections_in_dashboard_exports_and_rendered_cards(client):
    import csv
    import io
    seed()
    corrected = {'inspected_at':'2026-10-29 08:00:00', 'inspection': {'brood_frames':0, 'queen_seen':None, 'note':'Ispravljen pregled'}}
    assert client.put('/api/inspections/1',json=corrected).status_code == 200
    dashboard = db.list_hive_dashboard()[0]
    assert dashboard['inspected_at'] == corrected['inspected_at']
    assert dashboard['queen_seen'] is None
    data = client.get('/export/json').json()
    assert data['inspections'][0]['brood_frames'] == 0
    assert data['inspections'][0]['note'] == 'Ispravljen pregled'
    rows = list(csv.DictReader(io.StringIO(client.get('/export/inspections.csv').content.decode('utf-8-sig'))))
    assert rows[0]['brood_frames'] == '0' and rows[0]['queen_seen'] == ''
    assert rows[0]['note'] == 'Ispravljen pregled'
    card = client.get('/inspections')
    assert 'Ispravljen pregled' in card.text and SEED_TRANSCRIPT in card.text
    assert card.headers['cache-control'] == 'no-store'
    # A newer YA-01 unreviewed row must not hide the earlier approved latest row.
    with db.connection() as conn:
        log_id = conn.execute("INSERT INTO hive_logs(created_at,raw_transcript) VALUES('2026-10-30','legacy')").lastrowid
        attempt_id = conn.execute("INSERT INTO extraction_attempts(raw_log_id,started_at) VALUES (?,'2026-10-30')",(log_id,)).lastrowid
        conn.execute("INSERT INTO inspections(raw_log_id,extraction_attempt_id,hive_id,inspected_at) VALUES (?,?,'H1','2026-10-30')", (log_id,attempt_id))
    assert db.list_hive_dashboard()[0]['inspection_id'] == 1
    assert len(db.list_recent_inspections()) == 1
    assert len(client.get('/export/json').json()['inspections']) == 1


def test_existing_hive_rename_rolls_back_on_failed_confirmation(client, whisper, ollama, monkeypatch):
    seed(); ollama()
    original_name = db.get_hive('H1')['name']
    body = approval(prepare(client), hive={'hive_id':'H1','name':'Changed','create':False})
    original = db.insert_approved
    def broken(*args):
        raise sqlite3.IntegrityError('fail')
    monkeypatch.setattr(db, 'insert_approved', broken)
    assert client.post('/api/reviews/confirm',json=body).status_code == 503
    assert counts() == [1,1,1,1]
    assert db.get_hive('H1')['name'] == original_name
    monkeypatch.setattr(db, 'insert_approved', original)
    assert client.post('/api/reviews/confirm',json=body).status_code == 200
    assert db.get_hive('H1')['name'] == 'Changed'
    # Omitting name when selecting an existing hive preserves its configured name.
    body = approval(prepare(client), hive={'hive_id':'H1'})
    assert client.post('/api/reviews/confirm',json=body).status_code == 200
    assert db.get_hive('H1')['name'] == 'Changed'


def test_invalid_update_leaves_persisted_facts_unchanged(client):
    seed()
    before = db.get_inspection_for_log(1)
    for facts in ({'brood_frames':-1}, {'queen_seen':False}, {'pollen_intake':4}):
        response = client.put('/api/inspections/1', json={'inspected_at':'2026-10-30','inspection':facts})
        assert response.status_code == 422
        assert db.get_inspection_for_log(1) == before


def test_legacy_source_status_and_preview_compatibility(client):
    log_id = db.save_raw_hive_log('existing source')
    pending = client.get(f'/api/logs/{log_id}').json()
    assert pending['status'] == 'pending'
    assert pending['preview']['hive_id'] is None
    with db.connection() as conn:
        conn.execute("UPDATE hive_logs SET extraction_status='failed' WHERE id=?", (log_id,))
    assert client.get(f'/api/logs/{log_id}').json()['status'] == 'failed'
