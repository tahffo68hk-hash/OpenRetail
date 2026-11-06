"""Staff can open another store-local date and look up one order by id."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from conftest import visitor

SHANGHAI=ZoneInfo('Asia/Shanghai')


def test_chosen_date_and_order_lookup_keep_mock_money_separate(client, admin_header):
    local_day=datetime.now(SHANGHAI).date()
    yesterday=local_day-timedelta(days=1)
    one_am=datetime(local_day.year, local_day.month, local_day.day, 1, 0, tzinfo=SHANGHAI)
    afternoon=datetime(yesterday.year, yesterday.month, yesterday.day, 15, 0, tzinfo=SHANGHAI)
    assert one_am.astimezone(timezone.utc).date()==local_day-timedelta(days=1)
    assert client.get(f'/api/admin/orders?today=1&date={yesterday.isoformat()}').status_code==401
    assert client.get('/api/admin/orders?order_id=missing-order').status_code==401
    assert client.get(f'/api/admin/orders.csv?date={yesterday.isoformat()}').status_code==401
    assert client.get('/api/admin/orders.csv?order_id=missing-order').status_code==401
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    morning=client.post('/api/orders', headers=guest, json={'request_id':'day-lookup-0100',
        'lines':[{'product_id':product['id'], 'quantity':1}]}).json()
    assert client.post('/api/payments/mock-confirm', headers=guest, json={'order_id':morning['id']}).json()['real_money'] is False
    earlier=client.post('/api/orders', headers=guest, json={'request_id':'day-lookup-yesterday',
        'lines':[{'product_id':product['id'], 'quantity':1}]}).json()
    assert client.post('/api/payments/mock-confirm', headers=guest, json={'order_id':earlier['id']}).json()['payment_kind']=='MOCK_NOT_REAL_MONEY'
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE orders SET created_at=?, paid_at=? WHERE id=?', (int(one_am.timestamp()), int(one_am.timestamp()), morning['id']))
        conn.execute('UPDATE orders SET created_at=?, paid_at=? WHERE id=?', (int(afternoon.timestamp()), int(afternoon.timestamp()), earlier['id']))
        stock=conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']
        movements=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    today=client.get(f'/api/admin/orders?today=1&date={local_day.isoformat()}', headers=admin_header).json()
    prior=client.get(f'/api/admin/orders?today=1&date={yesterday.isoformat()}', headers=admin_header).json()
    assert today['local_date']==local_day.isoformat() and prior['local_date']==yesterday.isoformat()
    assert {row['id'] for row in today['orders']}=={morning['id']}
    assert {row['id'] for row in prior['orders']}=={earlier['id']}
    assert today['orders'][0]['local_time']==one_am.strftime('%Y-%m-%d %H:%M')
    assert today['orders'][0]['money_label']=='MOCK_NOT_REAL_MONEY'
    assert today['orders'][0]['verified']==0 and today['orders'][0]['real_money'] is False
    assert product['name'] in today['orders'][0]['items']
    assert today['physical_door_opened'] is False and today['real_door_enabled'] is False
    found=client.get('/api/admin/orders?order_id='+earlier['id'], headers=admin_header)
    assert found.status_code==200
    body=found.json()
    assert body['local_date']==yesterday.isoformat()
    assert len(body['orders'])==1 and body['orders'][0]['id']==earlier['id']
    assert body['orders'][0]['money_label']=='MOCK_NOT_REAL_MONEY' and body['orders'][0]['real_money'] is False
    assert client.get('/api/admin/orders?order_id='+earlier['id'][:8], headers=admin_header).status_code==404
    missing=client.get('/api/admin/orders?order_id=not-a-real-order', headers=admin_header)
    assert missing.status_code==404 and missing.json()['detail']=='订单不存在'
    crossed=client.get(f'/api/admin/orders?order_id={morning["id"]}&date={yesterday.isoformat()}', headers=admin_header)
    assert crossed.status_code==404 and crossed.json()['detail']=='该日期没有这张订单'
    assert client.get('/api/admin/orders?today=1&date=2026-13-40', headers=admin_header).status_code==422
    exported=client.get(f'/api/admin/orders.csv?date={yesterday.isoformat()}', headers=admin_header)
    assert exported.status_code==200
    header,*data=exported.text.splitlines()
    assert header=='order_id,local_time,timezone,status,amount_yuan,payment_label,real_money,items'
    assert earlier['id'] in exported.text and morning['id'] not in exported.text
    assert 'MOCK_NOT_REAL_MONEY' in exported.text and ',false,' in exported.text
    one=client.get('/api/admin/orders.csv?order_id='+morning['id'], headers=admin_header)
    assert one.status_code==200
    assert morning['id'] in one.text and earlier['id'] not in one.text
    assert client.get(f'/api/admin/orders.csv?order_id={morning["id"]}&date={yesterday.isoformat()}', headers=admin_header).status_code==404
    overview=client.get('/api/admin/overview', headers=admin_header).json()
    assert overview['today_verified_revenue_cents']==0 and overview['verified_revenue_cents']==0
    assert overview['today_simulated_revenue_cents']==product['price_cents']
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']==stock
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==movements
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
        assert conn.execute('SELECT COUNT(*) n FROM payments WHERE verified=1').fetchone()['n']==0
