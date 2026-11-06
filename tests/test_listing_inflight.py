"""A second list or unlist is ignored while the first is in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_listing_change_writes_one_audit(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077999','name':'可上下架','price_cents':250,'stock':8,'active':True})
    assert made.status_code==200
    product_id=made.json()['id']
    with client.app.state.db.connect() as conn:
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(product_id,)).fetchone()['n']
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_listing=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag,active):
                response=await http.post('/api/admin/products/'+str(product_id)+'/listing',headers=admin_header,
                                         json={'active':active})
                results.append((tag,response.status_code,response.json()))
            async def second():
                for _ in range(100):
                    if entered.is_set():break
                    await anyio.sleep(0.01)
                assert entered.is_set()
                await post('second',False)
                release.set()
            async with anyio.create_task_group() as tg:
                tg.start_soon(post,'first',False)
                tg.start_soon(second)
    try:
        anyio.run(overlap)
    finally:
        client.app.state.hold_listing=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['applied'] is True and bodies['first']['duplicate'] is False
    assert bodies['first']['outcome']=='UNLISTED' and bodies['first']['active'] is False
    assert bodies['first']['stock']==8 and bodies['first']['reserved_stock']==0
    assert bodies['first']['stock_changed'] is False
    assert bodies['second']['applied'] is False and bodies['second']['duplicate'] is True
    assert bodies['second']['stock']==8 and bodies['second']['stock_changed'] is False
    for body in bodies.values():
        assert body['physical_door_opened'] is False and body['real_door_enabled'] is False
        assert body['identity_verified'] is False and body['door_authorized'] is False
        assert body['system_of_record']=='sqlite'
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock,active FROM products WHERE id=?',(product_id,)).fetchone()
        assert row['stock']==8 and row['reserved_stock']==0 and row['active']==0
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_UNLISTED' AND detail='6900000077999'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_LISTED' AND detail='6900000077999'").fetchone()['n']==0
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(product_id,)).fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    shown=client.post('/api/admin/products/'+str(product_id)+'/listing',headers=admin_header,json={'active':True})
    assert shown.status_code==200 and shown.json()['outcome']=='LISTED' and shown.json()['applied'] is True
    assert shown.json()['active'] is True and shown.json()['stock']==8 and shown.json()['stock_changed'] is False
    same=client.post('/api/admin/products/'+str(product_id)+'/listing',headers=admin_header,json={'active':True})
    assert same.status_code==200 and same.json()['outcome']=='IDEMPOTENT' and same.json()['duplicate'] is False
    assert same.json()['applied'] is False and same.json()['active'] is True and same.json()['stock']==8
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT stock,reserved_stock,active FROM products WHERE id=?',(product_id,)).fetchone()
        assert row['stock']==8 and row['reserved_stock']==0 and row['active']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_UNLISTED' AND detail='6900000077999'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_LISTED' AND detail='6900000077999'").fetchone()['n']==1
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(product_id,)).fetchone()['n']==moves
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result IN ('UNLOCK','OPEN')").fetchone()['n']==0
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    chunk=script.split('const listing=')[1].split('const helpAction=')[0]
    assert 'state.listing.has(listingId)' in chunk and 'listing.disabled=true' in chunk
    assert chunk.index('state.listing.has(listingId)')<chunk.index("'/listing'")
    assert "r.duplicate||r.applied===false||r.outcome==='IDEMPOTENT'" in chunk
    assert "toast(r.active?'已上架':'已下架')" in chunk
    assert 'state.adding' in script and 'state.editing' in script and 'state.adjusting' in script
