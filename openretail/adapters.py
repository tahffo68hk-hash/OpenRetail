"""Actual API integration boundaries. No direct device control by default."""
import json
import re
import httpx
from .config import Settings

# Official entity ids are domain.object_id. Reject slashes so a contact read cannot become a service call.
_ENTITY_ID=re.compile(r'^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$')

class IntegrationError(Exception):
    pass

class HomeAssistantAdapter:
    def __init__(self, settings:Settings, client:httpx.Client|None=None):
        self.cfg=settings
        self.client=client or httpx.Client(timeout=4.0)

    def status(self):
        if not self.cfg.ha_enabled:
            return {'status':'NOT_CONFIGURED','control':'SIMULATOR_ONLY'}
        if not self.cfg.ha_token:
            return {'status':'MISSING_TOKEN','control':'DISABLED'}
        try:
            r=self.client.get(self.cfg.ha_url.rstrip('/')+'/api/',
                              headers={'Authorization':f'Bearer {self.cfg.ha_token}'})
            r.raise_for_status()
            return {'status':'CONNECTED','control':'DISABLED_IN_V1'}
        except httpx.HTTPError:
            return {'status':'UNAVAILABLE','control':'DISABLED'}

    def door_contact(self)->dict:
        """Read one entity with GET /api/states/<entity_id>. Never calls a lock service."""
        entity=(self.cfg.ha_door_state_entity or '').strip()
        report={'configured':False,'available':False,'entity_id':'','state':None,'device_class':None,
                'read_only':True,'physical_door_opened':False,'lock_service_called':False,'reason':'NOT_CONFIGURED'}
        if not self.cfg.ha_enabled or not entity:
            return report
        if not _ENTITY_ID.fullmatch(entity):
            report['reason']='UNAVAILABLE'
            return report
        report['configured']=True
        report['entity_id']=entity
        if not self.cfg.ha_token:
            report['reason']='UNAVAILABLE'
            return report
        url=self.cfg.ha_url.rstrip('/')+'/api/states/'+entity
        try:
            response=self.client.get(url,headers={'Authorization':'Bearer '+self.cfg.ha_token})
            response.raise_for_status()
            body=response.json()
        except (httpx.HTTPError,ValueError):
            report['reason']='UNAVAILABLE'
            return report
        if not isinstance(body,dict):
            report['reason']='UNAVAILABLE'
            return report
        state=body.get('state')
        attrs=body.get('attributes') if isinstance(body.get('attributes'),dict) else {}
        device_class=attrs.get('device_class')
        report['device_class']=device_class if isinstance(device_class,str) else None
        if not isinstance(state,str) or state in ('','unavailable','unknown'):
            report['state']=state if isinstance(state,str) and state else None
            report['reason']='UNAVAILABLE'
            return report
        report['available']=True
        report['state']=state
        report['reason']='READ'
        return report

    def unlock(self)->str:
        # Safety property: V1 always simulates, even if HA is reachable.
        if not self.cfg.live_door_enabled:
            return 'SIMULATED'
        # Settings.validate forbids this branch, preserve fail-closed design.
        raise IntegrationError('V1 does not permit real door unlocks')

    def publish_event(self,event_type:str,event_data:dict):
        """Optional HA event bus notification, not a command to unlock a door."""
        if not self.cfg.ha_enabled or not self.cfg.ha_token:
            return False
        try:
            r=self.client.post(self.cfg.ha_url.rstrip('/')+'/api/events/'+event_type,
                headers={'Authorization':f'Bearer {self.cfg.ha_token}'},json=event_data)
            r.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

class ERPNextReader:
    """Read-only Item catalog preview. Prices & barcodes require explicit mapping."""
    def __init__(self,settings:Settings,client:httpx.Client|None=None):
        self.cfg=settings
        self.client=client or httpx.Client(timeout=10.0)

    def preview(self,limit:int=50):
        if not (self.cfg.erpnext_url and self.cfg.erpnext_api_key and self.cfg.erpnext_api_secret):
            raise IntegrationError('ERPNext credentials are not configured')
        headers={'Authorization':f'token {self.cfg.erpnext_api_key}:{self.cfg.erpnext_api_secret}'}
        params={'fields':json.dumps(['item_code','item_name','disabled']),
                'limit_page_length':min(limit,100),'limit_start':0}
        try:
            r=self.client.get(self.cfg.erpnext_url.rstrip('/')+'/api/resource/Item',
                              headers=headers,params=params)
            r.raise_for_status()
            data=r.json()['data']
        except (httpx.HTTPError,KeyError,ValueError) as exc:
            raise IntegrationError('ERPNext catalog read failed') from exc
        return {'items':data, 'ready_for_sale':False,
                'note':'Read-only catalog only. Item Price and Item Barcode require mapping; no order/stock sync.'}
