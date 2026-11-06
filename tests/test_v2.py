"""V2 security, immutable settlement, V1 data migration, cryptographic mock gateway."""
from __future__ import annotations
import base64
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from openretail.config import Settings
from openretail.main import create_app
from openretail.security import password_hash
from openretail.wechat import WeChatNative
from conftest import visitor


def test_admin_cookie_csrf_and_logout(client):
    assert client.post('/api/admin/login',json={'password':'bad'}).status_code==401
    login=client.post('/api/admin/login',json={'password':'A'*40})
    assert login.status_code==200
    csrf=login.json()['csrf']
    assert 'HttpOnly' in login.headers['set-cookie']
    assert client.get('/api/admin/overview').status_code==200
    assert client.put('/api/admin/mode',json={'mode':'UNATTENDED'}).status_code==403
    assert client.put('/api/admin/mode',headers={'X-CSRF-Token':'bad'},json={'mode':'UNATTENDED'}).status_code==403
    assert client.put('/api/admin/mode',headers={'X-CSRF-Token':csrf},json={'mode':'UNATTENDED'}).status_code==200
    assert client.post('/api/admin/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    assert client.get('/api/admin/overview').status_code==401


def test_login_lockout_persists_on_failed_attempt(client):
    for _ in range(5):assert client.post('/api/admin/login',json={'password':'bad'}).status_code==401
    assert client.post('/api/admin/login',json={'password':'A'*40}).status_code==429
    with client.app.state.db.connect() as c:
        assert c.execute('SELECT failed FROM login_attempts').fetchone()['failed']==5


def test_reservation_expiry_cancel_movement(client,admin_header):
    a=visitor(client);p=client.get('/api/products').json()[0]
    order=client.post('/api/orders',headers=a,json={'request_id':'my-cancel-test-1',
        'lines':[{'product_id':p['id'],'quantity':4}]}).json()
    assert client.get('/api/products').json()[0]['reserved_stock']==4
    x=client.post('/api/orders/'+order['id']+'/cancel',headers=a)
    assert x.status_code==200 and x.json()['status']=='CANCELLED'
    assert client.post('/api/orders/'+order['id']+'/cancel',headers=a).json()['status']=='CANCELLED'
    assert client.post('/api/payments/mock-confirm',headers=a,json={'order_id':order['id']}).status_code==409
    assert client.get('/api/products').json()[0]['available_stock']==p['stock']
    second=client.post('/api/orders',headers=a,json={'request_id':'my-expire-test-2',
        'lines':[{'product_id':p['id'],'quantity':3}]}).json()
    with client.app.state.db.tx() as c:c.execute('UPDATE orders SET expires_at=0 WHERE id=?',(second['id'],))
    assert client.get('/api/products').json()[0]['reserved_stock']==0
    assert client.get('/api/orders/'+second['id'],headers=a).json()['status']=='EXPIRED'
    moves=client.get('/api/admin/stock-movements',headers=admin_header).json()
    assert {x['reason'] for x in moves}>={'ORDER_RESERVED','ORDER_CANCELLED','ORDER_EXPIRED'}


def test_reservation_prevents_oversell_during_admin_update(client,admin_header):
    a=visitor(client)
    p=client.get('/api/products').json()[0]
    assert client.post('/api/admin/products/'+str(p['id'])+'/adjust-stock',headers=admin_header,
        json={'quantity_delta':2-p['stock'],'reason':'count correction'}).status_code==200
    o=client.post('/api/orders',headers=a,json={'request_id':'last-stock-test-1',
        'lines':[{'product_id':p['id'],'quantity':2}]}).json()
    edited=client.patch('/api/admin/products/'+str(p['id']),headers=admin_header,
        json={'name':p['name'],'price_cents':p['price_cents']})
    assert edited.status_code==200 and edited.json()['stock']==2 and edited.json()['stock_changed'] is False
    assert client.post('/api/admin/products/'+str(p['id'])+'/adjust-stock',headers=admin_header,
        json={'quantity_delta':-1,'reason':'physical damage'}).status_code==409
    assert client.post('/api/payments/mock-confirm',headers=a,json={'order_id':o['id']}).json()['status']=='PAID'
    assert client.get('/api/products').json()[0]['stock']==0


def test_csv_import_blocked_after_first_order(client,admin_header):
    a=visitor(client);p=client.get('/api/products').json()[0]
    client.post('/api/orders',headers=a,json={'request_id':'csv-after-orders-test-1',
        'lines':[{'product_id':p['id'],'quantity':1}]})
    body={'file':('catalog.csv','barcode,name,price,stock\nABC123,test,3.00,5\n','text/csv')}
    assert client.post('/api/admin/import-products?dry_run=true',headers=admin_header,files=body).status_code==200
    assert client.post('/api/admin/import-products?dry_run=false',headers=admin_header,files=body).status_code==409


def test_non_demo_has_no_unauthenticated_guest_and_no_real_unlock(tmp_path):
    cfg=Settings(db_path=str(tmp_path/'pilot.sqlite3'),app_mode='pilot',
        admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
        admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
        trusted_proxy_tls=True,public_base_url='https://pilot.example.invalid',mock_payments=False)
    with TestClient(create_app(cfg),base_url='https://pilot.example.invalid') as c:
        assert c.post('/api/entry').status_code==503
        assert c.post('/api/door/open').status_code==401
        assert c.put('/api/admin/mode',headers={'X-Admin-Key':'A'*40},json={'mode':'UNATTENDED'}).status_code==401
        login=c.post('/api/admin/login',json={'password':'StrongOperatorPassphrase2026'})
        assert login.status_code==200
        csrf={'X-CSRF-Token':login.json()['csrf']}
        invite=c.post('/api/admin/checkout-invite',headers=csrf).json()
        assert invite['checkout_url'].startswith('https://pilot.example.invalid/')
        assert invite['qr_data_uri'].startswith('data:image/png;base64,')
        guest=c.post('/api/entry/redeem',json={'invite':invite['invite']})
        assert guest.status_code==200
        assert guest.json()['identity_verified'] is False
        assert c.post('/api/entry/redeem',json={'invite':invite['invite']}).status_code==401
        token={'Authorization':'Bearer '+guest.json()['guest_token']}
        entry=c.get('/api/entry/status',headers=token).json()
        assert entry['physical_door_opened'] is False and entry['door_authorized'] is False
        assert entry['events'][0]['result']=='CHECKOUT_SESSION'
        assert entry['events'][0]['detail']=='NOT A DOOR GRANT'
        assert c.post('/api/door/open',headers=token).status_code==503
        assert c.put('/api/admin/mode',headers=csrf,json={'mode':'UNATTENDED'}).status_code==409
        assert c.post('/api/payments/mock-confirm',headers=token,json={'order_id':'anything'}).status_code==403


def create_keys(tmp_path):
    merchant_priv=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    platform_priv=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    merchant_file=tmp_path/'merchant.pem';pubfile=tmp_path/'wechat-public.pem'
    merchant_file.write_bytes(merchant_priv.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    pubfile.write_bytes(platform_priv.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    return str(merchant_file),str(pubfile),platform_priv


def provider_signature(private,raw:bytes):
    ts=str(int(time.time()));nonce='provider-test-nonce'
    message=f'{ts}\n{nonce}\n'.encode()+raw+b'\n'
    sig=base64.b64encode(private.sign(message,padding.PKCS1v15(),hashes.SHA256())).decode()
    return {'Wechatpay-Serial':'PUB_KEY_ID_TEST01','Wechatpay-Timestamp':ts,
            'Wechatpay-Nonce':nonce,'Wechatpay-Signature':sig}


def test_signed_wechat_native_flow_and_reconciliation(tmp_path):
    merchant,pubfile,platform_key=create_keys(tmp_path)
    cfg=Settings(db_path=str(tmp_path/'pay.sqlite3'),app_mode='pilot',mock_payments=False,
        admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
        admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
        trusted_proxy_tls=True,public_base_url='https://pilot.example.invalid',
        payment_provider='wechat_native',wechat_mchid='1900000001',wechat_appid='wxTESTID',
        wechat_serial='MCHSERIAL',wechat_private_key_file=merchant,
        wechat_platform_pubkey_file=pubfile,wechat_platform_serial='PUB_KEY_ID_TEST01',
        wechat_api_v3_key='Z'*32,wechat_notify_url='https://pilot.example.invalid/api/payments/wechat-notify')
    calls=[]
    def fake_wechat(req):
        calls.append(req)
        assert req.headers['Authorization'].startswith('WECHATPAY2-SHA256-RSA2048')
        if req.method=='POST' and req.url.path.endswith('/native'):
            payload=json.loads(req.content)
            assert payload['amount']['total']==500
            raw=json.dumps({'code_url':'weixin://wxpay/bizpayurl?pr=TEST'}).encode()
            return httpx.Response(200,content=raw,headers=provider_signature(platform_key,raw))
        if req.method=='GET':
            oid=req.url.path.split('/')[-1]
            raw=json.dumps({'out_trade_no':oid,'mchid':'1900000001','appid':'wxTESTID',
                'trade_state':'SUCCESS','transaction_id':'wx_transaction_1',
                'amount':{'total':500,'currency':'CNY'}}).encode()
            return httpx.Response(200,content=raw,headers=provider_signature(platform_key,raw))
        raise AssertionError('Unexpected merchant call')

    with TestClient(create_app(cfg),base_url='https://pilot.example.invalid') as c:
        c.app.state.wechat=WeChatNative(cfg,client=httpx.Client(transport=httpx.MockTransport(fake_wechat)))
        assert c.get('/docs').status_code==404
        assert c.get('/api/health').json()['real_payment'] is True
        assert c.post('/api/entry').status_code==503
        login=c.post('/api/admin/login',json={'password':'StrongOperatorPassphrase2026'}).json()
        csrf={'X-CSRF-Token':login['csrf']}
        assert c.post('/api/admin/products',headers=csrf,json={'barcode':'ABC100','name':'测试商品',
            'price_cents':500,'stock':2,'active':True}).status_code==200
        invite=c.post('/api/admin/checkout-invite',headers=csrf).json()
        guest=c.post('/api/entry/redeem',json={'invite':invite['invite']}).json()
        auth={'Authorization':'Bearer '+guest['guest_token']}
        p=c.get('/api/products').json()[0]
        order=c.post('/api/orders',headers=auth,json={'request_id':'pilot-test-order-001',
            'lines':[{'product_id':p['id'],'quantity':1}]}).json()
        assert c.get('/api/products').json()[0]['reserved_stock']==1
        qr=c.post('/api/orders/'+order['id']+'/wechat-native',headers=auth)
        assert qr.status_code==200
        assert qr.json()['qr_data_uri'].startswith('data:image/png;base64,')
        assert c.post('/api/orders/'+order['id']+'/cancel',headers=auth).status_code==409
        # Signature invalid -> no settlement; content not trusted by frontend.
        event={'out_trade_no':order['id'],'mchid':cfg.wechat_mchid,'appid':cfg.wechat_appid,
               'trade_state':'SUCCESS','trade_type':'NATIVE','transaction_id':'wx_transaction_1',
               'amount':{'total':500,'currency':'CNY'}}
        nonce=b'123456789012';ad=b'wechat'
        encrypted=AESGCM(cfg.wechat_api_v3_key.encode()).encrypt(nonce,json.dumps(event).encode(),ad)
        body=json.dumps({'id':'notification-001','resource':{'algorithm':'AEAD_AES_256_GCM',
            'nonce':nonce.decode(),'associated_data':ad.decode(),
            'ciphertext':base64.b64encode(encrypted).decode()}}).encode()
        assert c.post('/api/payments/wechat-notify',content=body,headers={
            **provider_signature(platform_key,body),'Wechatpay-Signature':'not-valid'}).status_code==401
        assert c.get('/api/products').json()[0]['stock']==2
        assert c.post('/api/payments/wechat-notify',content=body,
                      headers=provider_signature(platform_key,body)).status_code==200
        assert c.post('/api/payments/wechat-notify',content=body,
                      headers=provider_signature(platform_key,body)).status_code==200
        assert c.get('/api/products').json()[0]['stock']==1
        assert c.get('/api/products').json()[0]['reserved_stock']==0
        assert c.get('/api/orders/'+order['id'],headers=auth).json()['status']=='PAID'
        assert c.get('/api/admin/overview').json()['verified_revenue_cents']==500
        reconciled=c.post('/api/admin/orders/'+order['id']+'/reconcile-wechat',headers=csrf)
        assert reconciled.json()['outcome']=='IDEMPOTENT'
        assert len(calls)==2


def test_invalid_pilot_config(tmp_path):
    from pytest import raises
    with raises(RuntimeError,match='TLS'):
        create_app(Settings(db_path=str(tmp_path/'invalid.db'),app_mode='pilot',
            admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
            admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
            mock_payments=False,public_base_url='https://pilot.example.invalid',trusted_proxy_tls=False))


def test_migrate_v1_paid_order_preserves_ledger(tmp_path):
    """A V1 order with FKs must survive the CHECK constraint rebuild."""
    import sqlite3
    from openretail.database import Database
    legacy=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(legacy) as c:
        c.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE products(id INTEGER PRIMARY KEY AUTOINCREMENT,barcode TEXT UNIQUE NOT NULL,name TEXT NOT NULL,
          price_cents INTEGER NOT NULL CHECK(price_cents>=0),stock INTEGER NOT NULL CHECK(stock>=0),
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)));
        CREATE TABLE guest_sessions(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL);
        CREATE TABLE orders(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES guest_sessions(id),
          request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN('PENDING','PAID','EXPIRED')),
          total_cents INTEGER NOT NULL CHECK(total_cents>=0),created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
          paid_at INTEGER,UNIQUE(session_id,request_id));
        CREATE TABLE order_lines(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL REFERENCES orders(id),
          product_id INTEGER NOT NULL REFERENCES products(id),barcode TEXT NOT NULL,name TEXT NOT NULL,
          unit_price_cents INTEGER NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>0));
        CREATE TABLE payments(id TEXT PRIMARY KEY,order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
          provider TEXT NOT NULL,verified INTEGER NOT NULL,created_at INTEGER NOT NULL);
        ''')
        c.execute("INSERT INTO products(barcode,name,price_cents,stock) VALUES('CODE','Legacy',100,5)")
        c.execute("INSERT INTO guest_sessions VALUES('s','hashed',1,9999999999)")
        c.execute("INSERT INTO orders VALUES('o','s','req','finger','PAID',100,1,9999999999,2)")
        c.execute("INSERT INTO order_lines(order_id,product_id,barcode,name,unit_price_cents,quantity) VALUES('o',1,'CODE','Legacy',100,1)")
        c.execute("INSERT INTO payments VALUES('mock_o','o','MOCK',0,2)")
    db=Database(str(legacy));db.init(demo=False)
    with db.connect() as c:
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert c.execute("SELECT status FROM orders WHERE id='o'").fetchone()['status']=='PAID'
        assert c.execute("SELECT order_id FROM order_lines").fetchone()['order_id']=='o'
        assert c.execute('SELECT stock,reserved_stock FROM products').fetchone()['reserved_stock']==0
    # Idempotent when starting again.
    db.init(demo=False)
    with db.connect() as c:assert c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1


def test_wechat_unpaid_expired_close_releases_only_after_provider_closed(tmp_path):
    cfg=Settings(db_path=str(tmp_path/'closed.sqlite3'),app_mode='pilot',
        admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
        admin_password_hash=password_hash('StrongOperatorPassphrase2026'),
        trusted_proxy_tls=True,public_base_url='https://pilot.example.invalid',
        mock_payments=False,payment_provider='disabled')
    with TestClient(create_app(cfg),base_url='https://pilot.example.invalid') as c:
        login=c.post('/api/admin/login',json={'password':'StrongOperatorPassphrase2026'}).json()
        csrf={'X-CSRF-Token':login['csrf']}
        c.post('/api/admin/products',headers=csrf,json={'barcode':'A001','name':'Test',
            'price_cents':250,'stock':2,'active':True})
        invite=c.post('/api/admin/checkout-invite',headers=csrf).json()
        guest=c.post('/api/entry/redeem',json={'invite':invite['invite']}).json()
        auth={'Authorization':'Bearer '+guest['guest_token']}
        p=c.get('/api/products').json()[0]
        oid=c.post('/api/orders',headers=auth,json={'request_id':'close-me-order-1',
            'lines':[{'product_id':p['id'],'quantity':2}]}).json()['id']
        with c.app.state.db.tx() as db:
            db.execute("UPDATE orders SET status='PAYMENT_PENDING',expires_at=1 WHERE id=?",(oid,))
        class Gateway:
            calls=[]
            def query_trade(self,oid):
                self.calls.append('query')
                return {'trade_state':'CLOSED' if 'close' in self.calls else 'NOTPAY',
                        'mchid':'1900000001','out_trade_no':oid}
            def close_trade(self,oid):self.calls.append('close')
        gateway=Gateway()
        c.app.state.wechat=gateway
        c.app.state.config.payment_provider if False else None
        # The configured provider switch also must be activated; no real merchant call is made.
        from dataclasses import replace
        object.__setattr__(c.app.state.config,'payment_provider','wechat_native')
        object.__setattr__(c.app.state.config,'wechat_mchid','1900000001')
        r=c.post('/api/admin/orders/'+oid+'/reconcile-wechat',headers=csrf)
        assert r.status_code==200 and r.json()['remote']=='CLOSED'
        assert gateway.calls==['query','close','query']
        assert c.get('/api/orders/'+oid,headers=auth).json()['status']=='CANCELLED'
        assert c.get('/api/products').json()[0]['reserved_stock']==0
        assert c.get('/api/products').json()[0]['stock']==2
