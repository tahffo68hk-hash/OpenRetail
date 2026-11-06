"""Admin catalog search and filters stay read-only and use the store low-stock threshold."""


def barcodes(rows):
    return {row['barcode'] for row in rows}


def test_search_and_filters_do_not_change_stock(client, admin_header):
    assert client.get('/api/admin/products?q=水').status_code==401
    assert client.get('/api/admin/products?listing=unlisted').status_code==401
    assert client.get('/api/admin/products?low_stock=1').status_code==401
    low=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000070007', 'name':'筛选低库存', 'price_cents':100, 'stock':5, 'active':True}).json()
    high=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000070008', 'name':'筛选充足', 'price_cents':100, 'stock':6, 'active':True}).json()
    hidden=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000070009', 'name':'筛选下架', 'price_cents':100, 'stock':5, 'active':True}).json()
    assert client.post('/api/admin/products/'+str(hidden['id'])+'/listing', headers=admin_header,
                       json={'active':False}).json()['stock']==5
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']
        reserved=conn.execute('SELECT COALESCE(SUM(reserved_stock),0) n FROM products').fetchone()['n']
        movements=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    by_name=client.get('/api/admin/products?q=筛选低库存', headers=admin_header)
    assert by_name.status_code==200
    assert barcodes(by_name.json())=={'6900000070007'}
    by_code=client.get('/api/admin/products?q=70008', headers=admin_header).json()
    assert barcodes(by_code)=={'6900000070008'}
    assert barcodes(client.get('/api/admin/products?q=%', headers=admin_header).json())==set()
    everything=barcodes(client.get('/api/admin/products', headers=admin_header).json())
    assert {'6900000070007','6900000070008','6900000070009','6901234567892'}<=everything
    listed=barcodes(client.get('/api/admin/products?listing=listed', headers=admin_header).json())
    unlisted=barcodes(client.get('/api/admin/products?listing=unlisted', headers=admin_header).json())
    assert '6900000070007' in listed and '6900000070008' in listed and '6900000070009' not in listed
    assert unlisted=={'6900000070009'}
    low_only=barcodes(client.get('/api/admin/products?low_stock=1', headers=admin_header).json())
    assert '6900000070007' in low_only and '6900000070009' in low_only and '6900000070008' not in low_only
    combined=barcodes(client.get('/api/admin/products?q=筛选&listing=unlisted', headers=admin_header).json())
    assert combined=={'6900000070009'}
    named_low=barcodes(client.get('/api/admin/products?q=筛选&low_stock=1', headers=admin_header).json())
    assert named_low=={'6900000070007','6900000070009'}
    assert client.get('/api/admin/products?q=筛选充足&low_stock=1', headers=admin_header).json()==[]
    assert client.get('/api/admin/products?listing=nope', headers=admin_header).status_code==422
    overview=client.get('/api/admin/overview', headers=admin_header).json()
    assert overview['low_stock_threshold']==5
    assert '6900000070007' in {row['barcode'] for row in overview['low_stock']}
    assert '6900000070008' not in {row['barcode'] for row in overview['low_stock']}
    assert overview['real_door_enabled'] is False and overview['today_verified_revenue_cents']==0
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']==stock
        assert conn.execute('SELECT COALESCE(SUM(reserved_stock),0) n FROM products').fetchone()['n']==reserved
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==movements
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
        assert conn.execute('SELECT stock,active FROM products WHERE id=?',(low['id'],)).fetchone()['stock']==5
        assert conn.execute('SELECT active FROM products WHERE id=?',(hidden['id'],)).fetchone()['active']==0
