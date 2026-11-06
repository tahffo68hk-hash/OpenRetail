"""A blank or one-character help note asks for a sentence and stores nothing."""
from conftest import visitor


def test_short_help_does_not_create_a_request(client, admin_header):
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    for message in ('', ' ', '   ', '\n\t', 'a', ' 好 '):
        rejected=client.post('/api/help',json={'message':message})
        assert rejected.status_code==422 and rejected.json()['detail']=='请写一句需要店员协助的话'
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM help_requests').fetchone()['n']==0
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_REQUEST'").fetchone()['n']==0
    created=client.post('/api/help',json={'message':' 请到货架帮忙 '})
    assert created.status_code==201
    body=created.json()
    assert body['physical_door_opened'] is False and body['door_authorized'] is False
    assert body['payment_required_to_leave'] is False
    listed=client.get('/api/admin/help-requests',headers=admin_header).json()['requests']
    assert len(listed)==1 and listed[0]['status']=='OPEN' and listed[0]['message']=='请到货架帮忙'
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_REQUEST'").fetchone()['n']==1
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert "请写一句需要店员协助的话" in script and 'message.length<2' in script
    assert 'armBarcodeField' not in script.split("message.length<2")[1].split('已通知店员')[0]
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
