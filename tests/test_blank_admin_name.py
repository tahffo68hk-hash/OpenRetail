"""A blank admin product name asks for one and does not create or rename a product."""
from conftest import visitor


def test_blank_admin_name_does_not_create_or_rename(client, admin_header):
    guest=visitor(client)
    water=next(item for item in client.get('/api/products').json() if item['barcode']=='6901234567892')
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock,name,price_cents FROM products WHERE id=?',(water['id'],)).fetchone()
        products=conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']
        opening=conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='OPENING_BALANCE'").fetchone()['n']
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        created=conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_CREATED'").fetchone()['n']
        edited_audits=conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_EDIT'").fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        payments=conn.execute('SELECT COUNT(*) n FROM payments').fetchone()['n']
    both=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'   ','name':'   ','price_cents':100,'stock':1,'active':True})
    assert both.status_code==422 and both.json()['detail']=='请输入商品条码'
    for raw in ('', ' ', '   ', '\t', ' \n '):
        denied=client.post('/api/admin/products',headers=admin_header,json={
            'barcode':'6900000077111','name':raw,'price_cents':180,'stock':2,'active':True})
        assert denied.status_code==422 and denied.json()['detail']=='请输入商品名称'
        rename=client.patch('/api/admin/products/'+str(water['id']),headers=admin_header,
                            json={'name':raw,'price_cents':999})
        assert rename.status_code==422 and rename.json()['detail']=='请输入商品名称'
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock,name,price_cents FROM products WHERE id=?',(water['id'],)).fetchone()
        assert tuple(now)==tuple(stock)
        assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==products
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='OPENING_BALANCE'").fetchone()['n']==opening
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_CREATED'").fetchone()['n']==created
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_EDIT'").fetchone()['n']==edited_audits
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
        assert conn.execute('SELECT COUNT(*) n FROM payments').fetchone()['n']==payments
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077111','name':'  空白名称之后的商品  ','price_cents':250,'stock':2,'active':True})
    assert made.status_code==200 and made.json()['name']=='空白名称之后的商品' and made.json()['stock']==2
    duplicate=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077111','name':'重复','price_cents':100,'stock':1,'active':True})
    assert duplicate.status_code==409
    assert duplicate.json()['detail']=='条码已存在。请只改名称售价，或做单品库存调整；不要整表覆盖。'
    edited=client.patch('/api/admin/products/'+str(made.json()['id']),headers=admin_header,
                        json={'name':'  改过的名称  ','price_cents':260})
    assert edited.status_code==200 and edited.json()['name']=='改过的名称'
    assert edited.json()['price_cents']==260 and edited.json()['stock']==2 and edited.json()['stock_changed'] is False
    shop=client.get('/api/products/by-barcode/%20')
    assert shop.status_code==422 and shop.json()['detail']=='请输入商品条码'
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'blankAdminName' in script and "textContent='请输入商品名称'" in script
    assert "blankAdminBarcode(f.get('barcode'));if(!barcode)return;const name=blankAdminName" in script
    assert "showScanError('请输入商品条码')" in script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
