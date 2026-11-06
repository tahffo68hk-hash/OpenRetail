"""Local mock sandbox and SQLite inventory ledger. No WeChat network calls."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from conftest import visitor
from openretail.database import Database


def arm_wechat_failure(client):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail


def place(client, qty, request_id):
    auth=visitor(client)
    product=client.get('/api/products').json()[0]
    created=client.post('/api/orders',headers=auth,json={'request_id':request_id,
        'lines':[{'product_id':product['id'],'quantity':qty}]})
    assert created.status_code==201
    return auth, product, created.json()


def test_mock_query_notify_is_idempotent_and_unverified(client):
    arm_wechat_failure(client)
    auth, product, order=place(client, 2, 'mock-sandbox-order-001')
    started=client.post('/api/orders/'+order['id']+'/mock-checkout', headers=auth)
    assert started.status_code==200
    body=started.json()
    assert body['trade_state']=='NOTPAY' and body['verified']==0
    assert body['real_money'] is False and body['remote_call'] is False
    assert body['provider']=='MOCK_NOT_REAL_MONEY'
    assert client.post('/api/orders/'+order['id']+'/mock-checkout', headers=auth).json()['outcome']=='IDEMPOTENT'
    queried=client.get('/api/orders/'+order['id']+'/mock-payment', headers=auth).json()
    assert queried['trade_state']=='NOTPAY' and queried['verified']==0
    mismatch=client.post('/api/payments/mock-notify', headers=auth, json={
        'order_id':order['id'], 'event_id':'evt-mismatch', 'amount_cents':1})
    assert mismatch.status_code==422
    assert client.get('/api/products').json()[0]['stock']==product['stock']
    paid=client.post('/api/payments/mock-notify', headers=auth, json={
        'order_id':order['id'], 'event_id':'evt-ok', 'amount_cents':order['total_cents']})
    assert paid.status_code==200 and paid.json()['outcome']=='PAID' and paid.json()['verified']==0
    assert client.post('/api/payments/mock-notify', headers=auth, json={
        'order_id':order['id'], 'event_id':'evt-ok'}).json()['outcome']=='IDEMPOTENT'
    assert client.post('/api/payments/mock-notify', headers=auth, json={
        'order_id':order['id'], 'event_id':'evt-other'}).json()['outcome']=='IDEMPOTENT'
    after=client.get('/api/products').json()[0]
    assert after['stock']==product['stock']-2 and after['reserved_stock']==0
    success=client.get('/api/orders/'+order['id']+'/mock-payment', headers=auth).json()
    assert success['trade_state']=='SUCCESS' and success['verified']==0 and success['real_money'] is False
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT provider,verified FROM payments WHERE order_id=?',(order['id'],)).fetchone()
    assert row['provider']=='MOCK_NOT_REAL_MONEY' and row['verified']==0


def test_mock_close_and_timeout_release_reservation(client, admin_header):
    arm_wechat_failure(client)
    auth, product, order=place(client, 2, 'mock-close-order-0001')
    assert client.post('/api/orders/'+order['id']+'/mock-checkout', headers=auth).status_code==200
    closed=client.post('/api/admin/orders/'+order['id']+'/mock-close', headers=admin_header)
    assert closed.status_code==200 and closed.json()['outcome']=='CLOSED' and closed.json()['remote_call'] is False
    assert client.post('/api/admin/orders/'+order['id']+'/mock-close', headers=admin_header).json()['outcome']=='IDEMPOTENT'
    assert client.get('/api/products').json()[0]['stock']==product['stock']
    assert client.get('/api/products').json()[0]['reserved_stock']==0
    moves=client.get('/api/admin/stock-movements', headers=admin_header).json()
    assert sum(1 for row in moves if row['reason']=='MOCK_CLOSED' and row['reference']==order['id'])==1

    auth, product, order=place(client, 2, 'mock-timeout-order-001')
    assert client.post('/api/orders/'+order['id']+'/mock-checkout', headers=auth).status_code==200
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE orders SET expires_at=0 WHERE id=?',(order['id'],))
    listed=client.get('/api/products').json()[0]
    assert listed['stock']==product['stock'] and listed['reserved_stock']==0
    viewed=client.get('/api/orders/'+order['id']+'/mock-payment', headers=auth).json()
    assert viewed['order_status']=='EXPIRED' and viewed['trade_state']=='CLOSED'
    reconciled=client.post('/api/admin/orders/'+order['id']+'/reconcile-mock', headers=admin_header).json()
    assert reconciled['trade_state']=='CLOSED' and reconciled['remote_call'] is False
    assert client.post('/api/payments/mock-confirm', headers=auth, json={'order_id':order['id']}).json()['status']=='EXPIRED'


def test_wechat_pending_is_not_closed_by_mock_timeout(client, admin_header):
    arm_wechat_failure(client)
    auth, product, order=place(client, 1, 'external-pending-order-1')
    with client.app.state.db.tx() as conn:
        conn.execute('''UPDATE orders SET status='PAYMENT_PENDING', expires_at=0,
                        payment_reference='weixin://wxpay/bizpayurl?pr=TEST' WHERE id=?''',(order['id'],))
    client.get('/api/products')
    current=client.get('/api/orders/'+order['id'], headers=auth).json()
    assert current['status']=='PAYMENT_PENDING'
    assert client.get('/api/products').json()[0]['reserved_stock']==1
    assert client.get('/api/products').json()[0]['stock']==product['stock']
    assert client.post('/api/admin/orders/'+order['id']+'/mock-close', headers=admin_header).status_code==409
    assert client.post('/api/admin/orders/'+order['id']+'/reconcile-mock', headers=admin_header).status_code==409
    assert client.get('/api/products').json()[0]['reserved_stock']==1


def test_mock_refund_restores_stock_and_refuses_verified_payment(client, admin_header):
    arm_wechat_failure(client)
    auth, product, order=place(client, 2, 'mock-refund-order-0001')
    assert client.post('/api/payments/mock-confirm', headers=auth, json={'order_id':order['id']}).json()['status']=='PAID'
    assert client.get('/api/products').json()[0]['stock']==product['stock']-2
    refunded=client.post('/api/admin/orders/'+order['id']+'/mock-refund', headers=admin_header)
    assert refunded.status_code==200
    body=refunded.json()
    assert body['outcome']=='REFUNDED' and body['stock_restored'] is True
    assert body['verified']==0 and body['real_money'] is False and body['provider']=='MOCK_NOT_REAL_MONEY'
    assert client.get('/api/products').json()[0]['stock']==product['stock']
    assert client.get('/api/products').json()[0]['reserved_stock']==0
    second=client.post('/api/admin/orders/'+order['id']+'/mock-refund', headers=admin_header).json()
    assert second['outcome']=='IDEMPOTENT' and second['stock_restored'] is False
    assert client.get('/api/products').json()[0]['stock']==product['stock']
    moves=client.get('/api/admin/stock-movements', headers=admin_header).json()
    assert sum(1 for row in moves if row['reason']=='MOCK_REFUND_RESTORE' and row['reference']==order['id'])==1

    auth, product, other=place(client, 1, 'mock-refund-refuse-0002')
    assert client.post('/api/payments/mock-confirm', headers=auth, json={'order_id':other['id']}).status_code==200
    before=client.get('/api/products').json()[0]['stock']
    with client.app.state.db.tx() as conn:
        conn.execute("UPDATE payments SET provider='WECHAT_NATIVE', verified=1 WHERE order_id=?",(other['id'],))
    refused=client.post('/api/admin/orders/'+other['id']+'/mock-refund', headers=admin_header)
    assert refused.status_code==409
    assert client.get('/api/products').json()[0]['stock']==before


def test_ledger_tracks_race_cancel_pay_and_refund(client, admin_header):
    arm_wechat_failure(client)

    def balanced():
        body=client.get('/api/admin/inventory-ledger', headers=admin_header).json()
        assert body['system_of_record']=='sqlite' and body['balanced'] is True
        for row in body['products']:
            assert row['stock']==row['ledger_stock']
            assert row['reserved_stock']==row['ledger_reserved']
        return body

    balanced()
    product=client.get('/api/products').json()[0]
    assert client.post('/api/admin/products/'+str(product['id'])+'/adjust-stock', headers=admin_header,
        json={'quantity_delta':1-product['stock'],'reason':'count correction'}).status_code==200
    first, second=visitor(client), visitor(client)

    def reserve(item):
        who, request_id=item
        return client.post('/api/orders', headers=who, json={'request_id':request_id,
            'lines':[{'product_id':product['id'], 'quantity':1}]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(reserve, [(first, 'ledger-race-order-a'), (second, 'ledger-race-order-b')]))
    assert sorted(result.status_code for result in results)==[201, 409]
    winner=next(result for result in results if result.status_code==201)
    winner_auth=first if results[0] is winner else second
    assert client.post('/api/payments/mock-confirm', headers=winner_auth,
                       json={'order_id':winner.json()['id']}).status_code==200
    assert client.get('/api/products').json()[0]['stock']==0
    balanced()

    assert client.post('/api/admin/products/'+str(product['id'])+'/adjust-stock', headers=admin_header,
        json={'quantity_delta':5,'reason':'count correction'}).status_code==200
    auth, _, cancelled=place(client, 2, 'ledger-cancel-order-01')
    assert client.post('/api/orders/'+cancelled['id']+'/cancel', headers=auth).json()['status']=='CANCELLED'
    assert client.get('/api/products').json()[0]['stock']==5
    assert client.get('/api/products').json()[0]['reserved_stock']==0
    balanced()

    auth, _, sold=place(client, 2, 'ledger-refund-order-01')
    assert client.post('/api/payments/mock-confirm', headers=auth, json={'order_id':sold['id']}).json()['status']=='PAID'
    assert client.get('/api/products').json()[0]['stock']==3
    assert client.post('/api/admin/orders/'+sold['id']+'/mock-refund', headers=admin_header).json()['outcome']=='REFUNDED'
    assert client.get('/api/products').json()[0]['stock']==5
    body=balanced()
    reasons={row['reason'] for row in body['movements']}
    assert {'OPENING_BALANCE','ORDER_RESERVED','ORDER_CANCELLED','PAID_SALE','MOCK_REFUND_RESTORE'}<=reasons


def test_existing_orders_table_learns_refunded_status(tmp_path):
    path=tmp_path/'mid.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE products(id INTEGER PRIMARY KEY AUTOINCREMENT,barcode TEXT UNIQUE NOT NULL,name TEXT NOT NULL,
          price_cents INTEGER NOT NULL,stock INTEGER NOT NULL,reserved_stock INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE guest_sessions(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL);
        CREATE TABLE orders(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES guest_sessions(id),
          request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('PENDING','PAYMENT_PENDING','PAID','EXPIRED','CANCELLED','PAYMENT_REVIEW')),
          total_cents INTEGER NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,paid_at INTEGER,
          payment_reference TEXT, UNIQUE(session_id,request_id));
        ''')
        conn.execute("INSERT INTO products(barcode,name,price_cents,stock) VALUES('L1','Legacy',100,4)")
        conn.execute("INSERT INTO guest_sessions VALUES('s','hashed',1,9999999999)")
        conn.execute("INSERT INTO orders VALUES('o','s','req','finger','PAID',100,1,9999999999,2,NULL)")
    Database(str(path)).init(demo=False)
    with sqlite3.connect(path) as conn:
        sql=conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()[0]
        assert 'REFUNDED' in sql
        assert conn.execute("SELECT status FROM orders WHERE id='o'").fetchone()[0]=='PAID'
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
        opening=conn.execute("SELECT stock_delta FROM stock_movements WHERE reason='OPENING_BALANCE'").fetchone()
        assert opening[0]==4
