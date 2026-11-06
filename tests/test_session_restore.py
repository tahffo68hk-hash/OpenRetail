"""Reloading the same guest session returns the open order or receipt, not a new one."""
from conftest import visitor


def counts(client, product_id):
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        orders=conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    return row['stock'],row['reserved_stock'],orders,doors


def test_reload_returns_the_same_order_without_moving_stock(client):
    assert client.get('/api/orders').status_code==401
    guest=visitor(client)
    other=visitor(client)
    product=client.get('/api/products').json()[0]
    created=client.post('/api/orders',headers=guest,json={'request_id':'reload-unpaid-0001',
        'lines':[{'product_id':product['id'],'quantity':1}]}).json()
    assert created['status']=='PENDING' and created['real_money'] is False
    assert created['expires_at']==created['created_at']+900
    assert created['expires_local'] and created['expires_timezone']=='Asia/Shanghai'
    before=counts(client,product['id'])
    again=client.get('/api/orders',headers=guest).json()
    assert len(again)==1 and again[0]['id']==created['id']
    assert again[0]['lines'][0]['quantity']==1 and again[0]['total_cents']==created['total_cents']
    assert again[0]['expires_at']==created['expires_at'] and again[0]['expires_local']==created['expires_local']
    assert again[0]['payment_kind']=='UNPAID' and again[0]['real_money'] is False
    assert counts(client,product['id'])==before
    assert client.get('/api/orders',headers=other).json()==[]
    assert client.get('/api/orders/'+created['id']).status_code==401
    assert client.get('/api/orders/'+created['id'],headers=other).status_code==404
    paid=client.post('/api/payments/mock-confirm',headers=guest,json={'order_id':created['id']}).json()
    assert paid['id']==created['id'] and paid['payment_kind']=='MOCK_NOT_REAL_MONEY'
    assert paid['real_money'] is False and paid['verified']==0
    after_pay=counts(client,product['id'])
    assert after_pay[0]==before[0]-1 and after_pay[1]==0 and after_pay[2]==before[2]
    receipt=client.get('/api/orders',headers=guest).json()
    assert len(receipt)==1 and receipt[0]['id']==created['id'] and receipt[0]['status']=='PAID'
    assert receipt[0]['payment_kind']=='MOCK_NOT_REAL_MONEY' and receipt[0]['real_money'] is False
    assert counts(client,product['id'])==after_pay
    assert client.get('/api/orders',headers=other).json()==[]
