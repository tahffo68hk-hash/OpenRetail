"""A second redeem is ignored only while the first one is still in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from openretail.security import digest


def test_overlapping_redeem_starts_one_session(client, admin_header):
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    created=client.post('/api/admin/checkout-invite',headers=admin_header).json()
    code=created['invite']
    assert created['identity_verified'] is False and created['physical_door_opened'] is False
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_redeem=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/entry/redeem',json={'invite':code})
                results.append((tag,response.status_code,response.json()))
            async def second():
                for _ in range(100):
                    if entered.is_set():break
                    await anyio.sleep(0.01)
                assert entered.is_set()
                await post('second')
                release.set()
            async with anyio.create_task_group() as tg:
                tg.start_soon(post,'first')
                tg.start_soon(second)
    try:
        anyio.run(overlap)
    finally:
        client.app.state.hold_redeem=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['duplicate'] is False and bodies['second']['duplicate'] is True
    assert bodies['second'].get('detail')!='邀请码已使用'
    assert '邀请码已使用' not in str(bodies['second'])
    for body in bodies.values():
        assert body['identity_verified'] is False and body['door_authorized'] is False
        assert body['physical_door_opened'] is False and body['payment_required_to_leave'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']==1
        audits=conn.execute("SELECT detail FROM audit_events WHERE action='INVITE_REDEEMED'").fetchall()
        assert len(audits)==1
        assert audits[0]['detail'].startswith('session=')
        assert 'identity_verified=false;door_authorized=false' in audits[0]['detail']
        assert code not in audits[0]['detail']
    used=client.post('/api/entry/redeem',json={'invite':code})
    assert used.status_code==401 and used.json()['detail']=='邀请码已使用'
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_REDEEMED'").fetchone()['n']==1
    fresh=client.post('/api/admin/checkout-invite',headers=admin_header).json()
    with client.app.state.db.tx() as conn:
        conn.execute('UPDATE checkout_invites SET expires_at=0 WHERE invite_hash=?',(digest(fresh['invite']),))
    expired=client.post('/api/entry/redeem',json={'invite':fresh['invite']})
    assert expired.status_code==401 and expired.json()['detail']=='邀请码已过期'
    direct=client.post('/api/entry')
    assert direct.status_code==200 and direct.json()['physical_door_opened'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_REDEEMED'").fetchone()['n']==1
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'if(state.redeeming)return' in script and "$('redeem-btn').disabled=true" in script
    assert '已领取员工发放的结账会话；不会打开门禁' in script
    assert '请填写店员发给的结账邀请码。这不是身份核验，也不会开门。' in script
