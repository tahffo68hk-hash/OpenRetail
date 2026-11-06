"""A second simulated-door click is ignored only while the first one is still in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from openretail.config import Settings
from openretail.main import create_app
from openretail.security import password_hash
from conftest import visitor


def test_overlapping_simulated_door_writes_one_event(client, admin_header, tmp_path):
    assert client.get('/api/admin/overview',headers=admin_header).json()['mode']=='STAFFED'
    unlocks=[]
    def refuse_unlock(*_args, **_kwargs):
        unlocks.append('unlock')
        raise AssertionError('physical unlock was called')
    client.app.state.ha.unlock=refuse_unlock
    auth=visitor(client)
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    staffed=client.post('/api/door/open',headers=auth)
    assert staffed.status_code==409 and staffed.json()['detail']=='当前非无人值守演示模式'
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SIMULATED'").fetchone()['n']==0
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='DEMO_ENTRY_OPEN'").fetchone()['n']==0
    assert client.put('/api/admin/mode',headers=admin_header,json={'mode':'UNATTENDED'}).status_code==200
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_door=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/door/open',headers=auth)
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
        client.app.state.hold_door=None
        release.set()
        assert client.put('/api/admin/mode',headers=admin_header,json={'mode':'STAFFED'}).status_code==200
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['duplicate'] is False and bodies['first']['result']=='SIMULATED'
    assert bodies['second']['duplicate'] is True and bodies['second']['result'] is None
    for body in bodies.values():
        assert body['physical_door_opened'] is False and body['identity_verified'] is False
        assert body['door_authorized'] is False
    assert 'NO PHYSICAL UNLOCK' in {row['detail'] for row in bodies['first']['events']}
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SIMULATED' AND detail='NO PHYSICAL UNLOCK'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='DEMO_ENTRY_OPEN'").fetchone()['n']==1
    assert client.put('/api/admin/mode',headers=admin_header,json={'mode':'UNATTENDED'}).status_code==200
    later=client.post('/api/door/open',headers=auth)
    assert later.status_code==200 and later.json()['duplicate'] is False and later.json()['result']=='SIMULATED'
    assert later.json()['physical_door_opened'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SIMULATED'").fetchone()['n']==2
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='DEMO_ENTRY_OPEN'").fetchone()['n']==2
    assert client.put('/api/admin/mode',headers=admin_header,json={'mode':'STAFFED'}).status_code==200
    again=client.post('/api/door/open',headers=auth)
    assert again.status_code==409 and again.json()['detail']=='当前非无人值守演示模式'
    assert client.get('/api/admin/overview',headers=admin_header).json()['mode']=='STAFFED'
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SIMULATED'").fetchone()['n']==2
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    assert unlocks==[]
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'if(state.opening)return' in script and "$('door-btn').disabled=true" in script
    assert 'if(r.duplicate)return' in script
    assert '开门结果：' in script and '实际门锁未动作。' in script and '仅模拟开门成功' in script
    source=__import__('pathlib').Path('openretail/main.py').read_text(encoding='utf-8')
    assert "abort(503,'无已验证访客身份与现场门禁验收，禁止控制实物门锁')" in source
    assert 'lock.unlock' not in source and 'lock.open' not in source
    cfg=Settings(db_path=str(tmp_path/'pilot.sqlite3'),app_mode='pilot',
        admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
        admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
        trusted_proxy_tls=True,public_base_url='https://pilot.example.invalid',mock_payments=False)
    with TestClient(create_app(cfg),base_url='https://pilot.example.invalid') as pilot:
        login=pilot.post('/api/admin/login',json={'password':'StrongOperatorPassphrase2026'})
        csrf={'X-CSRF-Token':login.json()['csrf']}
        invite=pilot.post('/api/admin/checkout-invite',headers=csrf).json()
        guest=pilot.post('/api/entry/redeem',json={'invite':invite['invite']})
        denied=pilot.post('/api/door/open',headers={'Authorization':'Bearer '+guest.json()['guest_token']})
        assert denied.status_code==503
        assert denied.json()['detail']=='无已验证访客身份与现场门禁验收，禁止控制实物门锁'
        with pilot.app.state.db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SIMULATED'").fetchone()['n']==0
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=auth).status_code==404
