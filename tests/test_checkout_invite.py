"""Staffed checkout invites are one-time and do not authorize a door. Demo entry stays open."""
import time
from pathlib import Path
from fastapi.testclient import TestClient
from openretail.config import Settings
from openretail.main import create_app
from openretail.security import digest,password_hash


def sessions(client):
    with client.app.state.db.connect() as conn:
        return conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']


def test_invite_is_single_use_and_demo_entry_does_not_need_one(client, admin_header):
    store=client.get('/api/public/store').json()
    assert store['demo'] is True and store['invite_required'] is False
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert client.post('/api/admin/checkout-invite').status_code==401
    created=client.post('/api/admin/checkout-invite',headers=admin_header)
    assert created.status_code==200
    invite=created.json()
    assert invite['lifetime_seconds']==120
    assert abs(invite['expires_at']-time.time()-120)<5
    assert invite['identity_verified'] is False and invite['door_authorized'] is False
    assert invite['physical_door_opened'] is False and invite['payment_required_to_leave'] is False
    assert len(invite['invite'])>=24
    audit=client.get('/api/admin/audit',headers=admin_header).json()
    created_rows=[row for row in audit['events'] if row['action']=='INVITE_CREATED']
    assert created_rows and created_rows[0]['detail']=='lifetime_seconds=120'
    assert created_rows[0]['actor']=='demo-admin-key'
    assert invite['invite'] not in created_rows[0]['detail']
    first=client.post('/api/entry/redeem',json={'invite':invite['invite']})
    assert first.status_code==200
    body=first.json()
    assert body['identity_verified'] is False and body['door_authorized'] is False
    assert body['physical_door_opened'] is False and body['payment_required_to_leave'] is False
    assert body['virtual_event']=='CHECKOUT_SESSION'
    before_reuse=sessions(client)
    reused=client.post('/api/entry/redeem',json={'invite':invite['invite']})
    assert reused.status_code==401 and reused.json()['detail']=='邀请码已使用'
    assert sessions(client)==before_reuse
    fresh=client.post('/api/admin/checkout-invite',headers=admin_header).json()
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE checkout_invites SET expires_at=0 WHERE invite_hash=?',(digest(fresh['invite']),))
        doors=conn.execute('SELECT COUNT(*) n FROM door_events WHERE result=?',('SESSION_ISSUED',)).fetchone()['n']
    before_expire=sessions(client)
    expired=client.post('/api/entry/redeem',json={'invite':fresh['invite']})
    assert expired.status_code==401 and expired.json()['detail']=='邀请码已过期'
    assert sessions(client)==before_expire
    direct=client.post('/api/entry')
    assert direct.status_code==200
    assert direct.json()['identity_verified'] is False and direct.json()['physical_door_opened'] is False
    guest={'Authorization':'Bearer '+direct.json()['guest_token']}
    product=client.get('/api/products').json()[0]
    order=client.post('/api/orders',headers=guest,json={'request_id':'demo-without-invite-01',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert order.status_code==201
    assert client.post('/api/payments/mock-confirm',headers=guest,json={'order_id':order.json()['id']}).json()['payment_kind']=='MOCK_NOT_REAL_MONEY'
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM door_events WHERE result=?',('SESSION_ISSUED',)).fetchone()['n']==doors+1


def test_non_demo_anonymous_entry_asks_for_an_invite(tmp_path):
    cfg=Settings(db_path=str(Path(tmp_path)/'pilot.sqlite3'),app_mode='pilot',
        admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
        admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
        trusted_proxy_tls=True,public_base_url='https://pilot.example.invalid',mock_payments=False)
    with TestClient(create_app(cfg),base_url='https://pilot.example.invalid') as pilot:
        store=pilot.get('/api/public/store').json()
        assert store['demo'] is False and store['invite_required'] is True
        assert store['identity_verified'] is False and store['door_authorized'] is False
        assert store['physical_door_opened'] is False
        denied=pilot.post('/api/entry')
        assert denied.status_code==503
        assert denied.json()['detail']=='请向店员领取结账邀请码后再结账。这不是身份核验，也不会开门。'
        assert pilot.post('/api/admin/checkout-invite').status_code==401
