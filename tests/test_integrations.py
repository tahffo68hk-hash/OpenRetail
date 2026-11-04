from conftest import visitor
from openretail.importer import parse_catalog,ImportErrorDetail
from openretail.adapters import ERPNextReader,HomeAssistantAdapter
from openretail.config import Settings
import pytest
import httpx


def test_ospos_style_csv_import(client,admin_header):
    data=b'item_number,name,unit_price,quantity\n00123,Notebook,10.50,22\n00124,Pencil,2.30,10\n'
    def send(dry):
        return client.post('/api/admin/import-products?dry_run='+str(dry).lower(),
                          headers=admin_header,files={'file':('items.csv',data,'text/csv')})
    p=send(True);assert p.status_code==200 and p.json()['count']==2
    assert not any(x['barcode']=='00123' for x in client.get('/api/products').json())
    actual=send(False);assert actual.status_code==200
    item=next(x for x in client.get('/api/products').json() if x['barcode']=='00123')
    assert item['price_cents']==1050 and item['stock']==22


def test_bad_csv_rejected(client,admin_header):
    data=b'barcode,name,price,stock\n001,Pen,-10,3\n'
    resp=client.post('/api/admin/import-products',headers=admin_header,files={'file':('bad.csv',data)})
    assert resp.status_code==422
    with pytest.raises(ImportErrorDetail):parse_catalog(b'barcode,name,price,stock\nABC,Pen,4,3\nABC,Pen,4,3\n')


def test_frigate_integration_auth_dedupe(client,integration_header,admin_header):
    event={'type':'new','after':{'id':'abc123','label':'person','camera':'entrance'}}
    assert client.post('/api/integrations/frigate-event',json=event).status_code==401
    first=client.post('/api/integrations/frigate-event',headers=integration_header,json=event)
    second=client.post('/api/integrations/frigate-event',headers=integration_header,json=event)
    assert first.json()=={'stored':True,'theft_detected':False}
    assert second.json()['stored'] is False
    events=client.get('/api/admin/events',headers=admin_header).json()
    assert len(events['frigate'])==1 and events['frigate'][0]['camera']=='entrance'
    assert client.post('/api/integrations/frigate-event',headers=integration_header,json={'type':'new','after':{'id':'car1','label':'car','camera':'entrance'}}).json()['stored'] is False


def test_ha_no_real_unlock():
    cfg=Settings(admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,ha_enabled=False)
    ha=HomeAssistantAdapter(cfg)
    assert ha.status()['status']=='NOT_CONFIGURED'
    assert ha.unlock()=='SIMULATED'
    assert not ha.publish_event('retail_demo',{})


def test_erpnext_frappe_readonly_api():
    def handler(request):
        assert request.url.path=='/api/resource/Item'
        assert request.method=='GET'
        assert request.headers['Authorization']=='token key:secret'
        return httpx.Response(200,json={'data':[{'item_code':'10001','item_name':'Cup','disabled':0}]})
    cli=httpx.Client(transport=httpx.MockTransport(handler))
    cfg=Settings(admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
                 erpnext_url='https://erp.invalid',erpnext_api_key='key',erpnext_api_secret='secret')
    result=ERPNextReader(cfg,cli).preview()
    assert result['items'][0]['item_code']=='10001'
    assert result['ready_for_sale'] is False


def test_customer_cannot_access_admin_or_integration(client):
    auth=visitor(client)
    assert client.get('/api/admin/orders',headers=auth).status_code==401
    assert client.post('/api/integrations/frigate-event',headers=auth,json={'type':'new'}).status_code==401
