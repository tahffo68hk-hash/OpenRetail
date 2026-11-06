"""A blank barcode is a prompt to type one, not a product lookup."""
from urllib.parse import quote
from conftest import visitor


def test_blank_barcode_does_not_lookup_or_move_stock(client, admin_header):
    guest=visitor(client)
    water=next(item for item in client.get('/api/products').json() if item['barcode']=='6901234567892')
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(water['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        orders=conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    for raw in (' ', '   ', '\t', ' \n '):
        blank=client.get('/api/products/by-barcode/'+quote(raw,safe=''))
        assert blank.status_code==422 and blank.json()['detail']=='请输入商品条码'
    missing_path=client.get('/api/products/by-barcode/')
    assert missing_path.status_code==422 and missing_path.json()['detail']=='请输入商品条码'
    unknown=client.get('/api/products/by-barcode/0000000000000')
    assert unknown.status_code==404 and unknown.json()['detail']=='未找到条码'
    found=client.get('/api/products/by-barcode/6901234567892')
    assert found.status_code==200 and found.json()['id']==water['id'] and '瓶装饮用水' in found.json()['name']
    assert client.get('/api/orders',headers=guest).json()==[]
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(water['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']==orders
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert "showScanError('请输入商品条码')" in script and 'armBarcodeField()' in script
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
