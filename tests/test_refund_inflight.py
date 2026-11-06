"""A second mock refund is ignored while the first is in flight, and a later one does not restore stock again."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_mock_refund_restores_stock_once(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    auth=visitor(client)
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    created=client.post('/api/orders',headers=auth,json={'request_id':'refund-inflight-0001',
        'lines':[{'product_id':product['id'],'quantity':2}]})
    assert created.status_code==201
    order=created.json()
    paid=client.post('/api/payments/mock-confirm',headers=auth,json={'order_id':order['id']})
    assert paid.status_code==200 and paid.json()['status']=='PAID'
    assert client.get('/api/products').json()[0]['stock']==product['stock']-2
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_refund=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/admin/orders/'+order['id']+'/mock-refund',headers=admin_header)
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
        client.app.state.hold_refund=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['outcome']=='REFUNDED' and bodies['first']['stock_restored'] is True
    assert bodies['first']['duplicate'] is False
    assert bodies['second']['duplicate'] is True and bodies['second']['stock_restored'] is False
    for body in bodies.values():
        assert body['real_money'] is False and body['remote_call'] is False and body['verified']==0
        assert body['provider']=='MOCK_NOT_REAL_MONEY'
        assert body['identity_verified'] is False and body['door_authorized'] is False
        assert body['physical_door_opened'] is False
    assert client.get('/api/products').json()[0]['stock']==product['stock']
    again=client.post('/api/admin/orders/'+order['id']+'/mock-refund',headers=admin_header)
    assert again.status_code==200
    repeat=again.json()
    assert repeat['outcome']=='IDEMPOTENT' and repeat['stock_restored'] is False and repeat['duplicate'] is False
    assert repeat['real_money'] is False and repeat['remote_call'] is False and repeat['verified']==0
    assert repeat['provider']=='MOCK_NOT_REAL_MONEY' and repeat['physical_door_opened'] is False
    assert client.get('/api/products').json()[0]['stock']==product['stock']
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='MOCK_REFUND_RESTORE' AND reference=?",
                            (order['id'],)).fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='MOCK_REFUND' AND detail=?",
                            (order['id'],)).fetchone()['n']==1
        payment=conn.execute('SELECT provider,verified FROM payments WHERE order_id=?',(order['id'],)).fetchone()
        assert payment['provider']=='MOCK_NOT_REAL_MONEY' and int(payment['verified'])==0
        assert conn.execute('SELECT status FROM orders WHERE id=?',(order['id'],)).fetchone()['status']=='REFUNDED'
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    assert client.post('/api/orders/'+order['id']+'/refund',headers=auth).status_code==404
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'state.refunding' in script and 'refund.disabled=true' in script
    assert '模拟退款已回补库存，不是微信退款' in script
    assert '模拟退款已经完成，这次没有增加库存' in script
    assert "r.outcome==='IDEMPOTENT'||r.stock_restored===false" in script
