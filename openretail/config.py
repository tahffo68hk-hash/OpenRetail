"""Fail-closed runtime configuration. All keys are server-side secrets."""
from dataclasses import dataclass
import os
import secrets
import sys
from dotenv import load_dotenv

load_dotenv()

def flag(name:str,default:bool=False)->bool:
    return os.getenv(name,str(default)).strip().lower() in ('true','yes','1','on')

@dataclass(frozen=True)
class Settings:
    db_path:str=os.getenv('DB_PATH','./data/openretail.sqlite3')
    app_mode:str=os.getenv('APP_MODE','demo')  # demo | staging | production; pilot is a staging alias
    admin_key:str=os.getenv('ADMIN_KEY','')
    admin_password_hash:str=os.getenv('ADMIN_PASSWORD_HASH','')
    integration_key:str=os.getenv('INTEGRATION_KEY','')
    app_secret:str=os.getenv('APP_SECRET','')
    mock_payments:bool=flag('MOCK_PAYMENTS_ENABLED',True)
    ha_enabled:bool=flag('HA_ENABLED')
    live_door_enabled:bool=flag('LIVE_DOOR_ENABLED')
    ha_url:str=os.getenv('HA_URL','http://127.0.0.1:8123')
    ha_token:str=os.getenv('HA_TOKEN','')
    ha_unlock_script:str=os.getenv('HA_UNLOCK_SCRIPT','script.openretail_entry_unlock')
    ha_door_state_entity:str=os.getenv('HA_DOOR_STATE_ENTITY','')
    erpnext_url:str=os.getenv('ERPNEXT_URL','')
    erpnext_api_key:str=os.getenv('ERPNEXT_API_KEY','')
    erpnext_api_secret:str=os.getenv('ERPNEXT_API_SECRET','')
    public_base_url:str=os.getenv('PUBLIC_BASE_URL','')
    payment_provider:str=os.getenv('PAYMENT_PROVIDER','disabled') # disabled | wechat_native
    wechat_mchid:str=os.getenv('WECHAT_MCHID','')
    wechat_appid:str=os.getenv('WECHAT_APPID','')
    wechat_serial:str=os.getenv('WECHAT_MERCHANT_SERIAL','')
    wechat_private_key_file:str=os.getenv('WECHAT_MERCHANT_PRIVATE_KEY_FILE','')
    wechat_platform_pubkey_file:str=os.getenv('WECHAT_PLATFORM_PUBLIC_KEY_FILE','')
    wechat_platform_serial:str=os.getenv('WECHAT_PLATFORM_SERIAL','')
    wechat_api_v3_key:str=os.getenv('WECHAT_API_V3_KEY','')
    wechat_notify_url:str=os.getenv('WECHAT_NOTIFY_URL','')
    wechat_api_url:str='https://api.mch.weixin.qq.com'
    trusted_proxy_tls:bool=flag('TRUSTED_PROXY_TLS')
    approved_store:bool=flag('STORE_SITE_APPROVED')  # not self-certifying on-site acceptance

    def __post_init__(self):
        # Demo may boot before scripts/init_env.py. Ephemeral keys stay in memory.
        # Staging and production never receive generated keys.
        object.__setattr__(self,'demo_secrets_generated',False)
        if self.profile!='demo':
            return
        generated=[]
        for name in ('admin_key','integration_key','app_secret'):
            value=getattr(self,name) or ''
            if len(value)<24 or value.startswith('REPLACE_WITH_'):
                object.__setattr__(self,name,secrets.token_urlsafe(32))
                generated.append(name)
        object.__setattr__(self,'demo_secrets_generated',bool(generated))

    @property
    def profile(self)->str:
        return {'demo':'demo','staging':'staging','pilot':'staging','production':'production'}.get(self.app_mode,'invalid')

    @property
    def demo(self)->bool:return self.profile=='demo'

    def validate(self):
        if not (self.admin_key and self.integration_key and self.app_secret):
            raise RuntimeError('Run scripts/init_env.py to create randomized secrets')
        if min(map(len,(self.admin_key,self.integration_key,self.app_secret)))<24:
            raise RuntimeError('ADMIN_KEY / INTEGRATION_KEY / APP_SECRET must be >=24 chars')
        if any(s.startswith('REPLACE_WITH_') for s in (self.admin_key,self.integration_key,self.app_secret)):
            raise RuntimeError('Example placeholder secrets prohibited')
        if self.profile=='invalid':
            raise RuntimeError('APP_MODE must be demo, staging, or production')
        if self.mock_payments and not self.demo:
            raise RuntimeError('Mock payments are allowed in demo mode only')
        if self.live_door_enabled:
            raise RuntimeError('LIVE_DOOR_ENABLED remains prohibited until on-site hardware and egress gate')
        if self.profile in ('staging','production'):
            if not self.public_base_url.startswith('https://'):
                raise RuntimeError('Staging and production require PUBLIC_BASE_URL (https://...)')
            if not self.admin_password_hash:
                raise RuntimeError('Staging and production require ADMIN_PASSWORD_HASH; create via scripts/set_admin_password.py')
            if not self.trusted_proxy_tls:
                raise RuntimeError('Staging and production require TLS reverse-proxy configuration')
        if self.payment_provider not in ('disabled','wechat_native'):
            raise RuntimeError('Unsupported PAYMENT_PROVIDER')
        if self.payment_provider!='disabled':
            if self.demo:raise RuntimeError('Real payments are prohibited in demo mode')
            fields=(self.wechat_mchid,self.wechat_appid,self.wechat_serial,
                    self.wechat_private_key_file,self.wechat_platform_pubkey_file,
                    self.wechat_platform_serial,self.wechat_api_v3_key,self.wechat_notify_url)
            if not all(fields):raise RuntimeError('Incomplete WeChat merchant config')
            if len(self.wechat_api_v3_key.encode())!=32:raise RuntimeError('APIv3 key must be 32 bytes')
            if not self.wechat_notify_url.startswith('https://'):
                raise RuntimeError('WeChat notify URL requires HTTPS')
