"""List and unlist one SKU without touching stock or deleting history."""
from conftest import visitor


def movements(client, admin_header, product_id):
    rows=client.get('/api/admin/stock-movements?limit=500', headers=admin_header).json()
    return [row for row in rows if row['product_id']==product_id]


def test_unlist_blocks_sale_and_relist_restores_it_without_stock_changes(client, admin_header):
    guest=visitor(client)
    seeded=client.get('/api/products').json()[0]
    assert client.post('/api/orders', headers=guest, json={'request_id':'history-before-unlist',
        'lines':[{'product_id':seeded['id'], 'quantity':1}]}).status_code==201
    created=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000077773', 'name':'可下架', 'price_cents':250, 'stock':8, 'active':True}).json()
    before_moves=len(movements(client, admin_header, created['id']))
    denied=client.post('/api/admin/products/'+str(created['id'])+'/listing', json={'active':False})
    assert denied.status_code==401
    hidden=client.post('/api/admin/products/'+str(created['id'])+'/listing', headers=admin_header, json={'active':False})
    assert hidden.status_code==200
    body=hidden.json()
    assert body['outcome']=='UNLISTED' and body['active'] is False
    assert body['stock']==8 and body['stock_changed'] is False
    assert body['physical_door_opened'] is False and body['real_door_enabled'] is False
    assert len(movements(client, admin_header, created['id']))==before_moves
    assert all(row['barcode']!='6900000077773' for row in client.get('/api/products').json())
    lookup=client.get('/api/products/by-barcode/6900000077773')
    assert lookup.status_code==409 and '已下架' in lookup.json()['detail']
    assert client.post('/api/orders', headers=guest, json={'request_id':'cannot-buy-unlisted',
        'lines':[{'product_id':created['id'], 'quantity':1}]}).status_code==422
    shown=client.post('/api/admin/products/'+str(created['id'])+'/listing', headers=admin_header, json={'active':True})
    assert shown.status_code==200 and shown.json()['active'] is True and shown.json()['stock']==8
    assert client.get('/api/products/by-barcode/6900000077773').status_code==200
    sold=client.post('/api/orders', headers=guest, json={'request_id':'buy-after-relist',
        'lines':[{'product_id':created['id'], 'quantity':1}]})
    assert sold.status_code==201
    again=client.post('/api/admin/products/'+str(seeded['id'])+'/listing', headers=admin_header, json={'active':False})
    assert again.status_code==200 and again.json()['stock']==seeded['stock']
    assert again.json()['reserved_stock']==1
    ledger=client.get('/api/admin/inventory-ledger', headers=admin_header).json()
    assert ledger['balanced'] is True
    row=next(item for item in ledger['products'] if item['barcode']==seeded['barcode'])
    assert row['stock']==row['ledger_stock']==seeded['stock']
