"""Daily admin glance: mock money stays separate from verified money, and low stock is on-hand."""
from datetime import datetime, timezone
from conftest import visitor


def day_start():
    moment=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    return int(moment.timestamp())


def test_today_summary_counts_mock_sales_only_and_ignores_resolved_help(client, admin_header):
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    order=client.post('/api/orders', headers=guest, json={'request_id':'today-mock-sale-0001',
        'lines':[{'product_id':product['id'], 'quantity':1}]}).json()
    assert client.post('/api/payments/mock-confirm', headers=guest, json={'order_id':order['id']}).json()['status']=='PAID'
    open_help=client.post('/api/help', json={'message':'还没人来'}).json()
    acknowledged=client.post('/api/help', json={'message':'已经看到'}).json()
    resolved=client.post('/api/help', json={'message':'已经处理好'}).json()
    assert client.post(f"/api/admin/help-requests/{acknowledged['id']}/status", headers=admin_header,
                       json={'status':'ACKNOWLEDGED'}).status_code==200
    assert client.post(f"/api/admin/help-requests/{resolved['id']}/status", headers=admin_header,
                       json={'status':'RESOLVED'}).status_code==200
    summary=client.get('/api/admin/overview', headers=admin_header).json()
    assert summary['real_door_enabled'] is False
    assert summary['today_order_count']>=1
    assert summary['today_simulated_revenue_cents']==product['price_cents']
    assert summary['today_verified_revenue_cents']==0
    assert summary['verified_revenue_cents']==0
    assert summary['help_needs_attention']==2
    assert summary['help_open']==1 and summary['help_acknowledged']==1 and summary['help_resolved']==1
    assert open_help['id']!=resolved['id']
    with client.app.state.db.tx() as conn:
        yesterday=day_start()-60
        conn.execute('UPDATE orders SET created_at=?, paid_at=? WHERE id=?', (yesterday, yesterday, order['id']))
    later=client.get('/api/admin/overview', headers=admin_header).json()
    assert later['today_simulated_revenue_cents']==0
    assert later['today_verified_revenue_cents']==0
    assert later['today_order_count']==summary['today_order_count']-1


def test_low_stock_uses_on_hand_and_still_shows_reservations(client, admin_header):
    low=client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000011115', 'name':'低库存', 'price_cents':100, 'stock':5, 'active':True}).json()
    assert client.post('/api/admin/products', headers=admin_header, json={
        'barcode':'6900000011116', 'name':'库存充足', 'price_cents':100, 'stock':6, 'active':True}).status_code==200
    guest=visitor(client)
    assert client.post('/api/orders', headers=guest, json={'request_id':'low-stock-still-works',
        'lines':[{'product_id':low['id'], 'quantity':2}]}).status_code==201
    summary=client.get('/api/admin/overview', headers=admin_header).json()
    assert summary['low_stock_threshold']==5
    barcodes={row['barcode']:row for row in summary['low_stock']}
    assert '6900000011115' in barcodes
    assert '6900000011116' not in barcodes
    row=barcodes['6900000011115']
    assert row['stock']==5 and row['reserved_stock']==2 and row['available_stock']==3
    assert summary['today_verified_revenue_cents']==0
    assert summary['real_door_enabled'] is False
