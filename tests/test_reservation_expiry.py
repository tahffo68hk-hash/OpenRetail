"""Show the existing 15-minute hold. The timer still ignores non-mock payment reservations."""
from datetime import datetime
from zoneinfo import ZoneInfo
from conftest import visitor

SHANGHAI=ZoneInfo('Asia/Shanghai')


def levels(client, product_id):
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    return row['stock'],row['reserved_stock'],doors


def test_unpaid_hold_shows_expiry_and_non_mock_pending_stays_reserved(client, admin_header):
    assert client.get('/api/admin/orders/holding').status_code==401
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    created=client.post('/api/orders',headers=guest,json={'request_id':'expiry-show-0001',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert created.status_code==201
    order=created.json()
    assert order['status']=='PENDING' and order['payment_kind']=='UNPAID' and order['real_money'] is False
    assert order['expires_at']==order['created_at']+900
    assert order['expires_timezone']=='Asia/Shanghai'
    expected=datetime.fromtimestamp(order['expires_at'],SHANGHAI).strftime('%Y-%m-%d %H:%M')
    assert order['expires_local']==expected
    assert 800<=order['expires_in_seconds']<=900
    stock,reserved,doors=levels(client,product['id'])
    listed=client.get('/api/admin/orders/holding',headers=admin_header)
    assert listed.status_code==200
    body=listed.json()
    assert body['physical_door_opened'] is False and body['real_door_enabled'] is False
    row=next(item for item in body['orders'] if item['id']==order['id'])
    assert row['expires_local']==expected and row['expires_timezone']=='Asia/Shanghai'
    assert row['money_label']=='UNPAID' and row['real_money'] is False and row['closable'] is True
    assert 800<=row['expires_in_seconds']<=900
    assert levels(client,product['id'])==(stock,reserved,doors)
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE orders SET expires_at=0 WHERE id=?',(order['id'],))
    timed=client.get('/api/orders',headers=guest).json()[0]
    assert timed['status']=='EXPIRED' and timed['payment_kind']=='TIMEOUT_UNPAID'
    assert timed['real_money'] is False
    assert levels(client,product['id'])[:2]==(stock,0)
    external=client.post('/api/orders',headers=guest,json={'request_id':'expiry-wechat-0002',
        'lines':[{'product_id':product['id'],'quantity':1}]}).json()
    with client.app.state.db.tx() as conn:
        conn.execute('''UPDATE orders SET status='PAYMENT_PENDING', expires_at=0,
                        payment_reference='weixin://wxpay/bizpayurl?pr=TEST' WHERE id=?''',(external['id'],))
    held=levels(client,product['id'])
    client.get('/api/products')
    client.get('/api/orders',headers=guest)
    assert client.get('/api/orders/'+external['id'],headers=guest).json()['status']=='PAYMENT_PENDING'
    assert levels(client,product['id'])[:2]==held[:2]
    assert client.get('/api/admin/overview',headers=admin_header).json()['verified_revenue_cents']==0
