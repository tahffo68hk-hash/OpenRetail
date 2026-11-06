"""Deployment guards. These tests do not open a door or call a payment provider."""
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient
from openretail.config import Settings
from openretail.database import Database
from openretail.main import create_app
from scripts.doctor import run_doctor
from scripts.restore import assess, restore_backup

KEYS=dict(admin_key='A'*40,integration_key='I'*40,app_secret='S'*40)

def production_settings(path,**extra):
    base=dict(db_path=str(path),app_mode='production',mock_payments=False,payment_provider='disabled',
              admin_password_hash='not-a-real-login-hash',trusted_proxy_tls=True,
              public_base_url='https://shop.example.invalid',live_door_enabled=False,**KEYS)
    base.update(extra)
    return Settings(**base)

def test_doctor_readonly_does_not_create_database(tmp_path):
    missing=tmp_path/'absent.sqlite3'
    cfg=Settings(db_path=str(missing),app_mode='demo',mock_payments=True,**KEYS)
    with pytest.raises(SystemExit,match='数据库不存在'):
        run_doctor(cfg,init_demo=False)
    assert not missing.exists()

def test_init_demo_refuses_existing_and_non_demo(tmp_path):
    existing=tmp_path/'live.sqlite3'
    Database(str(existing)).init(demo=True)
    before=existing.read_bytes()
    cfg=Settings(db_path=str(existing),app_mode='demo',mock_payments=True,**KEYS)
    with pytest.raises(SystemExit,match='不会覆盖'):
        run_doctor(cfg,init_demo=True)
    assert existing.read_bytes()==before
    blocked=tmp_path/'prod.sqlite3'
    with pytest.raises(SystemExit,match='只允许 APP_MODE=demo'):
        run_doctor(production_settings(blocked),init_demo=True)
    assert not blocked.exists()

def test_init_demo_creates_only_missing_demo_database(tmp_path):
    path=tmp_path/'new-demo.sqlite3'
    cfg=Settings(db_path=str(path),app_mode='demo',mock_payments=True,**KEYS)
    text=run_doctor(cfg,init_demo=True)
    assert '检查模式：演示初始化' in text
    assert assess(path)['products']==8

def test_restore_is_isolated_and_consistent(tmp_path,monkeypatch):
    source=tmp_path/'source.sqlite3'
    Database(str(source)).init(demo=True)
    with sqlite3.connect(source) as conn:
        conn.execute("UPDATE products SET stock=79 WHERE barcode='6901234567892'")
        conn.commit()
    before=source.read_bytes()
    backup=tmp_path/'backup.sqlite3'
    with sqlite3.connect(source) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    dest=tmp_path/'isolated'/'restored.sqlite3'
    report=restore_backup(backup,dest)
    assert report['ok'] and report['products']==8
    assert dest.is_file() and source.read_bytes()==before
    with sqlite3.connect(dest) as conn:
        stock=conn.execute("SELECT stock FROM products WHERE barcode='6901234567892'").fetchone()[0]
    assert stock==79
    monkeypatch.setenv('DB_PATH',str(source))
    with pytest.raises(SystemExit,match='拒绝覆盖正在使用的数据库'):
        restore_backup(backup,source)

def test_missing_secrets_fail_closed():
    with pytest.raises(RuntimeError,match='init_env'):
        Settings(admin_key='',integration_key='',app_secret='',app_mode='staging',mock_payments=False).validate()

def test_database_directory_path_is_rejected(tmp_path):
    cfg=Settings(db_path=str(tmp_path),app_mode='demo',mock_payments=True,**KEYS)
    with pytest.raises(RuntimeError,match='不是文件'):
        create_app(cfg)

def test_production_profile_has_no_mock_payment_or_door(tmp_path):
    with pytest.raises(RuntimeError,match='Mock payments'):
        create_app(production_settings(tmp_path/'mock.sqlite3',mock_payments=True))
    with pytest.raises(RuntimeError,match='LIVE_DOOR_ENABLED'):
        create_app(production_settings(tmp_path/'door.sqlite3',live_door_enabled=True))
    with TestClient(create_app(production_settings(tmp_path/'prod.sqlite3'))) as client:
        health=client.get('/api/health').json()
        assert health['profile']=='production'
        assert health['real_payment'] is False and health['real_door'] is False
        assert client.get('/api/products').json()==[]
        assert client.post('/api/entry').status_code==503

def test_staging_alias_matches_pilot_gate(tmp_path):
    cfg=production_settings(tmp_path/'stage.sqlite3',app_mode='staging')
    assert cfg.profile=='staging'
    with TestClient(create_app(cfg)) as client:
        assert client.get('/api/health').json()['profile']=='staging'
        assert client.post('/api/payments/mock-confirm',json={'order_id':'x'*8}).status_code==401
