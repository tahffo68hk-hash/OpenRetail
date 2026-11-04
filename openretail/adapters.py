"""Actual API integration boundaries. No direct device control by default."""
import json
import httpx
from .config import Settings

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
