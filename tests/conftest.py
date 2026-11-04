"""Self-contained test credentials; no test ever unlocks a real door."""
import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault('ADMIN_KEY','A'*40)
os.environ.setdefault('INTEGRATION_KEY','I'*40)
os.environ.setdefault('APP_SECRET','S'*40)
os.environ.setdefault('DB_PATH',str(Path(tempfile.gettempdir())/'openretail-import-test.sqlite3'))
os.environ.setdefault('APP_MODE','demo')
os.environ.setdefault('MOCK_PAYMENTS_ENABLED','true')
os.environ.setdefault('LIVE_DOOR_ENABLED','false')

from openretail.main import create_app
from openretail.config import Settings

@pytest.fixture
def client(tmp_path):
    cfg=Settings(db_path=str(tmp_path/'test.sqlite3'),admin_key='A'*40,
                 integration_key='I'*40,app_secret='S'*40,
                 app_mode='demo',mock_payments=True,ha_enabled=False,live_door_enabled=False)
    with TestClient(create_app(cfg)) as test_client:
        yield test_client

@pytest.fixture
def admin_header():return {'X-Admin-Key':'A'*40}

@pytest.fixture
def integration_header():return {'X-Integration-Key':'I'*40}

def visitor(client):
    response=client.post('/api/entry')
    assert response.status_code==200
    return {'Authorization':'Bearer '+response.json()['guest_token']}
