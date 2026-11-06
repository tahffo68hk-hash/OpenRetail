"""A second product create is ignored while the first is in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient
from conftest import visitor


def test_overlapping_product_create_inserts_once(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    with client.app.state.db.connect() as conn:
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        before=conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']
    for body in (
        {'barcode':'   ','name':'不应新增','price_cents':100,'stock':1,'active':True},
        {'barcode':'6900000077666','name':'   ','price_cents':100,'stock':1,'active':True},
        {'barcode':'6900000077666','name':'不应新增','price_cents':0,'stock':1,'active':True},
    ):
        denied=client.post('/api/admin/products',headers=admin_header,json=body)
        assert denied.status_code==422
        assert denied.json()['detail'] in ('请输入商品条码','请输入商品名称','请输入有效售价')
    with client.app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==before
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_create=hold
    payload={'barcode':'6900000077666','name':'新增进行中','price_cents':150,'stock':4,'active':True}
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag,body):
                response=await http.post('/api/admin/products',headers=admin_header,json=body)
                results.append((tag,response.status_code,response.json()))
            async def second():
                for _ in range(100):
                    if entered.is_set():break
                    await anyio.sleep(0.01)
                assert entered.is_set()
                await post('second',{**payload,'name':'第二次名称','price_cents':999,'stock':9})
                release.set()
            async with anyio.create_task_group() as tg:
                tg.start_soon(post,'first',payload)
                tg.start_soon(second)
    try:
        anyio.run(overlap)
    finally:
        client.app.state.hold_create=None
        release.set()
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['created'] is True and bodies['first']['duplicate'] is False
    assert bodies['first']['barcode']=='6900000077666' and bodies['first']['stock']==4
    assert bodies['first']['name']=='新增进行中' and bodies['first']['price_cents']==150
    assert bodies['second']['created'] is False and bodies['second']['duplicate'] is True
    for body in bodies.values():
        assert body['physical_door_opened'] is False and body['identity_verified'] is False
        assert body['door_authorized'] is False and body['system_of_record']=='sqlite'
    with client.app.state.db.connect() as conn:
        rows=conn.execute("SELECT name,price_cents,stock,reserved_stock FROM products WHERE barcode='6900000077666'").fetchall()
        assert len(rows)==1 and rows[0]['name']=='新增进行中' and rows[0]['price_cents']==150
        assert rows[0]['stock']==4 and rows[0]['reserved_stock']==0
        assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==before+1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_CREATED' AND detail='6900000077666'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='OPENING_BALANCE' AND reference='6900000077666'").fetchone()['n']==1
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    other=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077777','name':'稍后新增','price_cents':200,'stock':3,'active':True})
    assert other.status_code==200 and other.json()['created'] is True and other.json()['duplicate'] is False
    assert other.json()['stock']==3 and other.json()['physical_door_opened'] is False
    again=client.post('/api/admin/products',headers=admin_header,json={
        'barcode':'6900000077666','name':'不应覆盖','price_cents':500,'stock':8,'active':False})
    assert again.status_code==409
    assert again.json()['detail']=='条码已存在。请只改名称售价，或做单品库存调整；不要整表覆盖。'
    with client.app.state.db.connect() as conn:
        row=conn.execute("SELECT name,price_cents,stock,active FROM products WHERE barcode='6900000077666'").fetchone()
        assert row['name']=='新增进行中' and row['price_cents']==150 and row['stock']==4 and row['active']==1
        assert conn.execute("SELECT COUNT(*) n FROM products WHERE barcode='6900000077777'").fetchone()['n']==1
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_CREATED'").fetchone()['n']==2
        assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='OPENING_BALANCE'").fetchone()['n']>=2
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result IN ('UNLOCK','OPEN')").fetchone()['n']==0
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    form=script.split("$('product-form').onsubmit")[1].split("$('edit-form').onsubmit")[0]
    assert 'state.adding' in form and 'button.disabled=true' in form
    assert form.index('blankAdminBarcode')<form.index('blankAdminName')<form.index('adminPriceCents')<form.index('state.adding')
    assert form.index('if(state.adding)return')<form.index("'/api/admin/products'")
    assert "toast('商品已新增')" in form and 'r.duplicate||r.created===false' in form
    assert "blankAdminBarcode(f.get('barcode'));if(!barcode)return;const name=blankAdminName" in form
    assert "blankAdminName(f.get('name'));if(!name)return;const priceCents=adminPriceCents" in form
    assert 'state.adjusting' in script
