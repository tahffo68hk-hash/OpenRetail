"""A second help-status click is ignored while the first is in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_help_status_writes_one_audit(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    created=client.post('/api/help',json={'message':'请帮忙看一下货架'})
    assert created.status_code==201
    request_id=created.json()['id']
    with client.app.state.db.connect() as conn:
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        stock=conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_help_status=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag,status):
                response=await http.post('/api/admin/help-requests/'+str(request_id)+'/status',headers=admin_header,
                                         json={'status':status})
                results.append((tag,response.status_code,response.json()))
            async def second():
                for _ in range(100):
                    if entered.is_set():break
                    await anyio.sleep(0.01)
                assert entered.is_set()
                await post('second','ACKNOWLEDGED')
                release.set()
            async with anyio.create_task_group() as tg:
                tg.start_soon(post,'first','ACKNOWLEDGED')
                tg.start_soon(second)
    try:
        anyio.run(overlap)
    finally:
        client.app.state.hold_help_status=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['applied'] is True and bodies['first']['duplicate'] is False
    assert bodies['first']['outcome']=='ACKNOWLEDGED' and bodies['first']['status']=='ACKNOWLEDGED'
    assert bodies['second']['applied'] is False and bodies['second']['duplicate'] is True
    assert bodies['second']['status']=='OPEN'
    for body in bodies.values():
        assert body['physical_door_opened'] is False and body['door_authorized'] is False
        assert body['identity_verified'] is False and body['payment_required_to_leave'] is False
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT status FROM help_requests WHERE id=?',(request_id,)).fetchone()['status']=='ACKNOWLEDGED'
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_ACKNOWLEDGED' AND detail=?",(str(request_id),)).fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_RESOLVED' AND detail=?",(str(request_id),)).fetchone()['n']==0
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
        assert conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']==stock
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    same=client.post('/api/admin/help-requests/'+str(request_id)+'/status',headers=admin_header,json={'status':'ACKNOWLEDGED'})
    assert same.status_code==200 and same.json()['outcome']=='IDEMPOTENT' and same.json()['duplicate'] is False
    assert same.json()['applied'] is False and same.json()['status']=='ACKNOWLEDGED'
    done=client.post('/api/admin/help-requests/'+str(request_id)+'/status',headers=admin_header,json={'status':'RESOLVED'})
    assert done.status_code==200 and done.json()['applied'] is True and done.json()['outcome']=='RESOLVED'
    assert done.json()['status']=='RESOLVED' and done.json()['physical_door_opened'] is False
    back=client.post('/api/admin/help-requests/'+str(request_id)+'/status',headers=admin_header,json={'status':'ACKNOWLEDGED'})
    assert back.status_code==409 and back.json()['detail']=='已处理的求助不能改回未处理'
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT status FROM help_requests WHERE id=?',(request_id,)).fetchone()['status']=='RESOLVED'
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_ACKNOWLEDGED' AND detail=?",(str(request_id),)).fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_RESOLVED' AND detail=?",(str(request_id),)).fetchone()['n']==1
        assert conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']==stock
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result IN ('UNLOCK','OPEN')").fetchone()['n']==0
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    chunk=script.split('const helpAction=')[1].split('const nav=')[0]
    assert 'state.helpStatus.has(helpId)' in chunk and 'helpAction.disabled=true' in chunk
    assert chunk.index('state.helpStatus.has(helpId)')<chunk.index("'/status'")
    assert "r.duplicate||r.applied===false||r.outcome==='IDEMPOTENT'" in chunk
    assert "toast(r.status==='RESOLVED'?'求助已处理，门未打开':'已确认求助，门未打开')" in chunk
    assert 'state.listing' in script and 'state.editing' in script and 'state.adding' in script and 'state.adjusting' in script
