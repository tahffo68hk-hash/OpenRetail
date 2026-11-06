"""OpenRetail V2 self-hosted single-store service.

Staging/pilot-capable transactional core, not an approved live unattended store.
Physical door control and unverified guest access fail closed. External money is
allowed only with separately configured WeChat Native merchant credentials.
"""
import hashlib
import sys
import base64
from datetime import datetime, timezone
import io
import qrcode
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI,Header,HTTPException,Depends,UploadFile,File,Query,Request,Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
import httpx

from .config import Settings
from .database import Database
from .security import digest,random_token,password_verify
from .wechat import WeChatNative,PaymentSignatureError
from .adapters import HomeAssistantAdapter,ERPNextReader,IntegrationError
from .importer import parse_catalog,write_catalog,ImportErrorDetail

ROOT=Path(__file__).resolve().parent.parent

def now()->int:return int(time.time())
def abort(status:int,message:str):raise HTTPException(status_code=status,detail=message)
def asdict(row):return dict(row) if row is not None else None

class Line(BaseModel):
    product_id:int=Field(gt=0)
    quantity:int=Field(ge=1,le=30)

class NewOrder(BaseModel):
    request_id:str=Field(min_length=8,max_length=128)
    lines:list[Line]=Field(min_length=1,max_length=40)

class ProductInput(BaseModel):
    barcode:str=Field(min_length=1,max_length=64)
    name:str=Field(min_length=1,max_length=120)
    price_cents:int=Field(ge=1,le=100_000_000)
    stock:int=Field(ge=0,le=1_000_000)
    active:bool=True
