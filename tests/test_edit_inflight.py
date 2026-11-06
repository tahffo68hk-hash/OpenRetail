"""A second name and price edit is ignored while the first is in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_product_edit_writes_one_audit(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    made=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077888','name':'原名','price_cents':100,'stock':6,'active':True})
    assert made.status_code==200
    product_id=made.json()['id']
    with client.app.state.db.connect() as conn:
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(product_id,)).fetchone()['n']
    for body,detail in (
        ({'name':'   ','price_cents':250},'请输入商品名称'),
        ({'name':'不应改','price_cents':0},'请输入有效售价'),
    ):
        denied=client.patch('/api/admin/products/'+str(product_id),headers=admin_header,json=body)
        assert denied.status_code==422 and denied.json()['detail']==detail
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_edit=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def patch(tag,body):
                response=await http.patch('/api/admin/products/'+str(product_id),headers=admin_header,json=body)
                results.append((tag,response.status_code,response.json()))
            async def second():
                for _ in range(100):
                    if entered.is_set():break
                    await anyio.sleep(0.01)
                assert entered.is_set()
                await patch('second',{'name':'第二次名称','price_cents':999})
                release.set()
            async with anyio.create_task_group() as tg:
                tg.start_soon(patch,'first',{'name':'新名','price_cents':250})
                tg.start_soon(second)
    try:
        anyio.run(overlap)
    finally:
        client.app.state.hold_edit=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['applied'] is True and bodies['first']['duplicate'] is False
    assert bodies['first']['name']=='新名' and bodies['first']['price_cents']==250
    assert bodies['first']['stock']==6 and bodies['first']['reserved_stock']==0
    assert bodies['first']['stock_changed'] is False
    assert bodies['second']['applied'] is False and bodies['second']['duplicate'] is True
    assert bodies['second']['stock']==6 and bodies['second']['stock_changed'] is False
    for body in bodies.values():
        assert body['physical_door_opened'] is False and body['identity_verified'] is False
        assert body['door_authorized'] is False and body['system_of_record']=='sqlite'
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT name,price_cents,stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        assert row['name']=='新名' and row['price_cents']==250 and row['stock']==6 and row['reserved_stock']==0
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_EDIT' AND detail='6900000077888'").fetchone()['n']==1
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(product_id,)).fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    later=client.patch('/api/admin/products/'+str(product_id),headers=admin_header,
                       json={'name':'再改','price_cents':300})
    assert later.status_code==200 and later.json()['applied'] is True and later.json()['duplicate'] is False
    assert later.json()['name']=='再改' and later.json()['price_cents']==300
    assert later.json()['stock']==6 and later.json()['stock_changed'] is False
    with client.app.state.db.connect() as conn:
        row=conn.execute('SELECT name,price_cents,stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
        assert row['name']=='再改' and row['price_cents']==300 and row['stock']==6 and row['reserved_stock']==0
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_EDIT' AND detail='6900000077888'").fetchone()['n']==2
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements WHERE product_id=?',(product_id,)).fetchone()['n']==moves
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result IN ('UNLOCK','OPEN')").fetchone()['n']==0
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    form=script.split("$('edit-form').onsubmit")[1].split("$('adjust-form').onsubmit")[0]
    assert 'state.editing' in form and 'button.disabled=true' in form
    assert form.index('blankAdminBarcode')<form.index('blankAdminName')<form.index('adminPriceCents')<form.index('state.editing')
    assert form.index('if(state.editing)return')<form.index("method:'PATCH'")
    assert "toast('名称和售价已更新')" in form and 'r.duplicate||r.applied===false' in form
    assert "blankAdminBarcode(f.get('barcode'));if(!barcode)return;const name=blankAdminName" in form
    assert "blankAdminName(f.get('name'));if(!name)return;const priceCents=adminPriceCents" in form
    assert 'state.adding' in script and 'state.adjusting' in script
