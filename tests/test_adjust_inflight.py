"""A second stock adjustment is ignored while the first is in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_stock_adjust_applies_once(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077444','name':'调整进行中','price_cents':100,'stock':10,'active':True})
    assert made.status_code==200
    product_id=made.json()['id']
    with client.app.state.db.connect() as conn:
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_adjust=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/admin/products/'+str(product_id)+'/adjust-stock',headers=admin_header,
                                         json={'quantity_delta':2,'reason':'到货入库'})
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
        client.app.state.hold_adjust=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['applied'] is True and bodies['first']['duplicate'] is False
    assert bodies['first']['stock']==12 and bodies['first']['reserved_stock']==0
    assert bodies['second']['applied'] is False and bodies['second']['duplicate'] is True
    assert bodies['second']['stock']==10 or bodies['second']['stock']==12
    for body in bodies.values():
        assert body['physical_door_opened'] is False and body['identity_verified'] is False
        assert body['door_authorized'] is False and body['system_of_record']=='sqlite'
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        assert row['stock']==12 and row['reserved_stock']==0
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST' AND detail=?",
                            ('6900000077444:2',)).fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reference='MANUAL' AND product_id=?",
                            (product_id,)).fetchone()['n']==1
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    again=client.post('/api/admin/products/'+str(product_id)+'/adjust-stock',headers=admin_header,
                      json={'quantity_delta':2,'reason':'到货入库'})
    assert again.status_code==200 and again.json()['applied'] is True and again.json()['stock']==14
    denied=client.post('/api/admin/products/'+str(product_id)+'/adjust-stock',headers=admin_header,
                       json={'quantity_delta':0,'reason':'盘点修正'})
    assert denied.status_code==422 and denied.json()['detail']=='调整数量不能为 0'
    guest=visitor(client)
    held=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077555','name':'调整底线','price_cents':100,'stock':3,'active':True}).json()
    assert client.post('/api/orders',headers=guest,json={'request_id':'adjust-inflight-floor',
        'lines':[{'product_id':held['id'],'quantity':2}]}).status_code==201
    too_low=client.post('/api/admin/products/'+str(held['id'])+'/adjust-stock',headers=admin_header,
                        json={'quantity_delta':-2,'reason':'商品报损'})
    assert too_low.status_code==409
    assert too_low.json()['detail']=='库存调整会低于可售底线或侵占未结算预留'
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        assert row['stock']==14 and row['reserved_stock']==0
        floor=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(held['id'],)).fetchone()
        assert floor['stock']==3 and floor['reserved_stock']==2
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST' AND detail LIKE '6900000077444:%'").fetchone()['n']==2
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reference='MANUAL' AND product_id=?",
                            (product_id,)).fetchone()['n']==2
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST' AND detail LIKE '6900000077555:%'").fetchone()['n']==0
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result IN ('UNLOCK','OPEN')").fetchone()['n']==0
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    adjust=script.split("$('adjust-form').onsubmit")[1].split('async function uploadCsv')[0]
    assert 'state.adjusting' in adjust and 'button.disabled=true' in adjust
    assert adjust.index('blankAdminBarcode')<adjust.index('adminStockDelta')<adjust.index('state.adjusting')
    assert adjust.index("if(state.adjusting)return")<adjust.index("'/adjust-stock'")
    assert "toast('库存已调整')" in adjust and 'r.duplicate||r.applied===false' in adjust
    assert "textContent='调整数量不能为 0'" in script
