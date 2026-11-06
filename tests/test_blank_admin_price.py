"""An invalid admin price asks for a real one and does not create or rename a product."""
from conftest import visitor


def test_invalid_admin_price_does_not_create_or_rename(client, admin_header):
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
    barcode_first=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'   ','name':'   ','price_cents':0,'stock':1,'active':True})
    assert barcode_first.status_code==422 and barcode_first.json()['detail']=='请输入商品条码'
    name_first=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077222','name':'  ','price_cents':0,'stock':1,'active':True})
    assert name_first.status_code==422 and name_first.json()['detail']=='请输入商品名称'
    for raw in (0, -5, None, '', 'abc', ' -1 ', 1.5):
        denied=client.post('/api/admin/products',headers=admin_header,json={
            'barcode':'6900000077222','name':'不应写入','price_cents':raw,'stock':2,'active':True})
        assert denied.status_code==422 and denied.json()['detail']=='请输入有效售价'
        rename=client.patch('/api/admin/products/'+str(water['id']),headers=admin_header,
                            json={'name':'不应改名','price_cents':raw})
        assert rename.status_code==422 and rename.json()['detail']=='请输入有效售价'
    too_high=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077222','name':'不应写入','price_cents':100_000_001,'stock':1,'active':True})
    assert too_high.status_code==422 and too_high.json()['detail']!='请输入有效售价'
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
        'barcode':'6900000077222','name':'有效售价商品','price_cents':200,'stock':2,'active':True})
    assert made.status_code==200 and made.json()['price_cents']==200 and made.json()['stock']==2
    duplicate=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077222','name':'重复','price_cents':200,'stock':1,'active':True})
    assert duplicate.status_code==409
    assert duplicate.json()['detail']=='条码已存在。请只改名称售价，或做单品库存调整；不要整表覆盖。'
    edited=client.patch('/api/admin/products/'+str(made.json()['id']),headers=admin_header,
                        json={'name':'改过的名称','price_cents':'260'})
    assert edited.status_code==200 and edited.json()['name']=='改过的名称' and edited.json()['price_cents']==260
    assert edited.json()['stock']==2 and edited.json()['stock_changed'] is False
    shop=client.get('/api/products/by-barcode/%20')
    assert shop.status_code==422 and shop.json()['detail']=='请输入商品条码'
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'adminPriceCents' in script and "textContent='请输入有效售价'" in script
    assert "blankAdminName(f.get('name'));if(!name)return;const priceCents=adminPriceCents" in script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
