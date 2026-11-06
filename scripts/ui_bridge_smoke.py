from pathlib import Path
import sys
import shutil
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from urllib.parse import urlsplit
import os
import base64
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
from openretail.config import Settings
from openretail.main import create_app
from dotenv import dotenv_values
root=ROOT
t=tempfile.TemporaryDirectory(prefix='openretail-ui-')
cfg=Settings(db_path=str(Path(t.name)/'smoke.sqlite3'),admin_key='A'*40,integration_key='I'*40,app_secret='S'*40,
             ha_enabled=False,live_door_enabled=False,ha_token='',ha_door_state_entity='')
with TestClient(create_app(cfg)) as backend,sync_playwright() as pw:
 b=pw.chromium.launch(headless=True,executable_path=(shutil.which('chromium') or shutil.which('google-chrome') or pw.chromium.executable_path),args=['--no-sandbox'])
 p=b.new_page(viewport={'width':390,'height':844})
 errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
 def call_backend(path, method, headers,body):
  res=backend.request(method,path,headers=headers or {},content=body if body else None)
  ctype=res.headers.get('content-type','')
  if 'sqlite' in ctype:
   return {'status':res.status_code,'data':None,'binary':base64.b64encode(res.content).decode()}
  return {'status':res.status_code,'data':res.json() if ctype.startswith('application/json') else res.text}
 p.expose_function('__callBackend',call_backend)
 html=(root/'web/index.html').read_text()
 html=html.replace('<link rel="stylesheet" href="/assets/styles.css">','<style>'+ (root/'web/styles.css').read_text()+'</style>')
 html=html.replace('<script src="/assets/app.js" defer></script>','')
 p.set_content(html,wait_until='domcontentloaded')
 p.evaluate('''() => {
  const mem=new Map();Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:k=>mem.get(k)||null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)}});
  window.fetch=async (path,opts={})=>{const x=await window.__callBackend(path,opts.method||'GET',opts.headers||{},opts.body||null);
    const bytes=x.binary?Uint8Array.from(atob(x.binary),c=>c.charCodeAt(0)):null;
    return {ok:x.status>=200&&x.status<300,status:x.status,json:async()=>x.data,text:async()=>typeof x.data==='string'?x.data:'',blob:async()=>new Blob(bytes?[bytes]:[])}}
 }''')
 p.add_script_tag(content=(root/'web/app.js').read_text())
 p.wait_for_function("document.querySelectorAll('.product-card').length===8",timeout=10000)
 print('products:',p.locator('.product-card').count(),'width:',p.evaluate('document.documentElement.scrollWidth'))
 p.evaluate("() => { const b=document.querySelector('#entry-btn'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#entry-result').textContent.includes('访客会话创建成功（未进行身份核验）')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='DEMO_SESSION_CREATE'").fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM door_events WHERE result='SESSION_ISSUED'").fetchone()['n']==1
 p.locator('#barcode').fill('   ')
 p.locator('#scan-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#scan-hint').textContent.includes('请输入商品条码') && document.querySelector('#barcode').value==='' && document.activeElement===document.querySelector('#barcode')")
 assert p.locator('#cart-total').inner_text()=='¥0.00'
 p.locator('#barcode').fill('0000000000000')
 p.locator('#scan-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#scan-hint').textContent.includes('未找到条码') && document.querySelector('#barcode').value==='' && document.activeElement===document.querySelector('#barcode')")
 assert p.locator('#cart-total').inner_text()=='¥0.00'
 p.locator('#barcode').fill('6901234567892')
 p.locator('#scan-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#scan-hint').textContent.includes('已添加') && document.querySelector('#scan-hint').textContent.includes('瓶装饮用水') && document.querySelector('#barcode').value==='' && document.activeElement===document.querySelector('#barcode') && document.querySelector('#cart-total').textContent==='¥2.00'")
 p.locator('#checkout-btn').click()
 p.wait_for_function("document.querySelector('#payment-result').textContent.includes('订单') && document.querySelector('#payment-result').textContent.includes('预留至') && document.querySelector('#payment-result').textContent.includes('Asia/Shanghai') && document.querySelector('#payment-result').textContent.includes('¥2.00')")
 held=p.locator('#receipt-id').input_value()
 p.evaluate('() => reloadSessionView()')
 p.wait_for_function("document.querySelector('#cart-total').textContent==='¥2.00' && document.querySelector('#payment-result').textContent.includes('预留至') && document.querySelector('#receipt-id').value==="+repr(held))
 print('order:',p.locator('#payment-result').inner_text())
 p.wait_for_function("document.querySelector('#cart-total').textContent==='¥2.00'")
 p.locator('#cart [data-add]').click()
 p.wait_for_function("document.querySelector('#cart-total').textContent==='¥4.00'")
 p.locator('#cart [data-minus]').click()
 p.wait_for_function("document.querySelector('#cart-total').textContent==='¥2.00'")
 p.locator('#pay-btn').click()
 p.wait_for_function("document.querySelector('#payment-result').textContent.includes('模拟支付成功')")
 paid_id=p.locator('#receipt-id').input_value()
 p.evaluate('() => reloadSessionView()')
 p.wait_for_function("document.querySelector('#receipt-id').value==="+repr(paid_id)+" && document.querySelector('#receipt').textContent.includes('非真实资金') && document.querySelector('#receipt').textContent.includes('MOCK_NOT_REAL_MONEY') && document.querySelector('#cart-total').textContent==='¥0.00'")
 print('paid:',p.locator('#payment-result').inner_text())
 p.wait_for_function("document.querySelector('#my-orders').textContent.includes('模拟支付成功')")
 p.wait_for_function("document.querySelector('#my-orders').textContent.includes('real_money=false')")
 p.wait_for_function("(()=>{const id=document.querySelector('#receipt-id').value;const card=document.querySelector('#receipt').textContent;const mine=document.querySelector('#my-orders').textContent;return id.length>=16&&card.includes('非真实资金')&&card.includes('MOCK_NOT_REAL_MONEY')&&card.includes('瓶装饮用水')&&mine.includes(id)&&mine.includes('¥2.00')&&mine.includes('非真实资金')})()")
 p.wait_for_function("document.querySelector('#entry-status').textContent.includes('实体门未打开')")
 assert 'refund' not in p.locator('#panel-shop').inner_text().lower()
 assert '退款' not in p.locator('#panel-shop').inner_text()
 p.locator('#help-message').fill('   ')
 p.locator('#help-btn').click()
 p.wait_for_function("document.querySelector('#help-result').textContent.includes('请写一句需要店员协助的话') && !document.querySelector('#help-result').textContent.includes('已通知店员') && !document.body.textContent.includes('已呼叫店员') && document.activeElement===document.querySelector('#help-message')")
 p.locator('#help-message').fill('请到货架帮忙')
 p.evaluate("() => { const b=document.querySelector('#help-btn'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#help-result').textContent.includes('已通知店员') && document.querySelector('#help-result').textContent.includes('不会打开实体门') && document.querySelector('#help-result').textContent.includes('离店不需要付款')")
 p.locator('[data-panel="admin"]').click()
 p.locator('#admin-key').fill('A'*40)
 p.locator('#admin-login').click()
 p.wait_for_function("!document.querySelector('#admin-body').hidden")
 p.wait_for_function("document.querySelector('#holding-list').textContent.includes('没有占用库存的未付款订单')")
 p.wait_for_function("document.querySelector('#holding-attention').textContent.includes('未付款占用 0 笔')")
 p.locator('#jump-holding').click()
 p.wait_for_function("document.querySelector('#holding-list').textContent.includes('没有占用库存的未付款订单')")
 print('admin:',p.locator('#m-orders').inner_text(),'real:',p.locator('#m-real').inner_text(),'errors:',errors)
 p.wait_for_function("document.querySelector('#help-list').textContent.includes('请到货架帮忙') && (document.querySelector('#help-list').textContent.match(/请到货架帮忙/g)||[]).length===1 && document.querySelector('[data-find-order]')")
 p.locator('[data-find-order]').click()
 p.wait_for_function("document.querySelector('#order-lookup-status').textContent.includes('已找到订单') && document.querySelector('#order-lookup-status').textContent.includes('非真实资金') && document.querySelector('#help-list').textContent.includes('请到货架帮忙') && document.querySelector('#help-list').textContent.includes('待处理')")
 p.locator('#jump-help').click()
 p.wait_for_function("document.querySelector('#help-status').value==='attention' && document.querySelector('#help-list').textContent.includes('请到货架帮忙') && document.querySelector('#help-list').textContent.includes('待处理') && !document.querySelector('#help-list').textContent.includes('已确认')")
 p.wait_for_function("document.querySelector('#door-event-list').textContent.includes('SESSION_ISSUED')")
 p.wait_for_function("(()=>{const t=document.querySelector('#event-list').textContent;return !t.includes('盗窃')&&!t.includes('偷盗')&&!t.includes('未付款离店')})()")
 p.wait_for_function("document.querySelector('#door-lock-note').textContent.includes('physical_door_opened=false')")
 p.wait_for_function("document.querySelector('#door-contact').textContent.includes('门磁未配置') && document.querySelector('#door-contact').textContent.includes('physical_door_opened=false') && !document.querySelector('#door-contact').textContent.includes('已开锁')")
 p.locator('#invite-copy').click()
 p.wait_for_function("document.querySelector('#toast').textContent.includes('还没有邀请码')")
 p.evaluate("() => { const b=document.querySelector('#issue-invite'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#invite-result').textContent.includes('120') && document.querySelector('#invite-result').textContent.includes('identity_verified=false') && document.querySelector('#invite-result').textContent.includes('door_authorized=false') && document.querySelector('#invite-result').textContent.includes('physical_door_opened=false') && document.querySelector('#invite-result').textContent.includes('不能作为进门凭证') && document.querySelector('#invite-qr').hidden===false")
 p.locator('#invite-copy').click()
 p.wait_for_function("(()=>{const t=document.querySelector('#toast').textContent;const code=document.querySelector('#invite-code').value;return (t.includes('邀请码已复制')||t.includes('邀请码已选中，可手动复制'))&&code.length>=24&&!code.includes(' ')&&document.querySelector('#invite-result').textContent.includes(code)})()")
 with backend.app.state.db.connect() as conn:
  assert conn.execute('SELECT COUNT(*) n FROM checkout_invites').fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_CREATED'").fetchone()['n']==1
 p.evaluate("() => { const b=document.querySelector('[data-help-status=\"ACKNOWLEDGED\"]'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#help-list').textContent.includes('已确认') && document.querySelector('#toast').textContent.includes('已确认求助，门未打开')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_ACKNOWLEDGED'").fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_RESOLVED'").fetchone()['n']==0
 p.locator('[data-help-status="RESOLVED"]').click()
 p.wait_for_function("document.querySelector('#toast').textContent.includes('求助已处理，门未打开')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_ACKNOWLEDGED'").fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='HELP_RESOLVED'").fetchone()['n']==1
 p.wait_for_function("document.querySelector('#ledger-balance').textContent.includes('一致')")
 p.wait_for_function("document.querySelector('#m-sales').textContent.includes('¥')")
 assert p.locator('#m-real').inner_text()=='¥0.00'
 p.wait_for_function("document.querySelector('#order-table').textContent.includes('非真实资金') && document.querySelector('#order-table').textContent.includes('¥2.00') && document.querySelector('#order-date').value.length===10")
 p.locator('#order-lookup').fill(p.locator('#order-table td').first.get_attribute('title'))
 p.locator('#order-filter button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#order-lookup-status').textContent.includes('已找到订单') && document.querySelector('#order-lookup-status').textContent.includes('非真实资金') && document.querySelector('#order-table').textContent.includes('¥2.00')")
 p.locator('#orders-export').click()
 p.wait_for_function("document.querySelector('#order-export-status').textContent.includes('已导出该订单') && document.querySelector('#order-export-status').textContent.includes('非真实资金')")
 p.wait_for_function("document.querySelector('#today-summary').textContent.includes('模拟销售额（非真实资金）') && document.querySelector('#today-summary').textContent.includes('已验签金额（真实资金） ¥0.00') && document.querySelector('#today-summary').textContent.includes('¥2.00') && document.querySelector('#today-summary').textContent.includes('Asia/Shanghai')")
 p.wait_for_function("document.querySelector('#store-timezone').value==='Asia/Shanghai'")
 p.wait_for_function("document.querySelector('#help-attention').textContent.includes('待处理求助')")
 p.evaluate("() => { const b=document.querySelector('[data-mock-refund]'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#toast').textContent.includes('模拟退款已回补库存，不是微信退款') && document.querySelector('#order-table').textContent.includes('模拟退回') && !document.querySelector('#toast').textContent.includes('这次没有增加库存')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='MOCK_REFUND_RESTORE'").fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM orders WHERE status='REFUNDED'").fetchone()['n']==1
  assert conn.execute('SELECT COALESCE(SUM(verified),0) n FROM payments').fetchone()['n']==0
 with backend.app.state.db.connect() as conn:
  products_before=conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']
 p.locator('#product-form input[name="barcode"]').fill('   ')
 p.locator('#product-form input[name="name"]').fill('不应新增')
 p.locator('#product-form input[name="price"]').fill('1.00')
 p.locator('#product-form input[name="stock"]').fill('1')
 p.locator('#product-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='请输入商品条码' && document.querySelector('#toast').textContent.includes('请输入商品条码') && !document.querySelector('#product-status').textContent.includes('找不到条码')")
 p.locator('#edit-form input[name="barcode"]').fill('  ')
 p.locator('#edit-form input[name="name"]').fill('不应改名')
 p.locator('#edit-form input[name="price"]').fill('2.00')
 p.locator('#edit-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='请输入商品条码'")
 p.locator('#adjust-form input[name="barcode"]').fill('\t')
 p.locator('#adjust-form input[name="delta"]').fill('1')
 p.locator('#adjust-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='请输入商品条码'")
 with backend.app.state.db.connect() as conn:
  assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==products_before
  water_name=conn.execute("SELECT name,price_cents FROM products WHERE barcode='6901234567892'").fetchone()
 p.locator('#product-form input[name="barcode"]').fill('6900000099991')
 p.locator('#product-form input[name="name"]').fill('   ')
 p.locator('#product-form input[name="price"]').fill('3.50')
 p.locator('#product-form input[name="stock"]').fill('4')
 p.locator('#product-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='请输入商品名称' && document.querySelector('#toast').textContent.includes('请输入商品名称')")
 p.locator('#edit-form input[name="barcode"]').fill('6901234567892')
 p.locator('#edit-form input[name="name"]').fill('  ')
 p.locator('#edit-form input[name="price"]').fill('9.90')
 p.locator('#edit-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='请输入商品名称'")
 with backend.app.state.db.connect() as conn:
  assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==products_before
  same=conn.execute("SELECT name,price_cents FROM products WHERE barcode='6901234567892'").fetchone()
  assert same['name']==water_name['name'] and same['price_cents']==water_name['price_cents']
 p.locator('#product-form input[name="barcode"]').fill('6900000099991')
 p.locator('#product-form input[name="name"]').fill('不应因售价新增')
 p.locator('#product-form input[name="price"]').evaluate("el => { el.value='0'; }")
 p.locator('#product-form input[name="stock"]').fill('4')
 p.locator('#product-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='请输入有效售价' && document.querySelector('#toast').textContent.includes('请输入有效售价')")
 p.locator('#edit-form input[name="barcode"]').fill('6901234567892')
 p.locator('#edit-form input[name="name"]').fill('瓶装饮用水 550ml')
 p.locator('#edit-form input[name="price"]').evaluate("el => { el.value=''; }")
 p.locator('#edit-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='请输入有效售价'")
 with backend.app.state.db.connect() as conn:
  assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==products_before
  same=conn.execute("SELECT name,price_cents FROM products WHERE barcode='6901234567892'").fetchone()
  assert same['name']==water_name['name'] and same['price_cents']==water_name['price_cents']
 p.locator('#product-form input[name="barcode"]').fill('6900000099991')
 p.locator('#product-form input[name="name"]').fill('烟雾测试商品')
 p.locator('#product-form input[name="price"]').fill('3.50')
 p.locator('#product-form input[name="stock"]').fill('4')
 p.evaluate("() => { const b=document.querySelector('#product-form button[type=\"submit\"]'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#product-status').textContent.includes('已新增')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']==products_before+1
  assert conn.execute("SELECT stock,name FROM products WHERE barcode='6900000099991'").fetchone()['stock']==4
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_CREATED' AND detail='6900000099991'").fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM stock_movements WHERE reason='OPENING_BALANCE' AND reference='6900000099991'").fetchone()['n']==1
 p.wait_for_function("document.querySelector('#low-stock-list').textContent.includes('6900000099991') && document.querySelector('#low-stock-list').textContent.includes('预留')")
 p.locator('[data-find-product="6900000099991"]').click()
 p.wait_for_function("document.querySelector('#catalog-query').value==='6900000099991' && document.querySelector('#admin-catalog').textContent.includes('6900000099991') && document.querySelector('#admin-catalog').textContent.includes('预留')")
 p.locator('#low-stock-threshold').evaluate("el => { el.value='0'; }")
 p.locator('#store-settings-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#store-settings-status').textContent==='请输入有效低库存阈值' && document.querySelector('#toast').textContent.includes('请输入有效低库存阈值') && !document.querySelector('#toast').textContent.includes('门店设置已保存')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute("SELECT value FROM store_settings WHERE key='low_stock_threshold'").fetchone()['value']=='5'
  assert conn.execute("SELECT value FROM store_settings WHERE key='store_timezone'").fetchone()['value']=='Asia/Shanghai'
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STORE_SETTINGS'").fetchone()['n']==0
 p.locator('#low-stock-threshold').fill('3')
 p.locator('#store-settings-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#store-settings-status').textContent.includes('已保存') && document.querySelector('#store-settings-status').textContent.includes('阈值 3')")
 p.wait_for_function("!document.querySelector('#low-stock-list').textContent.includes('6900000099991')")
 p.locator('#edit-form input[name="barcode"]').fill('6900000099991')
 p.locator('#edit-form input[name="name"]').fill('烟雾测试商品改名')
 p.locator('#edit-form input[name="price"]').fill('4.20')
 p.evaluate("() => { const b=document.querySelector('#edit-form button[type=\"submit\"]'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#product-status').textContent.includes('库存仍为 4')")
 with backend.app.state.db.connect() as conn:
  edited=conn.execute("SELECT name,price_cents,stock,reserved_stock FROM products WHERE barcode='6900000099991'").fetchone()
  assert edited['name']=='烟雾测试商品改名' and edited['price_cents']==420 and edited['stock']==4 and edited['reserved_stock']==0
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_EDIT' AND detail='6900000099991'").fetchone()['n']==1
 p.locator('#adjust-form input[name="barcode"]').fill('6900000099991')
 p.locator('#adjust-form input[name="delta"]').evaluate("el => { el.value='0'; }")
 p.locator('#adjust-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#product-status').textContent==='调整数量不能为 0' && document.querySelector('#toast').textContent.includes('调整数量不能为 0')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute("SELECT stock FROM products WHERE barcode='6900000099991'").fetchone()['stock']==4
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST' AND detail LIKE '6900000099991:%'").fetchone()['n']==0
 p.locator('#adjust-form input[name="barcode"]').fill('6900000099991')
 p.locator('#adjust-form input[name="delta"]').fill('2')
 p.locator('#adjust-form select[name="reason"]').select_option('到货入库')
 p.evaluate("() => { const b=document.querySelector('#adjust-form button[type=\"submit\"]'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#product-status').textContent.includes('库存已调整为 6')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute("SELECT stock FROM products WHERE barcode='6900000099991'").fetchone()['stock']==6
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='STOCK_ADJUST' AND detail LIKE '6900000099991:%'").fetchone()['n']==1
 p.evaluate("() => { const b=document.querySelector('[data-listing-barcode=\"6900000099991\"]'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#product-status').textContent.includes('已下架') && document.querySelector('#product-status').textContent.includes('库存仍为 6')")
 with backend.app.state.db.connect() as conn:
  listed=conn.execute("SELECT stock,reserved_stock,active FROM products WHERE barcode='6900000099991'").fetchone()
  assert listed['stock']==6 and listed['reserved_stock']==0 and listed['active']==0
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_UNLISTED' AND detail='6900000099991'").fetchone()['n']==1
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='PRODUCT_LISTED' AND detail='6900000099991'").fetchone()['n']==0
 p.wait_for_function("document.querySelector('#audit-list').textContent.includes('PRODUCT_UNLISTED') && document.querySelector('#audit-list').textContent.includes('6900000099991')")
 p.locator('#audit-action').fill('PRODUCT_UNLISTED')
 p.locator('#audit-filter button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#audit-list').textContent.includes('PRODUCT_UNLISTED') && document.querySelector('#audit-list').textContent.includes('6900000099991') && !document.querySelector('#audit-list').textContent.includes('INVITE_CREATED')")
 p.locator('#audit-action').fill('')
 p.locator('#audit-filter button[type="submit"]').click()
 p.locator('#catalog-query').fill('6900000099991')
 p.locator('#catalog-listing').select_option('unlisted')
 p.locator('#catalog-filter button[type="submit"]').click()
 p.wait_for_function("(()=>{const t=document.querySelector('#admin-catalog').textContent;return t.includes('6900000099991')&&t.includes('已下架')&&!t.includes('6901234567892')})()")
 p.locator('[data-panel="shop"]').click()
 p.locator('#barcode').fill('6900000099991')
 p.locator('#scan-form button[type="submit"]').click()
 p.wait_for_function("document.querySelector('#scan-hint').textContent.includes('已下架')")
 assert '6900000099991' not in p.locator('#catalog').inner_text()
 p.locator('[data-panel="admin"]').click()
 p.wait_for_function("document.querySelector('#ledger-balance').textContent.includes('一致')")
 code=p.locator('#invite-code').input_value()
 p.locator('[data-panel="shop"]').click()
 p.locator('#invite-token').fill(code)
 p.evaluate("() => { const b=document.querySelector('#redeem-btn'); b.click(); b.click(); }")
 p.wait_for_function("document.querySelector('#entry-result').textContent.includes('已领取员工发放的结账会话') && document.querySelector('#entry-result').textContent.includes('不会打开门禁') && !document.querySelector('#entry-result').textContent.includes('邀请码已使用')")
 with backend.app.state.db.connect() as conn:
  assert conn.execute("SELECT COUNT(*) n FROM audit_events WHERE action='INVITE_REDEEMED'").fetchone()['n']==1
  assert conn.execute('SELECT COUNT(*) n FROM guest_sessions').fetchone()['n']==2
 p.locator('[data-panel="admin"]').click()
 p.locator('#backup-download').click()
 p.wait_for_function("document.querySelector('#restore-report').textContent.includes('活动库未替换')")
 p.screenshot(path=str(root/'preview-mobile-v2.png'),full_page=True)
 p.set_viewport_size({'width':1440,'height':900})
 p.screenshot(path=str(root/'preview-desktop-v2.png'),full_page=True)
 print('desktop width:',p.evaluate('document.documentElement.scrollWidth'))
 b.close()

t.cleanup()
