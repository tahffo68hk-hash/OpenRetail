"""Staff can see unpaid holds and release them through the existing close path."""
from conftest import visitor


def levels(client, product_id):
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        payments=conn.execute('SELECT COUNT(*) n FROM payments').fetchone()['n']
    return row['stock'],row['reserved_stock'],doors,payments


def test_staff_can_release_an_unpaid_hold_without_touching_on_hand(client, admin_header):
    assert client.get('/api/admin/orders/holding').status_code==401
    assert client.post('/api/admin/orders/missing/mock-close').status_code==401
    guest=visitor(client)
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000081008','name':'占用库存','price_cents':150,'stock':5,'active':True}).json()
    order=client.post('/api/orders',headers=guest,json={'request_id':'holding-order-0001',
        'lines':[{'product_id':made['id'],'quantity':2}]}).json()
    assert order['status']=='PENDING' and order['real_money'] is False
    assert levels(client,made['id'])[:2]==(5,2)
    listed=client.get('/api/admin/orders/holding',headers=admin_header)
    assert listed.status_code==200
    body=listed.json()
    assert body['physical_door_opened'] is False and body['real_door_enabled'] is False
    assert body['payment_required_to_leave'] is False
    found=next(row for row in body['orders'] if row['id']==order['id'])
    assert found['status']=='PENDING' and found['closable'] is True and found['unpaid'] is True
    assert found['money_label']=='UNPAID' and found['real_money'] is False
    assert found['note']=='未付款 · 非真实资金'
    assert found['total_cents']==300 and '占用库存 x2'==found['items']
    assert found['local_time'] and found['timezone']=='Asia/Shanghai'
    assert 'A'*10 not in str(found)
    doors=levels(client,made['id'])[2]
    closed=client.post('/api/admin/orders/'+order['id']+'/mock-close',headers=admin_header)
    assert closed.status_code==200
    assert closed.json()['outcome']=='CLOSED' and closed.json()['remote_call'] is False
    assert closed.json()['real_money'] is False and closed.json()['stock_changed'] is False
    assert closed.json()['physical_door_opened'] is False
    assert levels(client,made['id'])[:2]==(5,0)
    again=client.post('/api/admin/orders/'+order['id']+'/mock-close',headers=admin_header).json()
    assert again['outcome']=='IDEMPOTENT'
    assert levels(client,made['id'])[:2]==(5,0)
    moves=client.get('/api/admin/stock-movements',headers=admin_header).json()
    assert sum(1 for row in moves if row['reason']=='MOCK_CLOSED' and row['reference']==order['id'])==1
    audit=client.get('/api/admin/audit',headers=admin_header).json()
    closed_rows=[row for row in audit['events'] if row['action']=='ORDER_CLOSED' and row['detail']==order['id']]
    assert len(closed_rows)==1 and closed_rows[0]['actor']=='demo-admin-key'
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    assert all(row['id']!=order['id'] for row in client.get('/api/admin/orders/holding',headers=admin_header).json()['orders'])
    paid=client.post('/api/orders',headers=guest,json={'request_id':'holding-paid-0002',
        'lines':[{'product_id':made['id'],'quantity':1}]}).json()
    assert client.post('/api/payments/mock-confirm',headers=guest,json={'order_id':paid['id']}).json()['real_money'] is False
    refused=client.post('/api/admin/orders/'+paid['id']+'/mock-close',headers=admin_header)
    assert refused.status_code==409
    assert levels(client,made['id'])[:2]==(4,0)
    assert levels(client,made['id'])[2]==doors
    assert all(row['id']!=paid['id'] for row in client.get('/api/admin/orders/holding',headers=admin_header).json()['orders'])
    external=client.post('/api/orders',headers=guest,json={'request_id':'holding-external-0003',
        'lines':[{'product_id':made['id'],'quantity':1}]}).json()
    with client.app.state.db.tx() as conn:
        conn.execute('''UPDATE orders SET status='PAYMENT_PENDING', payment_reference='weixin://wxpay/bizpayurl?pr=TEST'
                        WHERE id=?''',(external['id'],))
    visible=next(row for row in client.get('/api/admin/orders/holding',headers=admin_header).json()['orders'] if row['id']==external['id'])
    assert visible['closable'] is False and visible['real_money'] is False and visible['money_label']=='UNPAID'
    assert '不能在这里释放' in visible['note']
    blocked=client.post('/api/admin/orders/'+external['id']+'/mock-close',headers=admin_header)
    assert blocked.status_code==409
    assert levels(client,made['id'])[:2]==(4,1)
    assert client.get('/api/admin/overview',headers=admin_header).json()['verified_revenue_cents']==0
