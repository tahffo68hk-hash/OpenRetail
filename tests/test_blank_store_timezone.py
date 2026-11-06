"""An empty store timezone is not saved and does not replace the threshold check."""
from conftest import visitor


def test_empty_store_timezone_does_not_save_settings(client, admin_header):
    def fail(*_args, **_kwargs):
        raise AssertionError('live wechat was called')
    client.app.state.wechat.create_native=fail
    client.app.state.wechat.query_trade=fail
    client.app.state.wechat.close_trade=fail
    client.app.state.wechat.verify_notification=fail
    with client.app.state.db.connect() as conn:
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
        stock=conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']
        assert conn.execute("SELECT value FROM store_settings WHERE key='low_stock_threshold'").fetchone()['value']=='5'
        assert conn.execute("SELECT value FROM store_settings WHERE key='store_timezone'").fetchone()['value']=='Asia/Shanghai'
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STORE_SETTINGS'").fetchone()['n']==0
    for raw in ('', '   ', None):
        denied=client.put('/api/admin/store-settings',headers=admin_header,
                          json={'low_stock_threshold':5,'timezone':raw})
        assert denied.status_code==422 and denied.json()['detail']=='无法识别的时区名称，例如 Asia/Shanghai'
    both=client.put('/api/admin/store-settings',headers=admin_header,json={'low_stock_threshold':0,'timezone':'   '})
    assert both.status_code==422 and both.json()['detail']=='请输入有效低库存阈值'
    bad=client.put('/api/admin/store-settings',headers=admin_header,json={'timezone':'Not/AZone'})
    assert bad.status_code==422 and bad.json()['detail']=='无法识别的时区名称，例如 Asia/Shanghai'
    missing=client.put('/api/admin/store-settings',headers=admin_header,json={})
    assert missing.status_code==422 and missing.json()['detail']=='请提供低库存阈值或门店时区'
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT value FROM store_settings WHERE key='low_stock_threshold'").fetchone()['value']=='5'
        assert conn.execute("SELECT value FROM store_settings WHERE key='store_timezone'").fetchone()['value']=='Asia/Shanghai'
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STORE_SETTINGS'").fetchone()['n']==0
        assert conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']==stock
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    saved=client.put('/api/admin/store-settings',headers=admin_header,
                     json={'low_stock_threshold':5,'timezone':'Asia/Shanghai'})
    assert saved.status_code==200 and saved.json()['low_stock_threshold']==5
    assert saved.json()['store_timezone']=='Asia/Shanghai' and saved.json()['physical_door_opened'] is False
    assert saved.json()['identity_verified'] is False and saved.json()['door_authorized'] is False
    only_threshold=client.put('/api/admin/store-settings',headers=admin_header,json={'low_stock_threshold':6})
    assert only_threshold.status_code==200 and only_threshold.json()['low_stock_threshold']==6
    assert only_threshold.json()['store_timezone']=='Asia/Shanghai'
    again=client.put('/api/admin/store-settings',headers=admin_header,json={'low_stock_threshold':6,'timezone':'  '})
    assert again.status_code==422 and again.json()['detail']=='无法识别的时区名称，例如 Asia/Shanghai'
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT value FROM store_settings WHERE key='low_stock_threshold'").fetchone()['value']=='6'
        assert conn.execute("SELECT value FROM store_settings WHERE key='store_timezone'").fetchone()['value']=='Asia/Shanghai'
        assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STORE_SETTINGS'").fetchone()['n']==2
        assert conn.execute('SELECT COALESCE(SUM(stock),0) n FROM products').fetchone()['n']==stock
        assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result IN ('UNLOCK','OPEN')").fetchone()['n']==0
    store=client.get('/api/public/store').json()
    assert store['identity_verified'] is False and store['door_authorized'] is False
    assert store['physical_door_opened'] is False
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    guest=visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    form=script.split("$('store-settings-form').onsubmit")[1].split("$('order-filter').onsubmit")[0]
    assert form.index('adminLowStockThreshold')<form.index('adminStoreTimezone')<form.index("'/api/admin/store-settings'")
    assert "if(threshold==null)return" in form and "if(timezone==null)return" in form
    assert "textContent='无法识别的时区名称，例如 Asia/Shanghai'" in script
    assert "textContent='请输入有效低库存阈值'" in script
