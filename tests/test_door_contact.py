"""Door contact is a read-only Home Assistant state, never a lock command."""
import httpx
from openretail.adapters import HomeAssistantAdapter
from openretail.config import Settings


def _settings(**overrides):
    base=dict(admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
              app_mode='demo',mock_payments=True,live_door_enabled=False,
              ha_url='https://ha.invalid',ha_token='',ha_enabled=False,ha_door_state_entity='')
    base.update(overrides)
    return Settings(**base)


def test_door_contact_is_read_only(client, admin_header):
    assert client.get('/api/admin/events').status_code==401
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
    listed=client.get('/api/admin/events',headers=admin_header).json()
    assert listed['physical_door_opened'] is False
    assert listed['door_contact']['configured'] is False
    assert listed['door_contact']['available'] is False
    assert listed['door_contact']['reason']=='NOT_CONFIGURED'
    assert listed['door_contact']['state'] is None
    assert listed['door_contact']['physical_door_opened'] is False
    assert listed['door_contact']['lock_service_called'] is False
    again=client.get('/api/admin/events',headers=admin_header).json()
    assert again['door_contact']==listed['door_contact']
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
    page=__import__('pathlib').Path('web/index.html').read_text(encoding='utf-8')
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert 'id="door-contact"' in page and '门磁未配置' in page
    assert '门磁未配置' in script and '不是开锁' in script
    seen=[]
    def handler(request):
        seen.append((request.method,request.url.path))
        assert request.method=='GET'
        assert request.url.path=='/api/states/binary_sensor.openretail_door_contact'
        assert 'services' not in request.url.path
        assert request.headers['Authorization']=='Bearer test-token'
        return httpx.Response(200,json={
            'entity_id':'binary_sensor.openretail_door_contact',
            'state':'on',
            'attributes':{'device_class':'door'},
        })
    cfg=_settings(ha_enabled=True,ha_token='test-token',ha_door_state_entity='binary_sensor.openretail_door_contact')
    ha=HomeAssistantAdapter(cfg,httpx.Client(transport=httpx.MockTransport(handler)))
    contact=ha.door_contact()
    assert contact['available'] is True and contact['state']=='on'
    assert contact['device_class']=='door' and contact['read_only'] is True
    assert contact['physical_door_opened'] is False and contact['lock_service_called'] is False
    assert seen==[('GET','/api/states/binary_sensor.openretail_door_contact')]
    assert ha.unlock()=='SIMULATED'
    def refuse(request):
        raise AssertionError('unconfigured contact must not call Home Assistant')
    quiet=HomeAssistantAdapter(_settings(),httpx.Client(transport=httpx.MockTransport(refuse)))
    assert quiet.door_contact()['reason']=='NOT_CONFIGURED'
    assert quiet.unlock()=='SIMULATED'
    blocked=HomeAssistantAdapter(
        _settings(ha_enabled=True,ha_token='test-token',ha_door_state_entity='../api/services/lock/unlock'),
        httpx.Client(transport=httpx.MockTransport(refuse)))
    rejected=blocked.door_contact()
    assert rejected['available'] is False and rejected['physical_door_opened'] is False
    assert blocked.unlock()=='SIMULATED'
