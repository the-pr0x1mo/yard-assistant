import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import db, main, services
from app.db_cli import SEED_FACTS, SEED_TRANSCRIPT


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.sqlite"))
    db.db_init()
    return tmp_path


@pytest.fixture
def client(database):
    with TestClient(main.app) as client:
        yield client


@pytest.fixture
def ollama(monkeypatch):
    def configure(content=None, *, envelope=None, error=None):
        response = Mock()
        response.json.return_value = envelope if envelope is not None else {
            "response": json.dumps(SEED_FACTS, ensure_ascii=False) if content is None else content,
            "done": True, "model": "fixture", "total_duration": 1000,
            "prompt_eval_duration": 100, "eval_duration": 800, "prompt_eval_count": 50, "eval_count": 25,
        }
        request = Mock(return_value=response, side_effect=error)
        monkeypatch.setattr(services.requests, "post", request)
        return request, response
    return configure


@pytest.fixture
def whisper(monkeypatch):
    model = Mock()
    model.transcribe.return_value = ([SimpleNamespace(text=SEED_TRANSCRIPT)], SimpleNamespace(language="sr"))
    monkeypatch.setattr(main, "get_whisper", lambda: model)
    return model