class ProductEdit(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    price_cents:int=Field(ge=1,le=100_000_000)

class ModeInput(BaseModel):mode:str
class FakePayment(BaseModel):order_id:str
class MockNotify(BaseModel):
    order_id:str=Field(min_length=32,max_length=32)
    event_id:str=Field(min_length=1,max_length=128)
    amount_cents:int|None=Field(default=None,ge=1)
class Login(BaseModel):password:str=Field(min_length=1,max_length=256)
class RedeemInvite(BaseModel):invite:str=Field(min_length=24,max_length=128)
class FrigateMessage(BaseModel):
    type:str
    after:dict|None=None
    before:dict|None=None
class StockChange(BaseModel):
    quantity_delta:int=Field(ge=-100_000,le=100_000)
    reason:str=Field(min_length=4,max_length=120)
class HelpInput(BaseModel):
    message:str=Field(min_length=2,max_length=400)
    order_id:str|None=Field(default=None,max_length=64)
class HelpStatus(BaseModel):
    status:str


def create_app(settings:Settings|None=None)->FastAPI:
    cfg=settings or Settings()
    cfg.validate()
    if getattr(cfg,'demo_secrets_generated',False):
        print('OpenRetail demo: ephemeral ADMIN_KEY for this process only (not written to disk). '
              'Run scripts/init_env.py to persist secrets. ADMIN_KEY='+cfg.admin_key, file=sys.stderr)
    db=Database(cfg.db_path)
    db.init(demo=cfg.demo)
    ha=HomeAssistantAdapter(cfg)
    wechat=WeChatNative(cfg)
    app=FastAPI(title='OpenRetail 无人零售自建系统',version='2.1.0',
                description='Production-oriented staged implementation. Door unlock prohibited.',
                docs_url='/docs' if cfg.demo else None,redoc_url=None,openapi_url='/openapi.json' if cfg.demo else None)
    app.state.db=db
    app.state.config=cfg
    app.state.ha=ha
    app.state.wechat=wechat

    @app.middleware('http')
    async def security_headers(request:Request,call_next):
        # Refuse browser cross-origin state-changing requests (same-origin UI only).
        origin=request.headers.get('origin','')
        if origin and request.method not in ('GET','HEAD','OPTIONS'):
            from urllib.parse import urlparse
            o=urlparse(origin)
            host=request.headers.get('host','')
            if o.netloc!=host or o.scheme not in ('https','http'):
                return Response('Forbidden origin',status_code=403)
        res=await call_next(request)
        res.headers['X-Content-Type-Options']='nosniff'
        res.headers['X-Frame-Options']='DENY'
        res.headers['Referrer-Policy']='no-referrer'
        res.headers['Permissions-Policy']='geolocation=(), microphone=(), camera=(self)'
        res.headers['Content-Security-Policy']=("default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if request.url.path.startswith('/api/'):
            res.headers['Cache-Control']='no-store'
        if cfg.trusted_proxy_tls:
            res.headers['Strict-Transport-Security']='max-age=31536000'
        return res

    def admin(request:Request,x_admin_key:str|None=Header(default=None),x_csrf_token:str|None=Header(default=None)):
        # API key compatibility strictly for local demo; pilot requires operator login.
        if cfg.demo and x_admin_key and hmac.compare_digest(x_admin_key,cfg.admin_key):
            return 'demo-admin-key'
        token=request.cookies.get('or_admin_session','')
        if not token:abort(401,'请先登录管理员账号')
        with db.connect() as c:
            row=c.execute('SELECT csrf_hash,expires_at FROM admin_sessions WHERE token_hash=?',
                          (digest(token),)).fetchone()
        if not row or row['expires_at']<=now():abort(401,'管理会话失效，请重新登录')
        if request.method not in ('GET','HEAD'):
            if not x_csrf_token or not hmac.compare_digest(digest(x_csrf_token),row['csrf_hash']):
                abort(403,'缺少或错误的 CSRF 校验')
        return 'operator'

    def integrator(x_integration_key:str|None=Header(default=None)):
        if not x_integration_key or not hmac.compare_digest(x_integration_key,cfg.integration_key):
            abort(401,'集成密钥无效')

    def guest(authorization:str|None=Header(default=None)):
        if not authorization or not authorization.startswith('Bearer '):abort(401,'请先获取访客会话')
        with db.connect() as c:
            row=c.execute('SELECT id,expires_at FROM guest_sessions WHERE token_hash=?',
                          (digest(authorization[7:]),)).fetchone()
        if not row or row['expires_at']<=now():abort(401,'访客会话已失效')
        return row['id']

    def payment_facts(c,order_id,status):
        pay=c.execute('SELECT provider,verified FROM payments WHERE order_id=?',(order_id,)).fetchone()
        verified=int(pay['verified']) if pay else 0
        provider=pay['provider'] if pay else ''
        if status=='PAID' and provider=='MOCK_NOT_REAL_MONEY':kind='MOCK_NOT_REAL_MONEY'
        elif status=='PAID' and provider=='WECHAT_NATIVE' and verified==1:kind='WECHAT_NATIVE'
        elif status=='REFUNDED':kind='MOCK_REFUND' if provider=='MOCK_NOT_REAL_MONEY' else 'REFUNDED'
        elif status=='EXPIRED':kind='TIMEOUT_UNPAID'
        elif status=='CANCELLED':kind='CANCELLED_UNPAID'
        elif status in ('PENDING','PAYMENT_PENDING'):kind='UNPAID'
        else:kind='REVIEW'
        return {'payment_kind':kind,'verified':verified,'real_money':kind=='WECHAT_NATIVE' and verified==1}

    def row_order(c,order_id):
        row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
        if row is None:abort(404,'订单不存在')
        lines=[asdict(r) for r in c.execute(
            'SELECT product_id,barcode,name,unit_price_cents,quantity FROM order_lines WHERE order_id=?',
            (order_id,))]
        return {**asdict(row),'lines':lines,**payment_facts(c,order_id,row['status'])}

    def record_virtual_door(c,session_id,result,detail):
        c.execute('''INSERT INTO door_events(session_id,result,provider,detail,created_at)
                     VALUES(?,?,?,?,?)''',(session_id,result,'LOCAL_SIMULATOR',detail,now()))

    def entry_status(c,session_id):
        row=c.execute('SELECT expires_at FROM guest_sessions WHERE id=?',(session_id,)).fetchone()
        events=[asdict(r) for r in c.execute(
            '''SELECT id,result,provider,detail,created_at FROM door_events
               WHERE session_id=? ORDER BY id DESC LIMIT 20''',(session_id,))]
        return {'session_id':session_id,'expires_at':row['expires_at'] if row else None,
                'identity_verified':False,'door_authorized':False,'physical_door_opened':False,
                'virtual_only':True,'events':events}

    def order_owned(c,order_id,session_id):
        row=c.execute('SELECT * FROM orders WHERE id=? AND session_id=?',(order_id,session_id)).fetchone()
        if not row:abort(404,'订单不存在')
        return row

    def settle(c,order_id,provider,transaction_id,verified):
        row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
        if not row:abort(404,'订单不存在')
        if row['status']=='PAID':
            paid=c.execute('SELECT id,provider FROM payments WHERE order_id=?',(order_id,)).fetchone()
            if paid and paid['id']==transaction_id and paid['provider']==provider:return 'IDEMPOTENT'
            return 'CONFLICT_DIFFERENT_PAYMENT'
        if row['status']=='REFUNDED':return 'REFUNDED'
        if row['status'] not in ('PENDING','PAYMENT_PENDING'):
            c.execute("UPDATE orders SET status='PAYMENT_REVIEW' WHERE id=?",(order_id,))
            db.audit(c,'payment','LATE_PAYMENT_REVIEW',order_id)
            return 'REVIEW_REQUIRED'
        if row['status']=='PENDING' and row['expires_at']<=now():
            # This path should only occur after a verified external payment race.
            db.release(c,order_id,'LATE_PAYMENT_RELEASE')
            c.execute("UPDATE orders SET status='PAYMENT_REVIEW' WHERE id=?",(order_id,))
            return 'REVIEW_REQUIRED'
        items=c.execute('SELECT product_id,quantity FROM order_lines WHERE order_id=?',(order_id,)).fetchall()
        # Preflight all rows before applying any movement: a partial paid order
        # must never deduct just the first line.
        for item in items:
            p=c.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(item['product_id'],)).fetchone()
            if not p or min(p['stock'],p['reserved_stock'])<item['quantity']:
                c.execute("UPDATE orders SET status='PAYMENT_REVIEW' WHERE id=?",(order_id,))
                db.audit(c,'payment','STOCK_INVARIANT_REVIEW',order_id)
                return 'REVIEW_REQUIRED'
        for item in items:
            cur=c.execute('''UPDATE products SET stock=stock-?,reserved_stock=reserved_stock-?
                             WHERE id=? AND reserved_stock>=? AND stock>=?''',
                          (item['quantity'],item['quantity'],item['product_id'],item['quantity'],item['quantity']))
            if cur.rowcount!=1:raise RuntimeError('reservation changed during serialized transaction')
            db.movement(c,item['product_id'],-item['quantity'],-item['quantity'],'PAID_SALE',order_id)
        c.execute("UPDATE orders SET status='PAID',paid_at=? WHERE id=?",(now(),order_id))
        c.execute('INSERT INTO payments(id,order_id,provider,verified,created_at) VALUES(?,?,?,?,?)',
                  (transaction_id,order_id,provider,int(verified),now()))
        db.audit(c,'payment','ORDER_PAID',order_id)
        return 'PAID'

    def database_ready():
        try:
            with db.connect() as c:
                ok=c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        except (sqlite3.OperationalError,RuntimeError):
            abort(503,'数据库不可用')
        if not ok:abort(503,'数据库完整性检查失败')

    @app.get('/api/health')
    def health():
        database_ready()
        return {'status':'ok','mode':cfg.app_mode,'profile':cfg.profile,
                'real_payment':cfg.payment_provider!='disabled',
                'real_door':False,'unattended_ready':False}

    @app.get('/api/readiness')
    def readiness():
        database_ready()
        return {'status':'ready','db':True,'profile':cfg.profile,'staffed_checkout_ready':False,
                'unattended_approved':False}

    @app.get('/api/public/store')
    def store():
        with db.connect() as c:
            mode=c.execute("SELECT value FROM store_settings WHERE key='mode'").fetchone()['value']
        return {'name':'OpenRetail 自建超市','store_mode':mode,'demo':cfg.demo,
                'payment':'MOCK_ONLY' if cfg.demo else cfg.payment_provider.upper(),
                'door':'SIMULATED_ONLY','unattended_approved':False}

    @app.get('/api/products')
    def products():
        with db.tx() as c:
            db.expire(c,now())
            return [{**asdict(row),'available_stock':row['stock']-row['reserved_stock']}
                    for row in c.execute('SELECT * FROM products WHERE active=1 ORDER BY id')]

    @app.post('/api/entry')
    def entry():
        if not cfg.demo:abort(503,'正式访客核验未接入，当前禁止无人入店授权')
        token=random_token();sid=uuid4().hex;ts=now()
        with db.tx() as c:
            c.execute('INSERT INTO guest_sessions(id,token_hash,created_at,expires_at) VALUES(?,?,?,?)',
                      (sid,digest(token),ts,ts+7200))
            record_virtual_door(c,sid,'SESSION_ISSUED','NO PHYSICAL UNLOCK')
            db.audit(c,'visitor','DEMO_SESSION_CREATE',sid[:12])
        return {'guest_token':token,'session_id':sid,'expires_at':ts+7200,'identity_verified':False,
                'door_authorized':False,'physical_door_opened':False,'virtual_event':'SESSION_ISSUED'}

    def qr_image_data(value:str)->str:
        img=qrcode.make(value,box_size=7,border=3)
        buf=io.BytesIO();img.save(buf,format='PNG')
        return 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()

    @app.post('/api/admin/checkout-invite',dependencies=[Depends(admin)])
    def create_checkout_invite():
        # Staffed checkout token is NOT identity verification or door access.
        with db.tx() as c:
            mode=c.execute("SELECT value FROM store_settings WHERE key='mode'").fetchone()['value']
            if mode!='STAFFED':abort(409,'仅允许有人值守的试点结账')
            invite=random_token();ts=now()
            c.execute('INSERT INTO checkout_invites(invite_hash,created_at,expires_at) VALUES(?,?,?)',
                      (digest(invite),ts,ts+120))
            db.audit(c,'operator','STAFF_CHECKOUT_INVITE','expires_120s')
        base=cfg.public_base_url.rstrip('/') if not cfg.demo else 'http://127.0.0.1:8000'
        url=base+'/?invite='+invite
        return {'invite':invite,'checkout_url':url,'qr_data_uri':qr_image_data(url),
                'expires_at':ts+120,'identity_verified':False,
                'purpose':'STAFFED_CHECKOUT_ONLY','note':'只用于有人值守的结账，不是进店凭证'}

    @app.post('/api/entry/redeem')
    def redeem_checkout_invite(payload:RedeemInvite):
        if cfg.demo:abort(409,'演示模式请直接创建模拟访客会话')
        token=random_token();sid=uuid4().hex;ts=now()
        with db.tx() as c:
            mode=c.execute("SELECT value FROM store_settings WHERE key='mode'").fetchone()['value']
            if mode!='STAFFED':abort(409,'仅有人经营模式允许领取结账会话')
            cur=c.execute('UPDATE checkout_invites SET consumed_at=? WHERE invite_hash=? AND consumed_at IS NULL AND expires_at>?',
                          (ts,digest(payload.invite),ts))
            if cur.rowcount!=1:abort(401,'邀请码无效、过期或已使用')
            c.execute('INSERT INTO guest_sessions(id,token_hash,created_at,expires_at,verified_identity_hash) VALUES(?,?,?,?,?)',
                      (sid,digest(token),ts,ts+3600,None))
            record_virtual_door(c,sid,'CHECKOUT_SESSION','NOT A DOOR GRANT')
            db.audit(c,'visitor','STAFFED_CHECKOUT_CREATED',sid[:12])
        return {'guest_token':token,'session_id':sid,'expires_at':ts+3600,
                'identity_verified':False,'door_authorized':False,'physical_door_opened':False,
                'virtual_event':'CHECKOUT_SESSION'}

    @app.post('/api/door/open')
    def door_open(sid:str=Depends(guest)):
        if not cfg.demo:abort(503,'无已验证访客身份与现场门禁验收，禁止控制实物门锁')
        with db.tx() as c:
            mode=c.execute("SELECT value FROM store_settings WHERE key='mode'").fetchone()['value']
            if mode!='UNATTENDED':abort(409,'当前非无人值守演示模式')
            record_virtual_door(c,sid,'SIMULATED','NO PHYSICAL UNLOCK')
            db.audit(c,'visitor','DEMO_ENTRY_OPEN',sid[:12])
            status=entry_status(c,sid)
        return {'result':'SIMULATED','physical_door_opened':False,
                'note':'只有模拟事件；安全疏散不能依赖支付状态',**status}

    @app.get('/api/entry/status')
    def read_entry_status(sid:str=Depends(guest)):
        with db.connect() as c:
            return entry_status(c,sid)

    def optional_guest(authorization:str|None):
        if not authorization:return None
        if not authorization.startswith('Bearer '):abort(401,'访客会话无效')
        with db.connect() as c:
            row=c.execute('SELECT id,expires_at FROM guest_sessions WHERE token_hash=?',
                          (digest(authorization[7:]),)).fetchone()
        if not row or row['expires_at']<=now():abort(401,'访客会话已失效')
        return row['id']

    @app.post('/api/help',status_code=201)
    def ask_for_staff(payload:HelpInput,authorization:str|None=Header(default=None)):
        """In-store help request. Does not open a door and does not require payment."""
        message=payload.message.strip()
        if len(message)<2:abort(422,'请写一句需要店员协助的话')
        sid=optional_guest(authorization)
        ts=now()
        with db.tx() as c:
            order_id=None
            if payload.order_id:
                if not sid:abort(401,'关联订单需要当前会话')
                owned=c.execute('SELECT id FROM orders WHERE id=? AND session_id=?',(payload.order_id,sid)).fetchone()
                if not owned:abort(404,'订单不存在')
                order_id=payload.order_id
            cur=c.execute('''INSERT INTO help_requests(session_id,order_id,message,created_at,status)
                             VALUES(?,?,?,?,?)''',(sid,order_id,message,ts,'OPEN'))
            request_id=cur.lastrowid
            db.audit(c,'visitor','HELP_REQUEST',(sid or 'anonymous')[:12])
        return {'id':request_id,'created_at':ts,'session_recorded':sid is not None,'order_id':order_id,
                'physical_door_opened':False,'door_authorized':False,'payment_required_to_leave':False}

    @app.get('/api/orders')
    def my_orders(sid:str=Depends(guest)):
        with db.tx() as c:
            db.expire(c,now())
            ids=[r['id'] for r in c.execute(
                'SELECT id FROM orders WHERE session_id=? ORDER BY created_at DESC LIMIT 30',(sid,))]
            return [row_order(c,oid) for oid in ids]

    @app.post('/api/orders',status_code=201)
    def create_order(payload:NewOrder,sid:str=Depends(guest)):
        aggregate={}
        for x in payload.lines:aggregate[x.product_id]=aggregate.get(x.product_id,0)+x.quantity
        if any(q>30 for q in aggregate.values()):abort(422,'单种商品最多30件')
        fp=hashlib.sha256(json.dumps(sorted(aggregate.items()),separators=(',',':')).encode()).hexdigest()
        with db.tx() as c:
            db.expire(c,now())
            old=c.execute('SELECT * FROM orders WHERE session_id=? AND request_id=?',(sid,payload.request_id)).fetchone()
            if old:
                if old['fingerprint']!=fp:abort(409,'同一幂等键不能用于不同购物车')
                return row_order(c,old['id'])
            prepared=[];total=0
            for pid,q in sorted(aggregate.items()):
                p=c.execute('SELECT * FROM products WHERE id=? AND active=1',(pid,)).fetchone()
                if not p:abort(422,f'商品 {pid} 不存在或已下架')
                if p['stock']-p['reserved_stock']<q:abort(409,f'{p["name"]} 可售库存不足')
                prepared.append((p,q));total+=p['price_cents']*q
            if total<1:abort(422,'订单金额必须大于0')
            oid=uuid4().hex;ts=now()
            c.execute('''INSERT INTO orders(id,session_id,request_id,fingerprint,status,total_cents,created_at,expires_at)
                         VALUES(?,?,?,?,'PENDING',?,?,?)''',(oid,sid,payload.request_id,fp,total,ts,ts+900))
            for p,q in prepared:
                c.execute('INSERT INTO order_lines(order_id,product_id,barcode,name,unit_price_cents,quantity) VALUES(?,?,?,?,?,?)',
                          (oid,p['id'],p['barcode'],p['name'],p['price_cents'],q))
                cur=c.execute('UPDATE products SET reserved_stock=reserved_stock+? WHERE id=? AND stock-reserved_stock>=?',
                              (q,p['id'],q))
                if cur.rowcount!=1:abort(409,'库存并发预留失败')
                db.movement(c,p['id'],0,q,'ORDER_RESERVED',oid)
            db.audit(c,'visitor','ORDER_RESERVED',oid)
            return row_order(c,oid)

    @app.get('/api/orders/{order_id}')
    def order_detail(order_id:str,sid:str=Depends(guest)):
        with db.tx() as c:
            db.expire(c,now())
            order_owned(c,order_id,sid)
            return row_order(c,order_id)

    @app.post('/api/orders/{order_id}/cancel')
    def cancel_order(order_id:str,sid:str=Depends(guest)):
        with db.tx() as c:
            db.expire(c,now())
            o=order_owned(c,order_id,sid)
            if o['status']=='CANCELLED':return row_order(c,order_id)
            if o['status']!='PENDING':abort(409,'已进入支付流程或已付款，不能直接取消')
            db.release(c,order_id,'ORDER_CANCELLED')
            c.execute("UPDATE orders SET status='CANCELLED' WHERE id=?",(order_id,))
            db.audit(c,'visitor','ORDER_CANCELLED',order_id)
            return row_order(c,order_id)

    def mock_enabled():
        if not(cfg.demo and cfg.mock_payments):abort(403,'模拟支付仅允许演示模式，不会访问微信支付')

    def mock_body(**extra):
        # verified=0 and MOCK_NOT_REAL_MONEY are the durable marks that this is not money.
        return {'provider':'MOCK_NOT_REAL_MONEY','verified':0,'real_money':False,'remote_call':False,**extra}

    def reject_external_payment(row,payment=None):
        if payment and (payment['provider']!='MOCK_NOT_REAL_MONEY' or int(payment['verified'])!=0):
            abort(409,'拒绝把非模拟支付当作模拟单处理')
        ref=row['payment_reference'] or ''
        if row['status']=='PAYMENT_PENDING' and not ref.startswith('mock:'):
            abort(409,'外部或未确认的支付单不会由模拟通道处理')
        if ref and not ref.startswith('mock:'):
            abort(409,'外部支付单不会由模拟通道查询、关闭或退款')

    def mock_trade_state(row,payment):
        if row['status']=='PAID' and payment and payment['provider']=='MOCK_NOT_REAL_MONEY' and int(payment['verified'])==0:
            return 'SUCCESS'
        if row['status']=='REFUNDED':return 'REFUND'
        if row['status'] in ('CANCELLED','EXPIRED'):return 'CLOSED'
        if row['status'] in ('PENDING','PAYMENT_PENDING'):return 'NOTPAY'
        if row['status']=='PAYMENT_REVIEW':return 'REVIEW'
        return 'UNKNOWN'

    def load_payment(c,order_id):
        return c.execute('SELECT id,provider,verified FROM payments WHERE order_id=?',(order_id,)).fetchone()

    @app.post('/api/payments/mock-confirm')
    def mock_confirm(payload:FakePayment,sid:str=Depends(guest)):
        mock_enabled()
        with db.tx() as c:
            db.expire(c,now())
            row=order_owned(c,payload.order_id,sid)
            if row['status']=='EXPIRED':return {'id':row['id'],'status':'EXPIRED','reason':'已超时，请重新下单',**mock_body()}
            if row['status']=='PAID':return row_order(c,row['id'])
            if row['status']=='REFUNDED':abort(409,'模拟退款已完成，不能再次确认付款')
            if row['status']=='PAYMENT_PENDING' and not str(row['payment_reference'] or '').startswith('mock:'):
                abort(409,'订单在外部支付处理中，不能用模拟支付确认')
            if row['status'] not in ('PENDING','PAYMENT_PENDING'):abort(409,'订单状态不允许模拟支付')
            outcome=settle(c,row['id'],'MOCK_NOT_REAL_MONEY','mock_'+row['id'],False)
            if outcome!='PAID':abort(409,'模拟付款异常，需人工复核')
            return row_order(c,row['id'])

    @app.post('/api/orders/{order_id}/mock-checkout')
    def mock_checkout(order_id:str,sid:str=Depends(guest)):
        """Open a local sandbox checkout. No socket is opened."""
        mock_enabled()
        with db.tx() as c:
            db.expire(c,now())
            row=order_owned(c,order_id,sid)
            if row['status']=='EXPIRED':
                return mock_body(order_id=order_id,outcome='EXPIRED',trade_state='CLOSED',order_status='EXPIRED')
            if row['status']=='PAYMENT_PENDING' and str(row['payment_reference'] or '').startswith('mock:'):
                return mock_body(order_id=order_id,outcome='IDEMPOTENT',trade_state='NOTPAY',
                                 order_status='PAYMENT_PENDING',payment_reference=row['payment_reference'])
            if row['status']!='PENDING':abort(409,'订单状态不允许发起模拟收款')
            ref='mock:'+order_id
            cur=c.execute('''UPDATE orders SET status='PAYMENT_PENDING',payment_reference=?,expires_at=?
                             WHERE id=? AND status='PENDING' ''',(ref,now()+900,order_id))
            if cur.rowcount!=1:abort(409,'模拟收款状态已变化')
            db.audit(c,'payment','MOCK_CHECKOUT_STARTED',order_id)
            return mock_body(order_id=order_id,outcome='PAYMENT_PENDING',trade_state='NOTPAY',
                             order_status='PAYMENT_PENDING',payment_reference=ref)

    @app.get('/api/orders/{order_id}/mock-payment')
    def mock_query(order_id:str,sid:str=Depends(guest)):
        mock_enabled()
        with db.tx() as c:
            db.expire(c,now())
            row=order_owned(c,order_id,sid)
            payment=load_payment(c,order_id)
            reject_external_payment(row,payment)
            return mock_body(order_id=order_id,trade_state=mock_trade_state(row,payment),
                             order_status=row['status'],expires_at=row['expires_at'])

    @app.post('/api/payments/mock-notify')
    def mock_notify(payload:MockNotify,sid:str=Depends(guest)):
        """Idempotent local confirm. event_id replays do not move stock twice."""
        mock_enabled()
        with db.tx() as c:
            db.expire(c,now())
            order_owned(c,payload.order_id,sid)
            existing=c.execute('SELECT outcome FROM payment_notifications WHERE event_id=?',(payload.event_id,)).fetchone()
            row=c.execute('SELECT * FROM orders WHERE id=?',(payload.order_id,)).fetchone()
            if existing:
                return mock_body(code='SUCCESS',outcome='IDEMPOTENT',order_status=row['status'],event_id=payload.event_id)
            if payload.amount_cents is not None and payload.amount_cents!=row['total_cents']:
                abort(422,'支付金额与订单不一致')
            payment=load_payment(c,payload.order_id)
            reject_external_payment(row,payment)
            if row['status']=='EXPIRED':
                c.execute('''INSERT INTO payment_notifications(event_id,provider,order_id,outcome,received_at)
                             VALUES(?,?,?,?,?)''',(payload.event_id,'MOCK_NOT_REAL_MONEY',payload.order_id,'EXPIRED',now()))
                return mock_body(code='SUCCESS',outcome='EXPIRED',order_status='EXPIRED',event_id=payload.event_id)
            if row['status']=='REFUNDED':abort(409,'模拟退款已完成，不能再次确认付款')
            if row['status'] not in ('PENDING','PAYMENT_PENDING','PAID'):abort(409,'订单状态不允许模拟通知')
            outcome=settle(c,payload.order_id,'MOCK_NOT_REAL_MONEY','mock_'+payload.order_id,False)
            if outcome not in ('PAID','IDEMPOTENT'):abort(409,'模拟付款异常，需人工复核')
            c.execute('''INSERT INTO payment_notifications(event_id,provider,order_id,outcome,received_at)
                         VALUES(?,?,?,?,?)''',(payload.event_id,'MOCK_NOT_REAL_MONEY',payload.order_id,outcome,now()))
            paid=load_payment(c,payload.order_id)
            if not paid or paid['provider']!='MOCK_NOT_REAL_MONEY' or int(paid['verified'])!=0:
                raise RuntimeError('mock settlement lost its unverified marker')
            return mock_body(code='SUCCESS',outcome=outcome,order_status='PAID',event_id=payload.event_id)

    @app.post('/api/admin/orders/{order_id}/mock-close',dependencies=[Depends(admin)])
    def mock_close(order_id:str):
        mock_enabled()
        with db.tx() as c:
            row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
            if not row:abort(404,'订单不存在')
            if row['status'] in ('CANCELLED','EXPIRED'):
                return mock_body(order_id=order_id,outcome='IDEMPOTENT',trade_state='CLOSED',order_status=row['status'])
            if row['status']=='PAID':abort(409,'已模拟支付的订单不能关单，如需退回库存请使用模拟退款')
            if row['status']=='REFUNDED':abort(409,'订单已模拟退款')
            local_pending=row['status']=='PENDING' or (row['status']=='PAYMENT_PENDING' and str(row['payment_reference'] or '').startswith('mock:'))
            if not local_pending:abort(409,'外部支付单请使用微信查单关单，模拟关单不会访问微信')
            db.release(c,order_id,'MOCK_CLOSED')
            c.execute("UPDATE orders SET status='CANCELLED' WHERE id=? AND status IN ('PENDING','PAYMENT_PENDING')",(order_id,))
            db.audit(c,'operator','MOCK_CLOSED',order_id)
            return mock_body(order_id=order_id,outcome='CLOSED',trade_state='CLOSED',order_status='CANCELLED')

    @app.post('/api/admin/orders/{order_id}/reconcile-mock',dependencies=[Depends(admin)])
    def reconcile_mock(order_id:str):
        """Apply local timeout, then report sandbox state. Does not call WeChat."""
        mock_enabled()
        with db.tx() as c:
            expired=db.expire(c,now())
            row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
            if not row:abort(404,'订单不存在')
            payment=load_payment(c,order_id)
            reject_external_payment(row,payment)
            return mock_body(order_id=order_id,trade_state=mock_trade_state(row,payment),
                             order_status=row['status'],expired_last_check=expired)

    @app.post('/api/admin/orders/{order_id}/mock-refund',dependencies=[Depends(admin)])
    def mock_refund(order_id:str):
        """Restore SQLite stock for an unverified mock sale. No provider refund exists."""
        mock_enabled()
        with db.tx() as c:
            row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
            if not row:abort(404,'订单不存在')
            if row['status']=='REFUNDED':
                return mock_body(order_id=order_id,outcome='IDEMPOTENT',trade_state='REFUND',
                                 order_status='REFUNDED',stock_restored=False)
            if row['status']!='PAID':abort(409,'只有已模拟支付的订单可以退回库存')
            payment=load_payment(c,order_id)
            if not payment or payment['provider']!='MOCK_NOT_REAL_MONEY' or int(payment['verified'])!=0:
                abort(409,'拒绝退款：不是未核验的模拟支付，不会调用真实退款接口')
            items=c.execute('SELECT product_id,quantity FROM order_lines WHERE order_id=?',(order_id,)).fetchall()
            for item in items:
                product=c.execute('SELECT stock FROM products WHERE id=?',(item['product_id'],)).fetchone()
                if not product or product['stock']+item['quantity']>1_000_000:abort(409,'退回后库存超出上限')
            for item in items:
                cur=c.execute('UPDATE products SET stock=stock+? WHERE id=?',(item['quantity'],item['product_id']))
                if cur.rowcount!=1:raise RuntimeError('mock refund stock update failed')
                db.movement(c,item['product_id'],item['quantity'],0,'MOCK_REFUND_RESTORE',order_id)
            cur=c.execute("UPDATE orders SET status='REFUNDED' WHERE id=? AND status='PAID'",(order_id,))
            if cur.rowcount!=1:raise RuntimeError('mock refund lost the paid row')
            c.execute('INSERT INTO refunds(id,order_id,provider,amount_cents,created_at) VALUES(?,?,?,?,?)',
                      ('mock_refund_'+order_id,order_id,'MOCK_NOT_REAL_MONEY',row['total_cents'],now()))
            db.audit(c,'operator','MOCK_REFUND',order_id)
            return mock_body(order_id=order_id,outcome='REFUNDED',trade_state='REFUND',
                             order_status='REFUNDED',stock_restored=True)

    @app.post('/api/orders/{order_id}/wechat-native')
    def initiate_wechat(order_id:str,sid:str=Depends(guest)):
        if cfg.payment_provider!='wechat_native':abort(503,'微信商户收款未启用')
        with db.tx() as c:
            db.expire(c,now())
            o=order_owned(c,order_id,sid)
            if o['status'] not in ('PENDING','PAYMENT_PENDING'):abort(409,'订单状态不允许发起收款')
            if o['status']=='PAYMENT_PENDING' and o['payment_reference']:
                return {'order_id':order_id,'code_url':o['payment_reference'],
                        'qr_data_uri':qr_image_data(o['payment_reference']),'status':'PAYMENT_PENDING',
                        'note':'Native QR 适用于另一台设备扫码；手机内结账需进一步集成 H5/JSAPI'}
            # Mark first: on a network timeout the remote gateway MAY have created a charge.
            c.execute("UPDATE orders SET status='PAYMENT_PENDING',expires_at=? WHERE id=?",(now()+900,order_id))
        try:
            code=app.state.wechat.create_native(order_id,o['total_cents'])
        except (httpx.HTTPError,PaymentSignatureError,OSError,ValueError) as exc:
            # Never free stock on uncertainty; requires query/close reconciliation.
            with db.tx() as c:db.audit(c,'payment','INITIATE_UNCERTAIN',order_id)
            abort(502,'微信下单未确认，库存继续保留；请在后台进行交易查询/人工对账')
        with db.tx() as c:
            c.execute('UPDATE orders SET payment_reference=? WHERE id=?',(code,order_id))
            db.audit(c,'payment','WECHAT_NATIVE_CREATED',order_id)
        return {'order_id':order_id,'code_url':code,
                'qr_data_uri':qr_image_data(code),'status':'PAYMENT_PENDING',
                'note':'在另一台设备上展示二维码；付款完成需等待已验签回调'}

    @app.post('/api/payments/wechat-notify')
    async def wechat_notify(request:Request):
        if cfg.payment_provider!='wechat_native':abort(404,'支付服务未启用')
        raw=await request.body()
        if len(raw)>256_000:abort(413,'通知报文过大')
        try:event_id,event=app.state.wechat.verify_notification(request.headers,raw)
        except PaymentSignatureError:abort(401,'支付通知签名校验失败')
        if event.get('trade_state')!='SUCCESS' or event.get('trade_type')!='NATIVE':
            abort(422,'非成功的 Native 支付通知')
        if event.get('mchid')!=cfg.wechat_mchid or event.get('appid')!=cfg.wechat_appid:
            abort(422,'商户标识不符')
        oid=event.get('out_trade_no')
        txid=event.get('transaction_id')
        money=event.get('amount') or {}
        if not isinstance(oid,str) or not isinstance(txid,str) or len(txid)>128:
            abort(422,'订单或微信交易号缺失')
        if money.get('currency')!='CNY' or type(money.get('total')) is not int:
            abort(422,'支付币种或金额字段错误')
        with db.tx() as c:
            existing=c.execute('SELECT outcome FROM payment_notifications WHERE event_id=?',(event_id,)).fetchone()
            if existing:return {'code':'SUCCESS','message':'成功'}
            order=c.execute('SELECT id,total_cents FROM orders WHERE id=?',(oid,)).fetchone()
            if not order:abort(404,'回调订单不存在')
            if money['total']!=order['total_cents']:abort(422,'支付金额与订单不一致')
            outcome=settle(c,oid,'WECHAT_NATIVE',txid,True)
            c.execute('INSERT INTO payment_notifications(event_id,provider,order_id,outcome,received_at) VALUES(?,?,?,?,?)',
                      (event_id,'WECHAT_NATIVE',oid,outcome,now()))
            if outcome!='PAID' and outcome!='IDEMPOTENT':db.audit(c,'payment','PAYMENT_REVIEW',oid)
        return {'code':'SUCCESS','message':'成功'}

    @app.post('/api/admin/orders/{order_id}/reconcile-wechat',dependencies=[Depends(admin)])
    def reconcile_wechat(order_id:str):
        """Query provider; release reserved inventory ONLY after confirmed CLOSED.
        A signed SUCCESS result recovers lost webhook notifications.
        """
        if cfg.payment_provider!='wechat_native':abort(503,'未启用微信商户支付')
        with db.connect() as c:
            local=c.execute('SELECT id,status,total_cents,expires_at FROM orders WHERE id=?',(order_id,)).fetchone()
            if not local:abort(404,'订单不存在')
        try:
            remote=app.state.wechat.query_trade(order_id)
            state=remote.get('trade_state')
            if state=='NOTPAY' and local['expires_at']<now():
                app.state.wechat.close_trade(order_id)
                remote=app.state.wechat.query_trade(order_id)
                state=remote.get('trade_state')
        except (httpx.HTTPError,OSError,PaymentSignatureError,ValueError):
            abort(502,'商户查询或关单未确认，订单仍保留待核对；请不要手动释放库存')
        if remote.get('mchid')!=cfg.wechat_mchid:
            abort(422,'商户号不一致，拒绝结算')
        if state=='SUCCESS':
            amount=remote.get('amount') or {}
            if (remote.get('appid')!=cfg.wechat_appid or amount.get('currency')!='CNY'
                or type(amount.get('total')) is not int or amount['total']!=local['total_cents']
                or not remote.get('transaction_id')):
                abort(422,'支付金额、币种或商户应用不一致')
            with db.tx() as c:
                outcome=settle(c,order_id,'WECHAT_NATIVE',remote['transaction_id'],True)
                db.audit(c,'operator','PAYMENT_RECONCILE',order_id+':'+outcome)
            return {'order_id':order_id,'remote':'SUCCESS','outcome':outcome}
        if state=='CLOSED':
            with db.tx() as c:
                current=c.execute('SELECT status FROM orders WHERE id=?',(order_id,)).fetchone()
                if current['status'] in ('PENDING','PAYMENT_PENDING'):
                    db.release(c,order_id,'PROVIDER_CONFIRMED_CLOSED')
                    c.execute("UPDATE orders SET status='CANCELLED' WHERE id=?",(order_id,))
                    db.audit(c,'operator','PAYMENT_CLOSED',order_id)
            return {'order_id':order_id,'remote':'CLOSED','outcome':'RELEASED_OR_ALREADY_FINAL'}
        return {'order_id':order_id,'remote':state,'outcome':'WAITING_OR_MANUAL_REVIEW'}

    @app.post('/api/admin/login')
    def login(payload:Login,request:Request,response:Response):
        fingerprint=digest(cfg.app_secret+str(request.client.host if request.client else 'unknown'))
        bad=False;blocked=False;token='';csrf='';ts=now()
        with db.tx() as c:
            attempt=c.execute('SELECT failed,blocked_until FROM login_attempts WHERE fingerprint=?',(fingerprint,)).fetchone()
            if attempt and attempt['blocked_until']>ts:
                blocked=True
            else:
                accepted=password_verify(payload.password,cfg.admin_password_hash) if cfg.admin_password_hash else False
                if cfg.demo and hmac.compare_digest(payload.password,cfg.admin_key):accepted=True
                if not accepted:
                    failed=(attempt['failed'] if attempt and (not attempt['blocked_until'] or attempt['blocked_until']>ts) else 0)+1
                    block=ts+900 if failed>=5 else 0
                    c.execute('''INSERT INTO login_attempts(fingerprint,failed,blocked_until) VALUES(?,?,?)
                                 ON CONFLICT(fingerprint) DO UPDATE SET failed=excluded.failed,blocked_until=excluded.blocked_until''',
                              (fingerprint,failed,block))
                    bad=True
                else:
                    c.execute('DELETE FROM login_attempts WHERE fingerprint=?',(fingerprint,))
                    token=random_token();csrf=random_token()
                    c.execute('INSERT INTO admin_sessions(token_hash,csrf_hash,created_at,expires_at) VALUES(?,?,?,?)',
                              (digest(token),digest(csrf),ts,ts+8*3600))
                    db.audit(c,'operator','LOGIN','operator')
        if blocked:abort(429,'尝试次数过多，请稍后重试')
        if bad:abort(401,'用户名或密码错误')
        response.set_cookie('or_admin_session',token,httponly=True,secure=not cfg.demo,samesite='strict',
                            path='/api/admin',max_age=8*3600)
        return {'ok':True,'csrf':csrf,'expires_at':ts+8*3600}

    @app.post('/api/admin/logout',dependencies=[Depends(admin)])
    def logout(request:Request,response:Response):
        token=request.cookies.get('or_admin_session','')
        with db.tx() as c:
            c.execute('DELETE FROM admin_sessions WHERE token_hash=?',(digest(token),))
        response.delete_cookie('or_admin_session',path='/api/admin')
        return {'ok':True}

    @app.get('/api/admin/overview',dependencies=[Depends(admin)])
    def overview():
        with db.tx() as c:
            expired=db.expire(c,now())
            mode=c.execute("SELECT value FROM store_settings WHERE key='mode'").fetchone()['value']
            count=c.execute('SELECT COUNT(*) n FROM products WHERE active=1').fetchone()['n']
            orders=c.execute("SELECT COUNT(*) n,COALESCE(SUM(total_cents),0) revenue FROM orders WHERE status='PAID'").fetchone()
            real=c.execute('''SELECT COALESCE(SUM(o.total_cents),0) n FROM orders o
                              JOIN payments p ON p.order_id=o.id WHERE p.verified=1 AND o.status='PAID' ''').fetchone()['n']
            pending=c.execute("SELECT COUNT(*) n FROM orders WHERE status='PAYMENT_PENDING'").fetchone()['n']
            review=c.execute("SELECT COUNT(*) n FROM orders WHERE status='PAYMENT_REVIEW'").fetchone()['n']
            entry=c.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
            incidents=c.execute('SELECT COUNT(*) n FROM incidents').fetchone()['n']
            day=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
            day_start=int(day.timestamp())
            today_orders=c.execute('SELECT COUNT(*) n FROM orders WHERE created_at>=?',(day_start,)).fetchone()['n']
            today_paid=c.execute("SELECT COALESCE(SUM(total_cents),0) n FROM orders WHERE status='PAID' AND paid_at>=?",(day_start,)).fetchone()['n']
            today_real=c.execute('''SELECT COALESCE(SUM(o.total_cents),0) n FROM orders o
                JOIN payments p ON p.order_id=o.id
                WHERE o.status='PAID' AND p.verified=1 AND o.paid_at>=?''',(day_start,)).fetchone()['n']
            help_open=c.execute("SELECT COUNT(*) n FROM help_requests WHERE status='OPEN'").fetchone()['n']
            help_ack=c.execute("SELECT COUNT(*) n FROM help_requests WHERE status='ACKNOWLEDGED'").fetchone()['n']
            help_resolved=c.execute("SELECT COUNT(*) n FROM help_requests WHERE status='RESOLVED'").fetchone()['n']
            threshold_row=c.execute("SELECT value FROM store_settings WHERE key='low_stock_threshold'").fetchone()
            threshold=int(threshold_row['value']) if threshold_row else 5
            low_stock=[{**asdict(row),'available_stock':row['stock']-row['reserved_stock']}
                       for row in c.execute('''SELECT id,barcode,name,stock,reserved_stock FROM products
                            WHERE active=1 AND stock<=? ORDER BY stock,id''',(threshold,))]
        return {'mode':mode,'products':count,'paid_orders':orders['n'],'simulated_revenue_cents':orders['revenue']-real,
                'verified_revenue_cents':real,'payment_pending':pending,'payment_review':review,
                'expired_last_check':expired,'door_events':entry,'incidents':incidents,
                'home_assistant':ha.status(),'real_payments_enabled':cfg.payment_provider!='disabled',
                'real_door_enabled':False,
                'today_order_count':today_orders,
                'today_simulated_revenue_cents':today_paid-today_real,
                'today_verified_revenue_cents':today_real,
                'today_basis':'UTC calendar day',
                'help_needs_attention':help_open+help_ack,
                'help_open':help_open,'help_acknowledged':help_ack,'help_resolved':help_resolved,
                'low_stock_threshold':threshold,
                'low_stock_basis':'products.stock on-hand book quantity; reserved_stock is still held for unpaid orders',
                'low_stock':low_stock}

    @app.put('/api/admin/mode',dependencies=[Depends(admin)])
    def update_mode(payload:ModeInput):
        if payload.mode not in ('STAFFED','UNATTENDED'):abort(422,'模式必须是STAFFED或UNATTENDED')
        if not cfg.demo and payload.mode=='UNATTENDED':abort(409,'缺少实机门禁与消防安全验收，禁止进入无人经营模式')
        with db.tx() as c:
            c.execute("UPDATE store_settings SET value=? WHERE key='mode'",(payload.mode,))
            db.audit(c,'operator','MODE_SET',payload.mode)
        return {'mode':payload.mode,'physical_door_affected':False}

    @app.get('/api/admin/products',dependencies=[Depends(admin)])
    def admin_products():
        with db.connect() as c:return [asdict(r) for r in c.execute('SELECT * FROM products ORDER BY id')]

    @app.post('/api/admin/products',dependencies=[Depends(admin)])
    def create_product(payload:ProductInput):
        """Add one SQLite catalog row. Duplicate barcodes are not an overwrite."""
        with db.tx() as c:
            db.expire(c,now())
            if c.execute('SELECT id FROM products WHERE barcode=?',(payload.barcode,)).fetchone():
                abort(409,'条码已存在。请只改名称售价，或做单品库存调整；不要整表覆盖。')
            cur=c.execute('INSERT INTO products(barcode,name,price_cents,stock,active) VALUES(?,?,?,?,?)',
                          (payload.barcode,payload.name,payload.price_cents,payload.stock,int(payload.active)))
            db.movement(c,cur.lastrowid,payload.stock,0,'OPENING_BALANCE',payload.barcode)
            db.audit(c,'operator','PRODUCT_CREATED',payload.barcode)
            row=c.execute('SELECT id,barcode,name,price_cents,stock,reserved_stock FROM products WHERE id=?',(cur.lastrowid,)).fetchone()
        return {**asdict(row),'created':True,'system_of_record':'sqlite'}

    @app.patch('/api/admin/products/{product_id}',dependencies=[Depends(admin)])
    def edit_product(product_id:int,payload:ProductEdit):
        """Name and price only. Stock and reservations stay untouched."""
        with db.tx() as c:
            current=c.execute('SELECT id,barcode,stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
            if not current:abort(404,'商品不存在')
            c.execute('UPDATE products SET name=?,price_cents=? WHERE id=?',
                      (payload.name,payload.price_cents,product_id))
            db.audit(c,'operator','PRODUCT_EDIT',current['barcode'])
            after=c.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product_id,)).fetchone()
            if after['stock']!=current['stock'] or after['reserved_stock']!=current['reserved_stock']:
                raise RuntimeError('name/price edit changed stock')
        return {'id':product_id,'barcode':current['barcode'],'name':payload.name,'price_cents':payload.price_cents,
                'stock':current['stock'],'reserved_stock':current['reserved_stock'],'stock_changed':False}

    @app.post('/api/admin/products/{product_id}/adjust-stock',dependencies=[Depends(admin)])
    def adjust_stock(product_id:int,payload:StockChange):
        if payload.quantity_delta==0:abort(422,'调整数量不能为 0')
        with db.tx() as c:
            p=c.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
            if not p:abort(404,'商品不存在')
            new=p['stock']+payload.quantity_delta
            # On-hand floor is the quantity already reserved for unpaid orders, and never below zero.
            if new<0 or new<p['reserved_stock']:
                abort(409,'库存调整会低于可售底线或侵占未结算预留')
            c.execute('UPDATE products SET stock=? WHERE id=?',(new,product_id))
            db.movement(c,product_id,payload.quantity_delta,0,payload.reason,'MANUAL')
            db.audit(c,'operator','STOCK_ADJUST',f'{product_id}:{payload.quantity_delta}')
        return {'product_id':product_id,'stock':new,'reserved_stock':p['reserved_stock'],
                'reason':payload.reason,'system_of_record':'sqlite'}

    @app.post('/api/admin/import-products',dependencies=[Depends(admin)])
    async def import_products(file:UploadFile=File(...),dry_run:bool=Query(True)):
        if file.size and file.size>2_000_000:abort(413,'CSV文件过大')
        try:items=parse_catalog(await file.read(2_000_001))
        except ImportErrorDetail as exc:abort(422,str(exc))
        if dry_run:return {'dry_run':True,'count':len(items),'preview':items[:15],
                           'notice':'Manual snapshot. Production inventory source must be selected.'}
        with db.tx() as c:
            db.expire(c,now())
            # Stop unsafe CSV stock replacement when any order history exists.
            if c.execute('SELECT 1 FROM orders LIMIT 1').fetchone():
                abort(409,'已有订单记录；为保证库存账本一致，禁止全量 CSV 覆盖。请使用逐品补货调整。')
            for p in items:
                old=c.execute('SELECT id,stock FROM products WHERE barcode=?',(p['barcode'],)).fetchone()
                c.execute('''INSERT INTO products(barcode,name,price_cents,stock) VALUES(?,?,?,?)
                             ON CONFLICT(barcode) DO UPDATE SET name=excluded.name,price_cents=excluded.price_cents,
                             stock=excluded.stock''',(p['barcode'],p['name'],p['price_cents'],p['stock']))
                product=c.execute('SELECT id FROM products WHERE barcode=?',(p['barcode'],)).fetchone()
                db.movement(c,product['id'],p['stock']-(old['stock'] if old else 0),0,'CSV_INITIAL_IMPORT',p['barcode'])
            db.audit(c,'operator','CSV_INITIAL_IMPORT',f'count={len(items)}')
        return {'dry_run':False,'count':len(items),'notice':'单次初始导入完成；禁止后续覆盖订单账本',
                'system_of_record':'sqlite'}

    @app.get('/api/admin/export-products',dependencies=[Depends(admin)])
    def export_products():
        with db.connect() as c:
            rows=c.execute('SELECT barcode,name,price_cents,stock FROM products ORDER BY id').fetchall()
        body=write_catalog(rows)
        return Response(body,media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':'attachment; filename="openretail-products.csv"'})

    @app.get('/api/admin/orders',dependencies=[Depends(admin)])
    def admin_orders():
        with db.connect() as c:
            return [asdict(x) for x in c.execute('''SELECT o.id,o.status,o.total_cents,o.created_at,o.paid_at,o.expires_at,
                    (SELECT provider FROM payments WHERE order_id=o.id ORDER BY created_at DESC LIMIT 1) provider,
                    (SELECT verified FROM payments WHERE order_id=o.id ORDER BY created_at DESC LIMIT 1) verified
                    FROM orders o ORDER BY o.created_at DESC LIMIT 100''')]

    @app.get('/api/admin/help-requests',dependencies=[Depends(admin)])
    def admin_help_requests():
        with db.connect() as c:
            rows=[asdict(x) for x in c.execute('''SELECT id,session_id,order_id,message,created_at,status
                                                  FROM help_requests ORDER BY id DESC LIMIT 50''')]
        return {'physical_door_opened':False,'payment_required_to_leave':False,'requests':rows}

    @app.post('/api/admin/help-requests/{request_id}/status',dependencies=[Depends(admin)])
    def update_help_status(request_id:int,payload:HelpStatus):
        """Mark a help request seen or done. Never opens a door or collects payment."""
        if payload.status not in ('ACKNOWLEDGED','RESOLVED'):
            abort(422,'状态只能是 ACKNOWLEDGED 或 RESOLVED')
        with db.tx() as c:
            row=c.execute('SELECT id,status FROM help_requests WHERE id=?',(request_id,)).fetchone()
            if not row:abort(404,'求助不存在')
            if row['status']=='RESOLVED' and payload.status!='RESOLVED':
                abort(409,'已处理的求助不能改回未处理')
            outcome='IDEMPOTENT' if row['status']==payload.status else payload.status
            if outcome!='IDEMPOTENT':
                c.execute('UPDATE help_requests SET status=? WHERE id=?',(payload.status,request_id))
                db.audit(c,'operator','HELP_'+payload.status,str(request_id))
        return {'id':request_id,'status':payload.status,'outcome':outcome,
                'physical_door_opened':False,'door_authorized':False,'payment_required_to_leave':False}

    @app.get('/api/admin/stock-movements',dependencies=[Depends(admin)])
    def stock_movements(limit:int=Query(default=100,ge=1,le=500)):
        with db.connect() as c:
            return [asdict(x) for x in c.execute('SELECT * FROM stock_movements ORDER BY id DESC LIMIT ?', (limit,))]

    @app.get('/api/admin/inventory-ledger',dependencies=[Depends(admin)])
    def inventory_ledger(limit:int=Query(default=200,ge=1,le=500)):
        """SQLite is the inventory system of record. Balances must match movement sums."""
        with db.connect() as c:
            products=[]
            balanced=True
            for row in c.execute('''SELECT p.id product_id,p.barcode,p.name,p.stock,p.reserved_stock,
                    COALESCE(SUM(m.stock_delta),0) ledger_stock,
                    COALESCE(SUM(m.reserved_delta),0) ledger_reserved
                    FROM products p LEFT JOIN stock_movements m ON m.product_id=p.id
                    GROUP BY p.id ORDER BY p.id'''):
                item=asdict(row)
                item['balanced']=item['stock']==item['ledger_stock'] and item['reserved_stock']==item['ledger_reserved']
                balanced=balanced and item['balanced']
                products.append(item)
            movements=[asdict(x) for x in c.execute('''SELECT id,product_id,stock_delta,reserved_delta,reason,reference,created_at,
                    SUM(stock_delta) OVER (PARTITION BY product_id ORDER BY id) stock_after,
                    SUM(reserved_delta) OVER (PARTITION BY product_id ORDER BY id) reserved_after
                    FROM stock_movements ORDER BY id DESC LIMIT ?''',(limit,))]
        return {'system_of_record':'sqlite','balanced':balanced,'products':products,'movements':movements}

    @app.get('/api/admin/events',dependencies=[Depends(admin)])
    def admin_events():
        with db.connect() as c:
            return {'physical_door_opened':False,
                    'door':[asdict(x) for x in c.execute('SELECT id,result,provider,detail,created_at FROM door_events ORDER BY id DESC LIMIT 40')],
                    'frigate':[asdict(x) for x in c.execute('SELECT * FROM incidents ORDER BY id DESC LIMIT 40')],
                    'audit':[asdict(x) for x in c.execute('SELECT actor,action,detail,created_at FROM audit_events ORDER BY id DESC LIMIT 40')]}

    @app.post('/api/integrations/frigate-event',dependencies=[Depends(integrator)])
    def frigate_event(payload:FrigateMessage):
        if payload.type not in ('new','update','end'):abort(422,'unsupported Frigate event type')
        ev=payload.after or payload.before or {}
        event_id=str(ev.get('id',''))[:128]
        label=str(ev.get('label',''))[:64]
        camera=str(ev.get('camera',''))[:120]
        if not event_id or not camera:abort(422,'missing Frigate event id/camera')
        if label!='person':return {'stored':False,'reason':'Only person events are included'}
        key=f'{event_id}:{payload.type}'
        with db.tx() as c:
            cur=c.execute('INSERT OR IGNORE INTO incidents(event_key,source,label,camera,event_type,created_at) VALUES(?,?,?,?,?,?)',
                          (key,'FRIGATE',label,camera,payload.type,now()))
            if cur.rowcount:db.audit(c,'frigate','PERSON_EVENT',key[:100])
        return {'stored':cur.rowcount>0,'theft_detected':False}

    @app.get('/api/admin/erpnext-preview',dependencies=[Depends(admin)])
    def erpnext_preview():
        try:return ERPNextReader(cfg).preview()
        except IntegrationError as exc:abort(503,str(exc))

    app.mount('/assets',StaticFiles(directory=str(ROOT/'web')),name='assets')
    @app.get('/')
    def index():return FileResponse(ROOT/'web/index.html')
    return app

def __getattr__(name):
    # Importing create_app must not boot a database or demand secrets.
    # uvicorn openretail.main:app still receives a real app on first access.
    if name=='app':
        instance=create_app()
        globals()['app']=instance
        return instance
    raise AttributeError(name)
