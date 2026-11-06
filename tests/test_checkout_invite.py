"""Staffed checkout invites are one-time and do not authorize a door. Demo entry stays open."""
import time
from openretail.security import digest


def test_invite_is_single_use_and_demo_entry_does_not_need_one(client, admin_header):
    assert client.post('/api/admin/checkout-invite').status_code==401
    created=client.post('/api/admin/checkout-invite',headers=admin_header)
    assert created.status_code==200
    invite=created.json()
    assert invite['lifetime_seconds']==120
    assert abs(invite['expires_at']-time.time()-120)<5
    assert invite['identity_verified'] is False and invite['door_authorized'] is False
    assert invite['physical_door_opened'] is False and invite['payment_required_to_leave'] is False
    assert len(invite['invite'])>=24
    first=client.post('/api/entry/redeem',json={'invite':invite['invite']})
    assert first.status_code==200
    body=first.json()
    assert body['identity_verified'] is False and body['door_authorized'] is False
    assert body['physical_door_opened'] is False and body['payment_required_to_leave'] is False
    assert body['virtual_event']=='CHECKOUT_SESSION'
    assert client.post('/api/entry/redeem',json={'invite':invite['invite']}).status_code==401
    fresh=client.post('/api/admin/checkout-invite',headers=admin_header).json()
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE checkout_invites SET expires_at=0 WHERE invite_hash=?',(digest(fresh['invite']),))
        doors=conn.execute('SELECT COUNT(*) n FROM door_events WHERE result=?',('SESSION_ISSUED',)).fetchone()['n']
    assert client.post('/api/entry/redeem',json={'invite':fresh['invite']}).status_code==401
    direct=client.post('/api/entry')
    assert direct.status_code==200
    assert direct.json()['identity_verified'] is False and direct.json()['physical_door_opened'] is False
    guest={'Authorization':'Bearer '+direct.json()['guest_token']}
    product=client.get('/api/products').json()[0]
    order=client.post('/api/orders',headers=guest,json={'request_id':'demo-without-invite-01',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert order.status_code==201
    assert client.post('/api/payments/mock-confirm',headers=guest,json={'order_id':order.json()['id']}).json()['payment_kind']=='MOCK_NOT_REAL_MONEY'
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM door_events WHERE result=?',('SESSION_ISSUED',)).fetchone()['n']==doors+1
