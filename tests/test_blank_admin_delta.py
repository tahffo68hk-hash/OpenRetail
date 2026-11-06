"""An empty or zero stock adjustment asks for a real quantity and does not move stock."""
from conftest import visitor


def test_invalid_adjust_quantity_does_not_move_stock(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    water=next(item for item in client.get('/api/products').json() if item['barcode']=='6901234567892')
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(water['id'],)).fetchone()
        adjusts=conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST'").fetchone()['n']
        manuals=conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reference='MANUAL'").fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    for raw in (0, None, '', 'abc', '  ', 1.5, True):
        denied=client.post('/api/admin/products/'+str(water['id'])+'/adjust-stock',headers=admin_header,
                           json={'quantity_delta':raw,'reason':'盘点修正'})
        assert denied.status_code==422 and denied.json()['detail']=='调整数量不能为 0'
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(water['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST'").fetchone()['n']==adjusts
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reference='MANUAL'").fetchone()['n']==manuals
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    up=client.post('/api/admin/products/'+str(water['id'])+'/adjust-stock',headers=admin_header,
                   json={'quantity_delta':1,'reason':'到货入库'})
    assert up.status_code==200 and up.json()['stock']==stock['stock']+1
    assert up.json()['physical_door_opened'] is False and up.json()['identity_verified'] is False
    assert up.json()['door_authorized'] is False
    down=client.post('/api/admin/products/'+str(water['id'])+'/adjust-stock',headers=admin_header,
                     json={'quantity_delta':-1,'reason':'商品报损'})
    assert down.status_code==200 and down.json()['stock']==stock['stock']
    assert down.json()['reserved_stock']==stock['reserved_stock']
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST' AND detail LIKE ?",
                            (water['barcode']+':%',)).fetchone()['n']==2
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reference='MANUAL' AND product_id=?",
                            (water['id'],)).fetchone()['n']==2
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077333','name':'可调边界','price_cents':100,'stock':3,'active':True}).json()
    guest=visitor(client)
    assert client.post('/api/orders',headers=guest,json={'request_id':'adjust-floor-0001',
        'lines':[{'product_id':made['id'],'quantity':2}]}).status_code==201
    too_low=client.post('/api/admin/products/'+str(made['id'])+'/adjust-stock',headers=admin_header,
                        json={'quantity_delta':-2,'reason':'商品报损'})
    assert too_low.status_code==409
    assert too_low.json()['detail']=='库存调整会低于可售底线或侵占未结算预留'
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(made['id'],)).fetchone()
        assert row['stock']==3 and row['reserved_stock']==2
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    adjust=script.split("$('adjust-form').onsubmit")[1].split('async function uploadCsv')[0]
    assert adjust.index('blankAdminBarcode')<adjust.index('adminStockDelta')
    assert "textContent='调整数量不能为 0'" in script
    assert "textContent='请输入商品条码'" in script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
