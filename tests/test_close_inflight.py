"""A second staff close is ignored only while that order's first close is still in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_mock_close_releases_one_hold(client, admin_header):
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
    created=client.post('/api/orders',headers=auth,json={'request_id':'close-inflight-0001',
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
    client.app.state.hold_close=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/admin/orders/'+order['id']+'/mock-close',headers=admin_header)
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
        client.app.state.hold_close=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['duplicate'] is False and bodies['first']['outcome']=='CLOSED'
    assert bodies['first']['stock_changed'] is False and bodies['first']['remote_call'] is False
    assert bodies['second']['duplicate'] is True and bodies['second']['stock_changed'] is False
    for body in bodies.values():
        assert body['real_money'] is False and body['physical_door_opened'] is False
        assert body['identity_verified'] is False and body['door_authorized'] is False
    assert client.get('/api/products').json()[0]['stock']==stock['stock']
    assert client.get('/api/products').json()[0]['reserved_stock']==stock['reserved_stock']
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='ORDER_CLOSED' AND detail=?",
                            (order['id'],)).fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='MOCK_CLOSED' AND reference=?",
                            (order['id'],)).fetchone()['n']==1
    later=client.post('/api/admin/orders/'+order['id']+'/mock-close',headers=admin_header)
    assert later.status_code==200 and later.json()['outcome']=='IDEMPOTENT' and later.json()['duplicate'] is False
    assert later.json()['stock_changed'] is False and later.json()['physical_door_opened'] is False
    assert client.get('/api/products').json()[0]['stock']==stock['stock']
    assert client.get('/api/products').json()[0]['reserved_stock']==stock['reserved_stock']
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='ORDER_CLOSED'").fetchone()['n']==1
    paid=client.post('/api/orders',headers=auth,json={'request_id':'close-inflight-paid1',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    assert client.post('/api/payments/mock-confirm',headers=auth,json={'order_id':paid.json()['id']}).json()['status']=='PAID'
    refused=client.post('/api/admin/orders/'+paid.json()['id']+'/mock-close',headers=admin_header)
    assert refused.status_code==409
    assert refused.json()['detail']=='已模拟支付的订单不能关单，如需退回库存请使用模拟退款'
    assert client.post('/api/admin/orders/'+paid.json()['id']+'/mock-refund',headers=admin_header).json()['stock_restored'] is True
    refunded=client.post('/api/admin/orders/'+paid.json()['id']+'/mock-close',headers=admin_header)
    assert refunded.status_code==409 and refunded.json()['detail']=='订单已模拟退款'
    external=client.post('/api/orders',headers=auth,json={'request_id':'close-inflight-ext001',
        'lines':[{'product_id':product['id'],'quantity':1}]})
    with client.app.state.db.tx() as conn:
        conn.execute('''UPDATE orders SET status='PAYMENT_PENDING', payment_reference='weixin://wxpay/bizpayurl?pr=TEST'
                        WHERE id=?''',(external.json()['id'],))
    blocked=client.post('/api/admin/orders/'+external.json()['id']+'/mock-close',headers=admin_header)
    assert blocked.status_code==409
    assert blocked.json()['detail']=='外部支付单请使用微信查单关单，模拟关单不会访问微信'
    assert client.get('/api/products').json()[0]['stock']==stock['stock']
    assert client.get('/api/products').json()[0]['reserved_stock']==stock['reserved_stock']+1
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='ORDER_CLOSED'").fetchone()['n']==1
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    assert unlocks==[]
    assert client.get('/api/admin/overview',headers=admin_header).json()['mode']=='STAFFED'
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    close_script=script.split("const closeHold=")[1].split("const refund=")[0]
    assert 'state.closing.has(closeId)' in close_script and 'closeHold.disabled=true' in close_script
    assert 'if(r.duplicate)return' in close_script
    assert "toast(r.outcome==='IDEMPOTENT'?'订单已经关闭':'已释放预留，账面库存未扣')" in close_script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=auth).status_code==404
