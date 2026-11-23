import pytest
from fastapi.testclient import TestClient

from app import database
from app.agent import SESSIONS
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'research.db')
    monkeypatch.setenv('LLM_PROVIDER', 'mock')
    SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
