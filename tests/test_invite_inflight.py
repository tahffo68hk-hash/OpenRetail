"""A second invite create is ignored only while the first one is still in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_invite_creates_one_code(client, admin_header):
    assert client.post('/api/admin/checkout-invite').status_code==401
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_invite=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/admin/checkout-invite',headers=admin_header)
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
        client.app.state.hold_invite=None
        release.set()
    assert len(results)==2
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['duplicate'] is False and bodies['second']['duplicate'] is True
    assert bodies['second']['invite'] is None
    code=bodies['first']['invite']
    assert code and len(code)>=24
    for body in bodies.values():
        assert body['identity_verified'] is False and body['door_authorized'] is False
        assert body['physical_door_opened'] is False and body['payment_required_to_leave'] is False
        assert body['lifetime_seconds']==120
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM checkout_invites').fetchone()['n']==1
        audits=conn.execute("SELECT detail FROM audit_events WHERE action='INVITE_CREATED'").fetchall()
        assert [row['detail'] for row in audits]==['lifetime_seconds=120']
        assert code not in audits[0]['detail']
    redeemed=client.post('/api/entry/redeem',json={'invite':code})
    assert redeemed.status_code==200
    assert redeemed.json()['identity_verified'] is False and redeemed.json()['door_authorized'] is False
    assert redeemed.json()['physical_door_opened'] is False
    later=client.post('/api/admin/checkout-invite',headers=admin_header)
    assert later.status_code==200 and later.json()['duplicate'] is False
    assert later.json()['invite']!=code
    assert later.json()['physical_door_opened'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM checkout_invites').fetchone()['n']==2
        audits=conn.execute("SELECT detail FROM audit_events WHERE action='INVITE_CREATED'").fetchall()
        assert len(audits)==2 and all(row['detail']=='lifetime_seconds=120' for row in audits)
        assert all(later.json()['invite'] not in row['detail'] for row in audits)
    direct=client.post('/api/entry')
    assert direct.status_code==200 and direct.json()['identity_verified'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_REDEEMED'").fetchone()['n']==1
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SIMULATED'").fetchone()['n']==0
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'state.issuing' in script and "$('issue-invite').disabled=true" in script
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
