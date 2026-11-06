"""Help list filter matches the unfinished count and does not change the notes."""
from conftest import visitor


def test_help_attention_filter_is_read_only(client, admin_header):
    assert client.get('/api/admin/help-requests').status_code==401
    assert client.get('/api/admin/help-requests?status=attention').status_code==401
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    open_help=client.post('/api/help',json={'message':'还没人看'}).json()
    seen=client.post('/api/help',json={'message':'已经看到'}).json()
    done=client.post('/api/help',json={'message':'已经处理好'}).json()
    assert client.post(f"/api/admin/help-requests/{seen['id']}/status",headers=admin_header,
                       json={'status':'ACKNOWLEDGED'}).json()['physical_door_opened'] is False
    resolved=client.post(f"/api/admin/help-requests/{done['id']}/status",headers=admin_header,
                         json={'status':'RESOLVED'})
    assert resolved.status_code==200
    assert resolved.json()['physical_door_opened'] is False
    assert resolved.json()['door_authorized'] is False and resolved.json()['payment_required_to_leave'] is False
    mixed=client.get('/api/admin/help-requests',headers=admin_header).json()
    assert mixed['status']=='' and mixed['physical_door_opened'] is False
    statuses={row['id']:row['status'] for row in mixed['requests']}
    assert statuses[open_help['id']]=='OPEN'
    assert statuses[seen['id']]=='ACKNOWLEDGED'
    assert statuses[done['id']]=='RESOLVED'
    attention=client.get('/api/admin/help-requests?status=attention',headers=admin_header).json()
    assert attention['status']=='attention'
    attention_ids={row['id'] for row in attention['requests']}
    assert open_help['id'] in attention_ids and seen['id'] in attention_ids and done['id'] not in attention_ids
    assert all(row['status'] in ('OPEN','ACKNOWLEDGED') for row in attention['requests'])
    only_done=client.get('/api/admin/help-requests?status=RESOLVED',headers=admin_header).json()['requests']
    assert done['id'] in {row['id'] for row in only_done}
    assert all(row['status']=='RESOLVED' for row in only_done)
    again=client.get('/api/admin/help-requests',headers=admin_header).json()
    again_status={row['id']:row['status'] for row in again['requests']}
    assert again_status[open_help['id']]=='OPEN'
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    page=__import__('pathlib').Path('web/index.html').read_text(encoding='utf-8')
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'id="jump-help"' in page and '查看待处理求助' in page and '没有求助' in page
    assert '没有求助' in script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
