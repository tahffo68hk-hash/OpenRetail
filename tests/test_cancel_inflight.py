"""A second cancel is ignored only while the first one is still in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_cancel_releases_a_pending_order_once(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    unlocks=[]
    def refuse_unlock(*_args, **_kwargs):
        unlocks.append('unlock')
        raise AssertionError('physical unlock was called')
    client.app.state.ha.unlock=refuse_unlock
    assert client.get('/api/admin/overview',headers=admin_header).json()['mode']=='STAFFED'
    auth=visitor(client)
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    created=client.post('/api/orders',headers=auth,json={'request_id':'cancel-inflight-0001',
        'lines':[{'product_id':product['id'],'quantity':2}]})
    assert created.status_code==201 and created.json()['status']=='PENDING'
    order=created.json()
    assert client.get('/api/products').json()[0]['stock']==stock['stock']
    assert client.get('/api/products').json()[0]['reserved_stock']==stock['reserved_stock']+2
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_cancel=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/orders/'+order['id']+'/cancel',headers=auth)
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
        client.app.state.hold_cancel=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['duplicate'] is False and bodies['first']['status']=='CANCELLED'
    assert bodies['second']['duplicate'] is True and bodies['second']['status'] is None
    for body in bodies.values():
        assert body['physical_door_opened'] is False and body['identity_verified'] is False
        assert body['door_authorized'] is False
    assert client.get('/api/products').json()[0]['stock']==stock['stock']
    assert client.get('/api/products').json()[0]['reserved_stock']==stock['reserved_stock']
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='ORDER_CANCELLED' AND detail=?",
                            (order['id'],)).fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='ORDER_CANCELLED' AND reference=?",
                            (order['id'],)).fetchone()['n']==1
    later=client.post('/api/orders/'+order['id']+'/cancel',headers=auth)
    assert later.status_code==200 and later.json()['status']=='CANCELLED' and later.json()['duplicate'] is False
    assert later.json()['physical_door_opened'] is False
    assert client.get('/api/products').json()[0]['reserved_stock']==stock['reserved_stock']
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='ORDER_CANCELLED'").fetchone()['n']==1
    paid=client.post('/api/orders',headers=auth,json={'request_id':'cancel-inflight-paid1',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert paid.status_code==201
    assert client.post('/api/payments/mock-confirm',headers=auth,json={'order_id':paid.json()['id']}).json()['status']=='PAID'
    refused=client.post('/api/orders/'+paid.json()['id']+'/cancel',headers=auth)
    assert refused.status_code==409
    assert refused.json()['detail']=='已进入支付流程或已付款，不能直接取消'
    assert client.get('/api/products').json()[0]['stock']==stock['stock']-1
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='ORDER_CANCELLED'").fetchone()['n']==1
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    assert unlocks==[]
    assert client.get('/api/admin/overview',headers=admin_header).json()['mode']=='STAFFED'
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'if(state.cancelling)return' in script and "$('cancel-order-btn').disabled=true" in script
    cancel_script=script.split("$('cancel-order-btn').onclick")[1].split('async function pollVerifiedPayment')[0]
    assert 'if(state.cancelling)return' in cancel_script and 'if(r.duplicate)return' in cancel_script
    assert "toast('已取消未付款订单')" in cancel_script
    assert "已取消 · 未付款 · 订单 " in script and '预留已释放' in script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=auth).status_code==404
