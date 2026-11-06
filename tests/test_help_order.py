"""A help note can point at an existing order without changing the note or the stock."""
from conftest import visitor


def test_help_order_lookup_keeps_status_and_stock(client, admin_header):
    assert client.get('/api/admin/help-requests').status_code==401
    assert client.get('/api/admin/orders?order_id=missing-order').status_code==401
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    created=client.post('/api/orders',headers=guest,json={'request_id':'help-link-order-0001',
        'lines':[{'product_id':product['id'],'quantity':1}]}).json()
    paid=client.post('/api/payments/mock-confirm',headers=guest,json={'order_id':created['id']})
    assert paid.status_code==200 and paid.json()['payment_kind']=='MOCK_NOT_REAL_MONEY'
    assert paid.json()['real_money'] is False and paid.json()['verified']==0
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    linked=client.post('/api/help',headers=guest,json={'message':'请到货架帮忙','order_id':created['id']})
    assert linked.status_code==201
    assert linked.json()['order_id']==created['id']
    assert linked.json()['physical_door_opened'] is False and linked.json()['payment_required_to_leave'] is False
    bare=client.post('/api/help',headers=guest,json={'message':'没有带订单'})
    assert bare.status_code==201 and bare.json()['order_id'] is None
    listed=client.get('/api/admin/help-requests',headers=admin_header).json()
    assert listed['physical_door_opened'] is False
    rows={row['id']:row for row in listed['requests']}
    assert rows[linked.json()['id']]['status']=='OPEN'
    assert rows[linked.json()['id']]['order_id']==created['id']
    assert rows[linked.json()['id']]['session_id']
    assert rows[bare.json()['id']]['order_id'] is None
    assert rows[bare.json()['id']]['status']=='OPEN'
    found=client.get('/api/admin/orders?order_id='+rows[linked.json()['id']]['order_id'],headers=admin_header)
    assert found.status_code==200
    body=found.json()
    assert body['orders'][0]['id']==created['id']
    assert body['orders'][0]['money_label']=='MOCK_NOT_REAL_MONEY' and body['orders'][0]['real_money'] is False
    assert body['orders'][0]['verified']==0
    assert product['name'] in body['orders'][0]['items']
    assert body['physical_door_opened'] is False
    again=client.get('/api/admin/help-requests',headers=admin_header).json()
    again_rows={row['id']:row for row in again['requests']}
    assert again_rows[linked.json()['id']]['status']=='OPEN'
    assert again_rows[bare.json()['id']]['status']=='OPEN'
    acked=client.post(f"/api/admin/help-requests/{bare.json()['id']}/status",headers=admin_header,
                      json={'status':'ACKNOWLEDGED'})
    assert acked.status_code==200 and acked.json()['status']=='ACKNOWLEDGED'
    assert acked.json()['physical_door_opened'] is False
    still=client.get('/api/admin/help-requests',headers=admin_header).json()
    still_rows={row['id']:row for row in still['requests']}
    assert still_rows[linked.json()['id']]['status']=='OPEN'
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
        assert conn.execute('SELECT COUNT(*) n FROM payments WHERE verified=1').fetchone()['n']==0
