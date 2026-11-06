"""Single-product catalog maintenance after orders exist. SQLite remains the only stock authority."""
from conftest import visitor


def ledger(client, admin_header):
    body=client.get('/api/admin/inventory-ledger', headers=admin_header).json()
    assert body['system_of_record']=='sqlite' and body['balanced'] is True
    return body


def test_add_edit_and_adjust_after_an_order_exists(client, admin_header):
    guest=visitor(client)
    seeded=client.get('/api/products').json()[0]
    assert client.post('/api/orders', headers=guest, json={'request_id':'single-sku-after-order',
        'lines':[{'product_id':seeded['id'], 'quantity':1}]}).status_code==201
    blocked=client.post('/api/admin/import-products?dry_run=false', headers=admin_header,
                        files={'file':('x.csv', 'barcode,name,price,stock\nNEW1,Nope,1.00,3\n', 'text/csv')})
    assert blocked.status_code==409

    created=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000099991', 'name':'新商品', 'price_cents':350, 'stock':4, 'active':True})
    assert created.status_code==200
    body=created.json()
    assert body['created'] is True and body['stock']==4 and body['system_of_record']=='sqlite'
    duplicate=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000099991', 'name':'重复', 'price_cents':100, 'stock':9, 'active':True})
    assert duplicate.status_code==409
    assert client.get('/api/admin/products', headers=admin_header)
    moves=client.get('/api/admin/stock-movements', headers=admin_header).json()
    assert any(row['reason']=='OPENING_BALANCE' and row['reference']=='6900000099991' and row['stock_delta']==4
               for row in moves)

    before=next(row for row in ledger(client, admin_header)['products'] if row['barcode']=='6900000099991')
    edited=client.patch('/api/admin/products/'+str(body['id']), headers=admin_header,
                        json={'name':'新商品改名', 'price_cents':420})
    assert edited.status_code==200
    assert edited.json()['stock']==4 and edited.json()['stock_changed'] is False
    assert edited.json()['price_cents']==420 and edited.json()['name']=='新商品改名'
    after=next(row for row in ledger(client, admin_header)['products'] if row['barcode']=='6900000099991')
    assert after['stock']==before['stock']==4
    assert after['ledger_stock']==before['ledger_stock']

    adjusted=client.post('/api/admin/products/'+str(body['id'])+'/adjust-stock', headers=admin_header,
                         json={'quantity_delta':2, 'reason':'到货入库'})
    assert adjusted.status_code==200 and adjusted.json()['stock']==6
    balanced=ledger(client, admin_header)
    row=next(item for item in balanced['products'] if item['barcode']=='6900000099991')
    assert row['stock']==row['ledger_stock']==6
    assert any(item['reason']=='到货入库' and item['stock_delta']==2 for item in balanced['movements'])


def test_unsafe_stock_decrease_is_rejected(client, admin_header):
    created=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000088882', 'name':'可调商品', 'price_cents':200, 'stock':5, 'active':True}).json()
    guest=visitor(client)
    assert client.post('/api/orders', headers=guest, json={'request_id':'reserve-before-adjust',
        'lines':[{'product_id':created['id'], 'quantity':2}]}).status_code==201
    too_low=client.post('/api/admin/products/'+str(created['id'])+'/adjust-stock', headers=admin_header,
                        json={'quantity_delta':-4, 'reason':'商品报损'})
    assert too_low.status_code==409
    negative=client.post('/api/admin/products/'+str(created['id'])+'/adjust-stock', headers=admin_header,
                         json={'quantity_delta':-9, 'reason':'盘点修正'})
    assert negative.status_code==409
    assert client.post('/api/admin/products/'+str(created['id'])+'/adjust-stock', headers=admin_header,
                       json={'quantity_delta':0, 'reason':'盘点修正'}).status_code==422
    current=next(row for row in client.get('/api/products').json() if row['barcode']=='6900000088882')
    assert current['stock']==5 and current['reserved_stock']==2
    ledger_row=next(row for row in ledger(client, admin_header)['products'] if row['barcode']=='6900000088882')
    assert ledger_row['stock']==ledger_row['ledger_stock']==5
