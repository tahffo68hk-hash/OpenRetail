"""An expired guest token is rejected without cancelling the unpaid order."""
from pathlib import Path
from fastapi.testclient import TestClient
from openretail.config import Settings
from openretail.main import create_app
from openretail.security import password_hash
from conftest import visitor


def test_expired_guest_token_keeps_the_unpaid_hold(client):
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    created=client.post('/api/orders',headers=guest,json={'request_id':'guest-expiry-hold-01',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert created.status_code==201
    order=created.json()
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        status=conn.execute('SELECT status FROM orders WHERE id=?',(order['id'],)).fetchone()['status']
    assert status=='PENDING' and stock['reserved_stock']>=1
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE guest_sessions SET expires_at=0 WHERE id=?',(client.get('/api/entry/status',headers=guest).json()['session_id'],))
    denied=client.get('/api/orders',headers=guest)
    assert denied.status_code==401 and denied.json()['detail']=='访客会话已过期'
    assert client.get('/api/entry/status',headers=guest).json()['detail']=='访客会话已过期'
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        still=conn.execute('SELECT status,expires_at,created_at FROM orders WHERE id=?',(order['id'],)).fetchone()
    assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
    assert still['status']=='PENDING' and still['expires_at']==still['created_at']+900
    fresh=client.post('/api/entry')
    assert fresh.status_code==200 and fresh.json()['identity_verified'] is False
    assert fresh.json()['physical_door_opened'] is False
    live=client.get('/api/entry/status',headers={'Authorization':'Bearer '+fresh.json()['guest_token']})
    assert live.status_code==200
    body=live.json()
    assert body['expires_local'] and body['expires_timezone']=='Asia/Shanghai'
    assert body['identity_verified'] is False and body['door_authorized'] is False
    assert body['physical_door_opened'] is False
    store=client.get('/api/public/store').json()
    assert store['demo'] is True and store['invite_required'] is False
    page=Path('web/app.js').read_text(encoding='utf-8')
    assert '访客会话已过期。可以再次使用生成访客会话。' in page
    assert '请向店员领取结账邀请码。这不是身份核验，也不会开门。' in page
    assert '可能已过期' not in page


def test_non_demo_store_still_requires_an_invite(tmp_path):
    cfg=Settings(db_path=str(Path(tmp_path)/'pilot.sqlite3'),app_mode='pilot',
        admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
        admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
        trusted_proxy_tls=True,public_base_url='https://pilot.example.invalid',mock_payments=False)
    with TestClient(create_app(cfg),base_url='https://pilot.example.invalid') as pilot:
        store=pilot.get('/api/public/store').json()
        assert store['invite_required'] is True and store['demo'] is False
        assert store['identity_verified'] is False and store['door_authorized'] is False
        denied=pilot.post('/api/entry')
        assert denied.status_code==503 and '请向店员领取结账邀请码' in denied.json()['detail']
        assert '不会开门' in denied.json()['detail']
