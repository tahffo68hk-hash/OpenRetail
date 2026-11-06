from conftest import visitor


def test_health_and_seed(client):
    h=client.get('/api/health').json()
    assert h['status']=='ok' and not h['real_door'] and not h['real_payment']
    assert len(client.get('/api/products').json())==8


def test_admin_protected(client,admin_header):
    assert client.get('/api/admin/overview').status_code==401
    assert client.get('/api/admin/overview',headers={'X-Admin-Key':'invalid'}).status_code==401
    r=client.get('/api/admin/overview',headers=admin_header)
    assert r.status_code==200 and r.json()['mode']=='STAFFED'


def test_unattended_mock_entry_flow(client,admin_header):
    auth=visitor(client)
    fail=client.post('/api/door/open',headers=auth)
    assert fail.status_code==409
    assert client.put('/api/admin/mode',headers=admin_header,json={'mode':'UNATTENDED'}).status_code==200
    ok=client.post('/api/door/open',headers=auth)
    assert ok.status_code==200 and ok.json()['result']=='SIMULATED'
    assert ok.json()['physical_door_opened'] is False
    overview=client.get('/api/admin/overview',headers=admin_header).json()
    assert overview['door_events']==2


def test_purchase_and_duplicate_pay(client,admin_header):
    auth=visitor(client)
    p=client.get('/api/products').json()[0]
    order_payload={'request_id':'idempotency-001','lines':[{'product_id':p['id'],'quantity':2}]}
    o=client.post('/api/orders',headers=auth,json=order_payload)
    assert o.status_code==201
    order=o.json()
    assert order['total_cents']==p['price_cents']*2
    assert order['status']=='PENDING'
    # Price is never accepted from guest
    assert client.get('/api/products').json()[0]['stock']==p['stock']
    replay=client.post('/api/orders',headers=auth,json=order_payload)
    assert replay.json()['id']==order['id']
    conflict=client.post('/api/orders',headers=auth,json={'request_id':'idempotency-001','lines':[{'product_id':p['id'],'quantity':1}]})
    assert conflict.status_code==409
    paid=client.post('/api/payments/mock-confirm',headers=auth,json={'order_id':order['id']})
    assert paid.status_code==200 and paid.json()['status']=='PAID'
    again=client.post('/api/payments/mock-confirm',headers=auth,json={'order_id':order['id']})
    assert again.status_code==200 and again.json()['status']=='PAID'
    assert client.get('/api/products').json()[0]['stock']==p['stock']-2
    assert client.get('/api/admin/overview',headers=admin_header).json()['paid_orders']==1


def test_order_session_isolation(client):
    first=visitor(client);second=visitor(client)
    p=client.get('/api/products').json()[0]
    order=client.post('/api/orders',headers=first,json={'request_id':'unique-order-1','lines':[{'product_id':p['id'],'quantity':1}]}).json()
    assert client.get('/api/orders/'+order['id'],headers=second).status_code==404
    assert client.post('/api/payments/mock-confirm',headers=second,json={'order_id':order['id']}).status_code==404


def test_reservation_protects_stock_adjustment_and_avoids_oversell(client,admin_header):
    first=visitor(client)
    p=client.get('/api/products').json()[0]
    order=client.post('/api/orders',headers=first,json={'request_id':'reserve-a-1',
        'lines':[{'product_id':p['id'],'quantity':2}]}).json()
    assert client.get('/api/products').json()[0]['available_stock']==p['stock']-2
    assert client.post('/api/admin/products',headers=admin_header,json={**p,'stock':1}).status_code==409
    paid=client.post('/api/payments/mock-confirm',headers=first,json={'order_id':order['id']})
    assert paid.status_code==200 and paid.json()['status']=='PAID'
    assert client.get('/api/products').json()[0]['stock']==p['stock']-2


def test_expired_order(client):
    auth=visitor(client);p=client.get('/api/products').json()[0]
    o=client.post('/api/orders',headers=auth,json={'request_id':'expire-test-1','lines':[{'product_id':p['id'],'quantity':1}]}).json()
    client.app.state.db
    with client.app.state.db.tx() as c:c.execute('UPDATE orders SET expires_at=0 WHERE id=?',(o['id'],))
    r=client.post('/api/payments/mock-confirm',headers=auth,json={'order_id':o['id']})
    assert r.status_code==200 and r.json()['status']=='EXPIRED'
    assert client.get('/api/orders/'+o['id'],headers=auth).json()['status']=='EXPIRED'


def test_no_mock_payment_in_non_demo(tmp_path):
    from openretail.config import Settings
    from openretail.main import create_app
    from fastapi.testclient import TestClient
    import pytest
    with pytest.raises(RuntimeError,match='Mock payments'):
        create_app(Settings(db_path=str(tmp_path/'x.db'),app_mode='pilot',
                            admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
                            mock_payments=True))


def test_live_door_switch_refused(tmp_path):
    from openretail.config import Settings
    from openretail.main import create_app
    import pytest
    with pytest.raises(RuntimeError,match='LIVE_DOOR_ENABLED'):
        create_app(Settings(db_path=str(tmp_path/'x.db'),app_mode='demo',
                            admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
                            mock_payments=True,live_door_enabled=True))


def test_concurrent_reservations_one_stock(tmp_path,admin_header):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from openretail.main import create_app
    from openretail.config import Settings
    cfg=Settings(db_path=str(tmp_path/'race.db'),admin_key='A'*40,
                 integration_key='I'*40,app_secret='S'*40,mock_payments=True)
    with TestClient(create_app(cfg)) as c:
        p=c.get('/api/products').json()[0]
        assert c.post('/api/admin/products',headers=admin_header,json={**p,'stock':1}).status_code==200
        a=visitor(c);b=visitor(c)
        def reserve(x):
            return c.post('/api/orders',headers=x[0],json={'request_id':x[1],
                'lines':[{'product_id':p['id'],'quantity':1}]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(reserve,[(a,'race-order-a'),(b,'race-order-b')]))
        assert sorted(r.status_code for r in result)==[201,409]
        first=next(r for r in result if r.status_code==201)
        first_auth=a if result[0] is first else b
        paid=c.post('/api/payments/mock-confirm',headers=first_auth,json={'order_id':first.json()['id']})
        assert paid.status_code==200
        assert c.get('/api/products').json()[0]['stock']==0
        assert c.get('/api/admin/overview',headers=admin_header).json()['paid_orders']==1


def test_example_placeholder_secrets_rejected(tmp_path):
    from openretail.config import Settings
    import pytest
    with pytest.raises(RuntimeError,match='placeholder'):
        Settings(db_path=str(tmp_path/'x.db'),app_mode='staging',mock_payments=False,
                 admin_key='REPLACE_WITH_RANDOM_ADMIN_KEY',
                 integration_key='I'*40,app_secret='S'*40).validate()
