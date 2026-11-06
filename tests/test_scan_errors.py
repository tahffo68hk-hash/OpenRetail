"""A rejected scan or quantity increase must not move the cart or the reservation."""
from conftest import visitor


def levels(client, product_id):
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        orders=conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']
        lines=conn.execute('SELECT COUNT(*) n FROM order_lines').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    return row['stock'],row['reserved_stock'],orders,lines,doors


def test_unknown_unlisted_and_oversell_leave_stock_alone(client, admin_header):
    guest=visitor(client)
    before=client.get('/api/products').json()
    missing=client.get('/api/products/by-barcode/0000000000000')
    assert missing.status_code==404 and missing.json()['detail']=='未找到条码'
    assert [row['id'] for row in client.get('/api/products').json()]==[row['id'] for row in before]
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000082008','name':'库存边界','price_cents':100,'stock':2,'active':True}).json()
    stock,reserved,orders,lines,doors=levels(client,made['id'])
    assert (stock,reserved)==(2,0)
    too_many=client.post('/api/orders',headers=guest,json={'request_id':'scan-oversell-0001',
        'lines':[{'product_id':made['id'],'quantity':3}]})
    assert too_many.status_code==409 and too_many.json()['detail']=='库存边界 可售库存不足'
    assert levels(client,made['id'])==(2,0,orders,lines,doors)
    created=client.post('/api/orders',headers=guest,json={'request_id':'scan-hold-0002',
        'lines':[{'product_id':made['id'],'quantity':2}]}).json()
    assert created['lines'][0]['quantity']==2
    blocked=client.post(f"/api/orders/{created['id']}/lines",headers=guest,json={'product_id':made['id'],'quantity':3})
    assert blocked.status_code==409 and blocked.json()['detail']=='库存边界 可售库存不足'
    still=client.get('/api/orders/'+created['id'],headers=guest).json()
    assert still['lines'][0]['quantity']==2 and still['total_cents']==200
    assert levels(client,made['id'])[:2]==(2,2)
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    hidden=client.post('/api/admin/products/'+str(made['id'])+'/listing',headers=admin_header,json={'active':False})
    assert hidden.status_code==200 and hidden.json()['stock']==2
    lookup=client.get('/api/products/by-barcode/6900000082008')
    assert lookup.status_code==409 and lookup.json()['detail']=='该商品已下架，暂不销售'
    refused=client.post('/api/orders',headers=guest,json={'request_id':'scan-unlisted-0003',
        'lines':[{'product_id':made['id'],'quantity':1}]})
    assert refused.status_code==422 and '已下架' in refused.json()['detail']
    grown=client.post(f"/api/orders/{created['id']}/lines",headers=guest,json={'product_id':made['id'],'quantity':3})
    assert grown.status_code==409 and '已下架' in grown.json()['detail']
    assert client.get('/api/orders/'+created['id'],headers=guest).json()['lines'][0]['quantity']==2
    assert levels(client,made['id'])[:2]==(2,2)
    assert levels(client,made['id'])[4]==doors
    assert client.get('/api/admin/overview',headers=admin_header).json()['real_door_enabled'] is False
