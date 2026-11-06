"""Today's order list and CSV use the store timezone and keep mock money labeled."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from conftest import visitor

SHANGHAI=ZoneInfo('Asia/Shanghai')


def test_today_orders_and_csv_keep_mock_money_separate(client, admin_header):
    assert client.get('/api/admin/orders?today=1').status_code==401
    assert client.get('/api/admin/orders.csv').status_code==401
    local_day=datetime.now(SHANGHAI).date()
    one_am=datetime(local_day.year, local_day.month, local_day.day, 1, 0, tzinfo=SHANGHAI)
    previous_evening=one_am-timedelta(hours=2)
    assert one_am.astimezone(timezone.utc).date()==local_day-timedelta(days=1)
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    morning=client.post('/api/orders', headers=guest, json={'request_id':'today-list-0100',
        'lines':[{'product_id':product['id'], 'quantity':1}]}).json()
    evening=client.post('/api/orders', headers=guest, json={'request_id':'today-list-previous',
        'lines':[{'product_id':product['id'], 'quantity':1}]}).json()
    assert client.post('/api/payments/mock-confirm', headers=guest, json={'order_id':morning['id']}).json()['payment_kind']=='MOCK_NOT_REAL_MONEY'
    assert client.post('/api/payments/mock-confirm', headers=guest, json={'order_id':evening['id']}).json()['real_money'] is False
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE orders SET created_at=?, paid_at=? WHERE id=?', (int(one_am.timestamp()), int(one_am.timestamp()), morning['id']))
        conn.execute('UPDATE orders SET created_at=?, paid_at=? WHERE id=?', (int(previous_evening.timestamp()), int(previous_evening.timestamp()), evening['id']))
        stock=conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']
        movements=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    listed=client.get('/api/admin/orders?today=1', headers=admin_header)
    assert listed.status_code==200
    body=listed.json()
    assert body['timezone']=='Asia/Shanghai'
    assert body['physical_door_opened'] is False
    assert body['payment_required_to_leave'] is False
    assert body['real_door_enabled'] is False
    ids={row['id'] for row in body['orders']}
    assert morning['id'] in ids and evening['id'] not in ids
    row=next(item for item in body['orders'] if item['id']==morning['id'])
    assert row['local_time']==one_am.strftime('%Y-%m-%d %H:%M')
    assert row['total_cents']==product['price_cents']
    assert row['status']=='PAID'
    assert row['money_label']=='MOCK_NOT_REAL_MONEY'
    assert row['verified']==0 and row['real_money'] is False
    assert row['provider']=='MOCK_NOT_REAL_MONEY'
    assert product['name'] in row['items']
    overview=client.get('/api/admin/overview', headers=admin_header).json()
    assert overview['today_verified_revenue_cents']==0
    assert overview['verified_revenue_cents']==0
    assert overview['today_simulated_revenue_cents']==product['price_cents']
    before=client.get('/api/admin/audit', headers=admin_header).json()
    assert 'ORDERS_EXPORTED' not in {row['action'] for row in before['events']}
    exported=client.get('/api/admin/orders.csv', headers=admin_header)
    assert exported.status_code==200
    assert exported.headers['content-type'].startswith('text/csv')
    assert exported.headers['x-openretail-live-replaced']=='false'
    text=exported.text
    header, data=text.splitlines()
    assert header=='order_id,local_time,timezone,status,amount_yuan,payment_label,real_money,items'
    assert morning['id'] in data and evening['id'] not in data
    assert 'Asia/Shanghai' in data
    assert 'MOCK_NOT_REAL_MONEY' in data
    assert ',false,' in data
    assert 'A'*10 not in text
    assert 'mchid' not in text.lower() and 'api_key' not in text.lower()
    audit=client.get('/api/admin/audit', headers=admin_header).json()
    assert ('ORDERS_EXPORTED','count=1;timezone=Asia/Shanghai','demo-admin-key') in {
        (row['action'], row['detail'], row['actor']) for row in audit['events']}
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']==stock
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==movements
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
        assert conn.execute("SELECT COUNT(*) n FROM payments WHERE verified=1").fetchone()['n']==0
