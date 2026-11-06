"""Demo startup, customer order labels, and virtual door events."""
import os
import subprocess
import sys
from conftest import visitor


def test_clean_demo_import_boots_without_prior_secrets(tmp_path):
    env=os.environ.copy()
    for key in ('ADMIN_KEY','INTEGRATION_KEY','APP_SECRET','ADMIN_PASSWORD_HASH','PUBLIC_BASE_URL','TRUSTED_PROXY_TLS','PAYMENT_PROVIDER'):
        env.pop(key,None)
    env.update(APP_MODE='demo',MOCK_PAYMENTS_ENABLED='true',LIVE_DOOR_ENABLED='false',
               DB_PATH=str(tmp_path/'clean-demo.sqlite3'))
    script=r'''
import openretail.main as main
assert "app" not in vars(main)
from openretail.config import Settings
from openretail.main import create_app
from fastapi.testclient import TestClient
cfg=Settings(admin_key="",integration_key="",app_secret="",app_mode="demo",mock_payments=True,live_door_enabled=False)
cfg.validate()
assert cfg.demo_secrets_generated and len(cfg.admin_key)>=24
assert not cfg.admin_key.startswith("REPLACE_WITH_")
try:
    Settings(admin_key="",integration_key="",app_secret="",app_mode="demo",mock_payments=True,live_door_enabled=True).validate()
except RuntimeError as exc:
    assert "LIVE_DOOR_ENABLED" in str(exc)
else:
    raise SystemExit("live door was accepted")
with TestClient(create_app(cfg)) as client:
    health=client.get("/api/health").json()
    assert health["status"]=="ok" and health["real_door"] is False and health["real_payment"] is False
app=main.app
assert app is main.app
print("DEMO_OK")
'''
    done=subprocess.run([sys.executable,'-c',script],cwd=str(tmp_path.parent and __import__('pathlib').Path(__file__).resolve().parents[1]),
                        env=env,capture_output=True,text=True)
    assert done.returncode==0, done.stderr
    assert 'DEMO_OK' in done.stdout
    assert 'ephemeral ADMIN_KEY' in done.stderr
    assert 'ADMIN_KEY=' not in done.stdout
    staging=env.copy()
    staging['APP_MODE']='staging'
    staging['MOCK_PAYMENTS_ENABLED']='false'
    blocked=subprocess.run([sys.executable,'-c',r'''
import openretail.main as main
assert "app" not in vars(main)
try:
    main.app
except RuntimeError as exc:
    text=str(exc)
    assert "init_env" in text or "PUBLIC_BASE_URL" in text or "ADMIN_PASSWORD_HASH" in text
    print("STAGING_BLOCKED")
else:
    raise SystemExit("staging booted without config")
'''],cwd=str(__import__('pathlib').Path(__file__).resolve().parents[1]),env=staging,capture_output=True,text=True)
    assert blocked.returncode==0, blocked.stderr
    assert 'STAGING_BLOCKED' in blocked.stdout


def test_guest_order_history_separates_mock_unpaid_and_timeout(client):
    first=visitor(client)
    second=visitor(client)
    product=client.get('/api/products').json()[0]
    created=client.post('/api/orders',headers=first,json={'request_id':'customer-history-0001',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert created.status_code==201
    pending=client.get('/api/orders',headers=first).json()
    assert pending[0]['status']=='PENDING' and pending[0]['payment_kind']=='UNPAID'
    assert pending[0]['real_money'] is False and pending[0]['verified']==0
    assert client.get('/api/orders',headers=second).json()==[]
    paid=client.post('/api/payments/mock-confirm',headers=first,json={'order_id':created.json()['id']})
    assert paid.status_code==200
    assert paid.json()['payment_kind']=='MOCK_NOT_REAL_MONEY' and paid.json()['verified']==0
    assert paid.json()['real_money'] is False
    again=client.get('/api/orders',headers=first).json()[0]
    assert again['payment_kind']=='MOCK_NOT_REAL_MONEY' and again['status']=='PAID'
    auth=visitor(client)
    expiring=client.post('/api/orders',headers=auth,json={'request_id':'customer-timeout-0002',
        'lines':[{'product_id':product['id'],'quantity':1}]}).json()
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE orders SET expires_at=0 WHERE id=?',(expiring['id'],))
    timed=client.get('/api/orders',headers=auth).json()[0]
    assert timed['status']=='EXPIRED' and timed['payment_kind']=='TIMEOUT_UNPAID'
    assert timed['real_money'] is False
    assert client.post('/api/orders/'+paid.json()['id']+'/refund',headers=first).status_code==404


def test_virtual_entry_events_keep_the_physical_door_closed(client,admin_header):
    auth=visitor(client)
    status=client.get('/api/entry/status',headers=auth).json()
    assert status['physical_door_opened'] is False and status['door_authorized'] is False
    assert status['identity_verified'] is False and status['virtual_only'] is True
    assert status['events'][0]['result']=='SESSION_ISSUED'
    assert status['events'][0]['detail']=='NO PHYSICAL UNLOCK'
    assert client.post('/api/door/open',headers=auth).status_code==409
    assert client.put('/api/admin/mode',headers=admin_header,json={'mode':'UNATTENDED'}).status_code==200
    opened=client.post('/api/door/open',headers=auth).json()
    assert opened['result']=='SIMULATED' and opened['physical_door_opened'] is False
    assert {row['result'] for row in opened['events']}>= {'SESSION_ISSUED','SIMULATED'}
    assert all(row['provider']=='LOCAL_SIMULATOR' for row in opened['events'])
