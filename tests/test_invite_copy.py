"""Copying an invite reads the unused code and does not issue another one."""
from conftest import visitor


def test_invite_copy_uses_the_code_only(client, admin_header):
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    created=client.post('/api/admin/checkout-invite',headers=admin_header)
    assert created.status_code==200
    body=created.json()
    code=body['invite']
    assert body['duplicate'] is False and body['lifetime_seconds']==120
    assert body['identity_verified'] is False and body['door_authorized'] is False
    assert body['physical_door_opened'] is False and body['payment_required_to_leave'] is False
    assert 'identity_verified' not in code and ' ' not in code
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM checkout_invites').fetchone()['n']==1
        audits=conn.execute("SELECT detail FROM audit_events WHERE action='INVITE_CREATED'").fetchall()
        assert [row['detail'] for row in audits]==['lifetime_seconds=120']
        assert code not in audits[0]['detail']
    page=__import__('pathlib').Path('web/index.html').read_text(encoding='utf-8')
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'id="invite-code"' in page and 'id="invite-copy"' in page and '复制邀请码' in page
    assert "$('invite-code').value=r.invite" in script
    copy=script.split("$('invite-copy').onclick")[1].split("$('cancel-order-btn')")[0]
    assert "const code=$('invite-code').value" in copy
    assert 'navigator.clipboard.writeText(code)' in copy
    assert '邀请码已复制' in copy and '邀请码已选中，可手动复制' in copy
    assert "throw Error('还没有邀请码')" in copy
    assert 'checkout-invite' not in copy and 'INVITE_CREATED' not in copy
    assert '结账邀请码' not in copy
    redeemed=client.post('/api/entry/redeem',json={'invite':code})
    assert redeemed.status_code==200
    assert redeemed.json()['identity_verified'] is False and redeemed.json()['door_authorized'] is False
    assert redeemed.json()['physical_door_opened'] is False
    direct=client.post('/api/entry')
    assert direct.status_code==200 and direct.json()['physical_door_opened'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM checkout_invites').fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_CREATED'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_REDEEMED'").fetchone()['n']==1
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
