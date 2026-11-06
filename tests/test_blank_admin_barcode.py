"""A blank admin barcode asks for one and does not create or change a product."""
from urllib.parse import quote
from conftest import visitor


def test_blank_admin_barcode_does_not_change_a_product(client, admin_header):
    guest=visitor(client)
    water=next(item for item in client.get('/api/products').json() if item['barcode']=='6901234567892')
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock,name,price_cents FROM products WHERE id=?',(water['id'],)).fetchone()
        products=conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']
        opening=conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='OPENING_BALANCE'").fetchone()['n']
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        created=conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_CREATED'").fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        payments=conn.execute('SELECT COUNT(*) n FROM payments').fetchone()['n']
    body={'name':'不应写入','price_cents':100,'stock':3,'active':True}
    for raw in ('', ' ', '   ', '\t', ' \n '):
        denied=client.post('/api/admin/products',headers=admin_header,json={**body,'barcode':raw})
        assert denied.status_code==422 and denied.json()['detail']=='请输入商品条码'
        lookup=client.get('/api/admin/products/by-barcode/'+quote(raw,safe=''),headers=admin_header)
        assert lookup.status_code==422 and lookup.json()['detail']=='请输入商品条码'
    missing=client.get('/api/admin/products/by-barcode/',headers=admin_header)
    assert missing.status_code==422 and missing.json()['detail']=='请输入商品条码'
    shop=client.get('/api/products/by-barcode/'+quote(' ',safe=''))
    assert shop.status_code==422 and shop.json()['detail']=='请输入商品条码'
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock,name,price_cents FROM products WHERE id=?',(water['id'],)).fetchone()
        assert tuple(now)==tuple(stock)
        assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==products
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='OPENING_BALANCE'").fetchone()['n']==opening
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_CREATED'").fetchone()['n']==created
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
        assert conn.execute('SELECT COUNT(*) n FROM payments').fetchone()['n']==payments
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':' 6900000077001 ','name':'空白条码之后的商品','price_cents':250,'stock':2,'active':True})
    assert made.status_code==200 and made.json()['barcode']=='6900000077001' and made.json()['stock']==2
    duplicate=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077001','name':'重复','price_cents':100,'stock':1,'active':True})
    assert duplicate.status_code==409
    assert duplicate.json()['detail']=='条码已存在。请只改名称售价，或做单品库存调整；不要整表覆盖。'
    found=client.get('/api/admin/products/by-barcode/6900000077001',headers=admin_header)
    assert found.status_code==200 and found.json()['id']==made.json()['id']
    edited=client.patch('/api/admin/products/'+str(made.json()['id']),headers=admin_header,
                        json={'name':'改过的名称','price_cents':260})
    assert edited.status_code==200 and edited.json()['name']=='改过的名称'
    assert edited.json()['stock']==2 and edited.json()['stock_changed'] is False
    adjusted=client.post('/api/admin/products/'+str(made.json()['id'])+'/adjust-stock',headers=admin_header,
                         json={'quantity_delta':1,'reason':'到货入库'})
    assert adjusted.status_code==200 and adjusted.json()['stock']==3
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'blankAdminBarcode' in script and "textContent='请输入商品条码'" in script
    assert "showScanError('请输入商品条码')" in script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
