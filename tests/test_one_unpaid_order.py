"""One session may hold only one unpaid order. A second checkout must not reserve again."""
from conftest import visitor


def snapshot(client, product_id):
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        orders=conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(product_id,)).fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    return row['stock'],row['reserved_stock'],orders,moves,doors


def test_second_unpaid_order_is_rejected_until_the_first_is_closed(client, admin_header):
    assert client.post('/api/orders',json={'request_id':'no-session-order-01','lines':[{'product_id':1,'quantity':1}]}).status_code==401
    guest=visitor(client)
    other=visitor(client)
    product=client.get('/api/products').json()[0]
    first=client.post('/api/orders',headers=guest,json={'request_id':'one-unpaid-first-0001',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert first.status_code==201
    order=first.json()
    assert order['status']=='PENDING' and order['expires_at']==order['created_at']+900
    held=snapshot(client,product['id'])
    duplicate=client.post('/api/orders',headers=guest,json={'request_id':'one-unpaid-second-0002',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert duplicate.status_code==409
    assert duplicate.json()['detail']=='已有待付款订单，请先完成付款或取消订单'
    assert snapshot(client,product['id'])==held
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    replay=client.post('/api/orders',headers=guest,json={'request_id':'one-unpaid-first-0001',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert replay.status_code==201 and replay.json()['id']==order['id']
    assert snapshot(client,product['id'])==held
    theirs=client.post('/api/orders',headers=other,json={'request_id':'one-unpaid-other-0003',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert theirs.status_code==201 and theirs.json()['id']!=order['id']
    assert snapshot(client,product['id'])[1]==held[1]+1
    cancelled=client.post('/api/orders/'+order['id']+'/cancel',headers=guest)
    assert cancelled.status_code==200 and cancelled.json()['status']=='CANCELLED'
    again=client.post('/api/orders',headers=guest,json={'request_id':'one-unpaid-after-cancel',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert again.status_code==201 and again.json()['id']!=order['id']
    paid=client.post('/api/payments/mock-confirm',headers=guest,json={'order_id':again.json()['id']})
    assert paid.status_code==200 and paid.json()['payment_kind']=='MOCK_NOT_REAL_MONEY' and paid.json()['real_money'] is False
    after_pay=client.post('/api/orders',headers=guest,json={'request_id':'one-unpaid-after-pay',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert after_pay.status_code==201
    assert client.post('/api/orders/'+after_pay.json()['id']+'/refund',headers=guest).status_code==404
    assert client.get('/api/admin/overview',headers=admin_header).json()['real_door_enabled'] is False
