"""Audit list can be narrowed to one action without writing anything."""
from conftest import visitor


def test_audit_action_filter_is_read_only(client, admin_header):
    assert client.get('/api/admin/audit').status_code==401
    assert client.get('/api/admin/audit?action=INVITE_CREATED').status_code==401
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    created=client.post('/api/admin/checkout-invite',headers=admin_header).json()
    redeemed=client.post('/api/entry/redeem',json={'invite':created['invite']})
    assert redeemed.status_code==200
    assert redeemed.json()['identity_verified'] is False and redeemed.json()['physical_door_opened'] is False
    invites=client.get('/api/admin/audit?action=INVITE_CREATED',headers=admin_header)
    assert invites.status_code==200
    body=invites.json()
    assert body['append_only'] is True and body['action']=='INVITE_CREATED'
    assert body['physical_door_opened'] is False and body['payment_required_to_leave'] is False
    assert body['events'] and all(row['action']=='INVITE_CREATED' for row in body['events'])
    assert all(row['detail']=='lifetime_seconds=120' for row in body['events'])
    assert all(created['invite'] not in row['detail'] for row in body['events'])
    redeemed_rows=client.get('/api/admin/audit?action=INVITE_REDEEMED',headers=admin_header).json()['events']
    assert redeemed_rows and all(row['action']=='INVITE_REDEEMED' for row in redeemed_rows)
    assert all(created['invite'] not in row['detail'] for row in redeemed_rows)
    assert any('identity_verified=false' in row['detail'] and 'door_authorized=false' in row['detail'] for row in redeemed_rows)
    assert all(row['action']!='INVITE_REDEEMED' for row in body['events'])
    both=client.get('/api/admin/audit',headers=admin_header).json()
    assert both['action']==''
    actions={row['action'] for row in both['events']}
    assert 'INVITE_CREATED' in actions and 'INVITE_REDEEMED' in actions
    empty=client.get('/api/admin/audit?action=NO_SUCH_ACTION',headers=admin_header)
    assert empty.status_code==200 and empty.json()['events']==[] and empty.json()['append_only'] is True
    assert client.get('/api/admin/audit?action=',headers=admin_header).json()['action']==''
    assert client.delete('/api/admin/audit/1',headers=admin_header).status_code==404
    direct=client.post('/api/entry')
    assert direct.status_code==200
    after_guest={row['action'] for row in client.get('/api/admin/audit?action=INVITE_REDEEMED',headers=admin_header).json()['events']}
    assert after_guest=={'INVITE_REDEEMED'}
    assert len(client.get('/api/admin/audit?action=INVITE_REDEEMED',headers=admin_header).json()['events'])==len(redeemed_rows)
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=visitor(client)).status_code==404
