"""WeChat Pay API v3 Native QR: signed create, signed/decrypted notifications.

Native QR is useful at a physical kiosk, not an ergonomic same-phone H5 checkout.
No merchant keys are bundled. Explicitly separate cryptographic verification from
application-level amount/merchant/order validation in main.py.
"""
import base64
from datetime import datetime,timezone
import json
import secrets
import time
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx

class PaymentSignatureError(Exception):pass

class WeChatNative:
    def __init__(self,cfg,client:httpx.Client|None=None):
        self.cfg=cfg
        self.client=client or httpx.Client(timeout=8)
        self._merchant_private=None
        self._platform_public=None

    @property
    def merchant_private(self):
        if self._merchant_private is None:
            self._merchant_private=serialization.load_pem_private_key(
                Path(self.cfg.wechat_private_key_file).read_bytes(),password=None)
        return self._merchant_private

    @property
    def platform_public(self):
        if self._platform_public is None:
            self._platform_public=serialization.load_pem_public_key(
                Path(self.cfg.wechat_platform_pubkey_file).read_bytes())
        return self._platform_public

    def sign(self,method:str,path:str,body:str,timestamp:str,nonce:str)->str:
        data=f'{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n'.encode()
        raw=self.merchant_private.sign(data,padding.PKCS1v15(),hashes.SHA256())
        return base64.b64encode(raw).decode()

    def create_native(self,order_id:str,amount:int,description:str='门店自助购物')->str:
        if self.cfg.payment_provider!='wechat_native':raise RuntimeError('WeChat Native disabled')
        path='/v3/pay/transactions/native'
        body=json.dumps({'appid':self.cfg.wechat_appid,'mchid':self.cfg.wechat_mchid,
                         'description':description[:127], 'out_trade_no':order_id,
                         'notify_url':self.cfg.wechat_notify_url,
                         'time_expire':datetime.fromtimestamp(int(time.time())+900,timezone.utc).isoformat(timespec='seconds'),
                         'amount':{'total':amount,'currency':'CNY'}},ensure_ascii=False,separators=(',',':'))
        timestamp=str(int(time.time()));nonce=secrets.token_hex(16)
        sig=self.sign('POST',path,body,timestamp,nonce)
        token=(f'mchid="{self.cfg.wechat_mchid}",nonce_str="{nonce}",'
               f'timestamp="{timestamp}",serial_no="{self.cfg.wechat_serial}",signature="{sig}"')
        response=self.client.post(self.cfg.wechat_api_url+path,content=body.encode(),headers={
            'Authorization':'WECHATPAY2-SHA256-RSA2048 '+token,
            'Accept':'application/json','Content-Type':'application/json','User-Agent':'OpenRetail/2.0'})
        response.raise_for_status()
        # Verify the exact raw response bytes (do not trust a reverse proxy's JSON alone).
        self._verify_provider_message(response.headers,response.content)
        result=response.json()
        code=result.get('code_url','')
        if not isinstance(code,str) or not code.startswith('weixin://'):
            raise PaymentSignatureError('WeChat did not return a valid Native QR code')
        return code

    def _signed_request(self,method:str,path:str,body:str='')->httpx.Response:
        stamp=str(int(time.time()));nonce=secrets.token_hex(16)
        sig=self.sign(method,path,body,stamp,nonce)
        auth=(f'mchid="{self.cfg.wechat_mchid}",nonce_str="{nonce}",'
              f'timestamp="{stamp}",serial_no="{self.cfg.wechat_serial}",signature="{sig}"')
        response=self.client.request(method,self.cfg.wechat_api_url+path,
            content=body.encode() if body else None,
            headers={'Authorization':'WECHATPAY2-SHA256-RSA2048 '+auth,
                     'Accept':'application/json','Content-Type':'application/json','User-Agent':'OpenRetail/2.0'})
        response.raise_for_status()
        if response.content:self._verify_provider_message(response.headers,response.content)
        return response

    def query_trade(self,order_id:str)->dict:
        if self.cfg.payment_provider!='wechat_native':raise RuntimeError('Payment disabled')
        if len(order_id)!=32 or not all(c in '0123456789abcdef' for c in order_id):
            raise ValueError('Invalid merchant order number')
        path=f'/v3/pay/transactions/out-trade-no/{order_id}?mchid={self.cfg.wechat_mchid}'
        result=self._signed_request('GET',path).json()
        if result.get('out_trade_no')!=order_id or result.get('mchid')!=self.cfg.wechat_mchid:
            raise PaymentSignatureError('Queried order identity mismatch')
        return result

    def close_trade(self,order_id:str)->None:
        if len(order_id)!=32 or not all(c in '0123456789abcdef' for c in order_id):
            raise ValueError('Invalid merchant order number')
        path=f'/v3/pay/transactions/out-trade-no/{order_id}/close'
        body=json.dumps({'mchid':self.cfg.wechat_mchid},separators=(',',':'))
        self._signed_request('POST',path,body)

    def _verify_provider_message(self,headers,raw:bytes,now_ts:int|None=None):
        try:
            serial=headers['Wechatpay-Serial']
            timestamp=headers['Wechatpay-Timestamp']
            nonce=headers['Wechatpay-Nonce']
            signature=headers['Wechatpay-Signature']
            if serial!=self.cfg.wechat_platform_serial:
                raise PaymentSignatureError('Untrusted WeChat platform signing key')
            if abs(int(timestamp)-(now_ts if now_ts is not None else int(time.time())))>300:
                raise PaymentSignatureError('Stale or future provider response')
            self.platform_public.verify(base64.b64decode(signature,validate=True),
                f'{timestamp}\n{nonce}\n'.encode()+raw+b'\n',padding.PKCS1v15(),hashes.SHA256())
        except PaymentSignatureError:raise
        except Exception as exc:
            raise PaymentSignatureError('Invalid WeChat platform signature') from exc

    def verify_notification(self,headers,raw:bytes,now_ts:int|None=None)->tuple[str,dict]:
        self._verify_provider_message(headers,raw,now_ts=now_ts)
        try:
            outer=json.loads(raw)
            resource=outer['resource']
            if resource['algorithm']!='AEAD_AES_256_GCM':raise ValueError('algorithm')
            ct=base64.b64decode(resource['ciphertext'],validate=True)
            plain=AESGCM(self.cfg.wechat_api_v3_key.encode()).decrypt(
                resource['nonce'].encode(),ct,resource.get('associated_data','').encode())
            event_id=outer['id']
            if not isinstance(event_id,str) or not (1<=len(event_id)<=128):
                raise ValueError('invalid event id')
            content=json.loads(plain)
            return event_id,content
        except Exception as exc:
            raise PaymentSignatureError('Invalid or undecipherable callback resource') from exc
