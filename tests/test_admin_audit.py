"""Privileged admin actions append a read-only audit row and do not open a door."""
from conftest import visitor


def test_unlist_appends_audit_without_changing_stock(client, admin_header):
    assert client.get('/api/admin/audit').status_code==401
    guest=visitor(client)
    seeded=client.get('/api/products').json()[0]
    assert client.post('/api/orders', headers=guest, json={'request_id':'audit-after-order',
        'lines':[{'product_id':seeded['id'], 'quantity':1}]}).status_code==201
    created=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000044444', 'name':'待审计', 'price_cents':300, 'stock':9, 'active':True}).json()
    hidden=client.post('/api/admin/products/'+str(created['id'])+'/listing', headers=admin_header, json={'active':False})
    assert hidden.status_code==200 and hidden.json()['stock']==9 and hidden.json()['stock_changed'] is False
    adjusted=client.post('/api/admin/products/'+str(created['id'])+'/adjust-stock', headers=admin_header,
                         json={'quantity_delta':1, 'reason':'到货入库'})
    assert adjusted.status_code==200 and adjusted.json()['stock']==10
    log=client.get('/api/admin/audit', headers=admin_header).json()
    assert log['append_only'] is True
    assert log['physical_door_opened'] is False and log['payment_required_to_leave'] is False
    actions={(row['action'], row['detail'], row['actor']) for row in log['events']}
    assert ('PRODUCT_CREATED','6900000044444','demo-admin-key') in actions
    assert ('PRODUCT_UNLISTED','6900000044444','demo-admin-key') in actions
    assert ('STOCK_ADJUST','6900000044444:1','demo-admin-key') in actions
    assert all(row['created_at'] for row in log['events'])
    assert client.delete('/api/admin/audit/1', headers=admin_header).status_code==404
    again=client.get('/api/admin/audit', headers=admin_header).json()
    assert ('PRODUCT_UNLISTED','6900000044444','demo-admin-key') in {(row['action'], row['detail'], row['actor']) for row in again['events']}
