"""Unpaid order lines can change quantity without breaking reservations."""
from conftest import visitor


def stock_of(client, product_id):
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        payments=conn.execute('SELECT COUNT(*) n FROM payments').fetchone()['n']
    return row['stock'],row['reserved_stock'],moves,doors,payments


def test_quantity_change_reserves_only_what_is_sellable(client, admin_header):
    assert client.post('/api/orders/missing/lines',json={'product_id':1,'quantity':2}).status_code==401
    guest=visitor(client)
    other=visitor(client)
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000080008','name':'可改数量','price_cents':100,'stock':3,'active':True}).json()
    created=client.post('/api/orders',headers=guest,json={'request_id':'line-qty-0001',
        'lines':[{'product_id':made['id'],'quantity':1}]})
    assert created.status_code==201
    order=created.json()
    assert order['total_cents']==100 and order['real_money'] is False
    path=f"/api/orders/{order['id']}/lines"
    raised=client.post(path,headers=guest,json={'product_id':made['id'],'quantity':2})
    assert raised.status_code==200
    body=raised.json()
    assert body['lines'][0]['quantity']==2 and body['total_cents']==200
    assert '可改数量 x2'==body['items']
    assert body['physical_door_opened'] is False and body['real_door_enabled'] is False
    assert body['payment_required_to_leave'] is False and body['real_money'] is False
    assert stock_of(client,made['id'])[:2]==(3,2)
    moves_before=stock_of(client,made['id'])[2]
    blocked=client.post(path,headers=guest,json={'product_id':made['id'],'quantity':4})
    assert blocked.status_code==409
    assert '可售库存不足' in blocked.json()['detail']
    still=client.get('/api/orders/'+order['id'],headers=guest).json()
    assert still['lines'][0]['quantity']==2 and still['total_cents']==200
    assert stock_of(client,made['id'])[:3]==(3,2,moves_before)
    assert client.post(path,headers=other,json={'product_id':made['id'],'quantity':1}).status_code==404
    assert stock_of(client,made['id'])[:2]==(3,2)
    down=client.post(path,headers=guest,json={'product_id':made['id'],'quantity':1})
    assert down.status_code==200 and down.json()['total_cents']==100
    assert stock_of(client,made['id'])[:2]==(3,1)
    hidden=client.post('/api/admin/products/'+str(made['id'])+'/listing',headers=admin_header,json={'active':False})
    assert hidden.status_code==200 and hidden.json()['stock']==3
    refused=client.post(path,headers=guest,json={'product_id':made['id'],'quantity':2})
    assert refused.status_code==409 and '下架' in refused.json()['detail']
    assert client.get('/api/orders/'+order['id'],headers=guest).json()['lines'][0]['quantity']==1
    assert stock_of(client,made['id'])[:2]==(3,1)
    emptied=client.post(path,headers=guest,json={'product_id':made['id'],'quantity':0})
    assert emptied.status_code==200
    assert emptied.json()['status']=='CANCELLED' and emptied.json()['cart_empty'] is True
    assert emptied.json()['lines']==[] and emptied.json()['total_cents']==0
    assert stock_of(client,made['id'])[:2]==(3,0)
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    shown=client.post('/api/admin/products/'+str(made['id'])+'/listing',headers=admin_header,json={'active':True})
    assert shown.json()['stock']==3
    guest=visitor(client)
    paid_order=client.post('/api/orders',headers=guest,json={'request_id':'line-qty-paid-01',
        'lines':[{'product_id':made['id'],'quantity':1}]}).json()
    assert client.post('/api/payments/mock-confirm',headers=guest,json={'order_id':paid_order['id']}).json()['real_money'] is False
    locked=client.post(f"/api/orders/{paid_order['id']}/lines",headers=guest,json={'product_id':made['id'],'quantity':2})
    assert locked.status_code==409
    assert stock_of(client,made['id'])[:2]==(2,0)
    doors=stock_of(client,made['id'])[3]
    assert client.post(f"/api/orders/{paid_order['id']}/lines",headers=guest,json={'product_id':made['id'],'quantity':1}).status_code==409
    assert stock_of(client,made['id'])[3]==doors
    assert client.get('/api/admin/overview',headers=admin_header).json()['verified_revenue_cents']==0
    shop=open('web/index.html',encoding='utf-8').read().split('id="panel-admin"',1)[0]
    assert '退款' not in shop
