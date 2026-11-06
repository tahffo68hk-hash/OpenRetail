"""A second help submit is ignored only while the first one is still in flight."""
import threading
import anyio
from httpx import ASGITransport, AsyncClient


def test_overlapping_help_creates_one_request(client, admin_header):
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    short=client.post('/api/help',json={'message':' '})
    assert short.status_code==422 and short.json()['detail']=='请写一句需要店员协助的话'
    entered=threading.Event()
    release=threading.Event()
    def hold():
        entered.set()
        assert release.wait(3)
    client.app.state.hold_help=hold
    results=[]
    async def overlap():
        transport=ASGITransport(app=client.app)
        async with AsyncClient(transport=transport,base_url='http://test') as http:
            async def post(tag):
                response=await http.post('/api/help',json={'message':'请帮忙看一下货架'})
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
        client.app.state.hold_help=None
        release.set()
    assert len(results)==2
    bodies={tag:body for tag,_,body in results}
    assert bodies['first']['duplicate'] is False and bodies['second']['duplicate'] is True
    assert bodies['first']['physical_door_opened'] is False and bodies['second']['physical_door_opened'] is False
    assert bodies['first']['door_authorized'] is False and bodies['first']['payment_required_to_leave'] is False
    with client.app.state.db.connect() as conn:
        rows=conn.execute('SELECT message,status FROM help_requests').fetchall()
        assert [(row['message'],row['status']) for row in rows]==[('请帮忙看一下货架','OPEN')]
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_REQUEST'").fetchone()['n']==1
    later=client.post('/api/help',json={'message':'另外需要一个袋子'})
    assert later.status_code==201 and later.json()['duplicate'] is False
    assert later.json()['physical_door_opened'] is False and later.json()['door_authorized'] is False
    listed=client.get('/api/admin/help-requests',headers=admin_header).json()['requests']
    assert {row['message'] for row in listed}=={'请帮忙看一下货架','另外需要一个袋子'}
    assert all(row['status']=='OPEN' for row in listed)
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_REQUEST'").fetchone()['n']==2
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'state.helping' in script and "$('help-btn').disabled=true" in script
    assert "请写一句需要店员协助的话" in script
