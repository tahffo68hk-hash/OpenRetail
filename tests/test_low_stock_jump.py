"""A low-stock barcode can be found with the existing product search."""


def test_low_stock_barcode_search_does_not_change_stock(client, admin_header):
    assert client.get('/api/admin/overview').status_code==401
    assert client.get('/api/admin/products?q=6900000083008').status_code==401
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000083008','name':'低库存跳转','price_cents':100,'stock':5,'active':True}).json()
    other=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000083009','name':'不在阈值','price_cents':100,'stock':6,'active':True}).json()
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(made['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    summary=client.get('/api/admin/overview',headers=admin_header).json()
    assert summary['low_stock_threshold']==5
    row=next(item for item in summary['low_stock'] if item['barcode']=='6900000083008')
    assert row['name']=='低库存跳转' and row['stock']==5 and row['reserved_stock']==0 and row['available_stock']==5
    assert all(item['barcode']!='6900000083009' for item in summary['low_stock'])
    found=client.get('/api/admin/products?q='+row['barcode'],headers=admin_header)
    assert found.status_code==200
    match=found.json()
    assert len(match)==1
    assert match[0]['id']==made['id'] and match[0]['barcode']==row['barcode']
    assert match[0]['name']==row['name'] and match[0]['stock']==5 and match[0]['reserved_stock']==0
    assert match[0]['active']==1
    hidden=client.post('/api/admin/products/'+str(made['id'])+'/listing',headers=admin_header,json={'active':False})
    assert hidden.status_code==200 and hidden.json()['stock']==5 and hidden.json()['stock_changed'] is False
    still=client.get('/api/admin/products?q=6900000083008&listing=all',headers=admin_header).json()
    assert len(still)==1 and still[0]['barcode']=='6900000083008' and still[0]['active']==0 and still[0]['stock']==5
    assert all(item['barcode']!='6900000083008' for item in client.get('/api/admin/overview',headers=admin_header).json()['low_stock'])
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(made['id'],)).fetchone()
        # Unlisting is the only stock-neutral write above. Search itself adds no movement.
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(made['id'],)).fetchone()['n']==1
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    assert other['stock']==6
    assert client.get('/api/admin/overview',headers=admin_header).json()['real_door_enabled'] is False
