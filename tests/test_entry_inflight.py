"""A second demo-entry click is ignored only while the first one is still in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from openretail.config import Settings
from openretail.main import create_app
from openretail.security import password_hash


def test_overlapping_demo_entry_starts_one_session(client, admin_header, tmp_path):
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_entry=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/entry')
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
        client.app.state.hold_entry=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['duplicate'] is False and bodies['second']['duplicate'] is True
    assert bodies['first']['virtual_event']=='SESSION_ISSUED'
    assert bodies['second']['guest_token'] is None
    for body in bodies.values():
        assert body['identity_verified'] is False and body['door_authorized'] is False
        assert body['physical_door_opened'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='DEMO_SESSION_CREATE'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SESSION_ISSUED'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_REDEEMED'").fetchone()['n']==0
    later=client.post('/api/entry')
    assert later.status_code==200 and later.json()['duplicate'] is False
    assert later.json()['virtual_event']=='SESSION_ISSUED' and later.json()['physical_door_opened'] is False
    assert later.json()['session_id']!=bodies['first']['session_id']
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']==2
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='DEMO_SESSION_CREATE'").fetchone()['n']==2
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SESSION_ISSUED'").fetchone()['n']==2
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'if(state.entering)return' in script and "$('entry-btn').disabled=true" in script
    assert 'if(s.duplicate)return' in script
    assert '访客会话创建成功（未进行身份核验）' in script
    cfg=Settings(db_path=str(tmp_path/'pilot.sqlite3'),app_mode='pilot',
        admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
        admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
        trusted_proxy_tls=True,public_base_url='https://pilot.example.invalid',mock_payments=False)
    with TestClient(create_app(cfg),base_url='https://pilot.example.invalid') as pilot:
        denied=pilot.post('/api/entry')
        assert denied.status_code==503
        assert denied.json()['detail']=='请向店员领取结账邀请码后再结账。这不是身份核验，也不会开门。'
        with pilot.app.state.db.connect() as conn:
            assert conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']==0
