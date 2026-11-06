from pathlib import Path
import sys
import shutil
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from urllib.parse import urlsplit
import os
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
from openretail.config import Settings
from openretail.main import create_app
from dotenv import dotenv_values
root=ROOT
t=tempfile.TemporaryDirectory(prefix='openretail-ui-')
cfg=Settings(db_path=str(Path(t.name)/'smoke.sqlite3'),admin_key='A'*40,integration_key='I'*40,app_secret='S'*40)
with TestClient(create_app(cfg)) as backend,sync_playwright() as pw:
 b=pw.chromium.launch(headless=True,executable_path=(shutil.which('chromium') or shutil.which('google-chrome') or pw.chromium.executable_path),args=['--no-sandbox'])
 p=b.new_page(viewport={'width':390,'height':844})
 errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
 def call_backend(path, method, headers,body):
  res=backend.request(method,path,headers=headers,content=body)
  return {'status':res.status_code,'data':res.json() if res.headers.get('content-type','').startswith('application/json') else res.text}
 p.expose_function('__callBackend',call_backend)
 html=(root/'web/index.html').read_text()
 html=html.replace('<link rel="stylesheet" href="/assets/styles.css">','<style>'+ (root/'web/styles.css').read_text()+'</style>')
 html=html.replace('<script src="/assets/app.js" defer></script>','')
 p.set_content(html,wait_until='domcontentloaded')
 p.evaluate('''() => {
  const mem=new Map();Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:k=>mem.get(k)||null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)}});
  window.fetch=async (path,opts={})=>{const x=await window.__callBackend(path,opts.method||'GET',opts.headers||{},opts.body||null);
    return {ok:x.status>=200&&x.status<300,status:x.status,json:async()=>x.data}}
 }''')
 p.add_script_tag(content=(root/'web/app.js').read_text())
 p.wait_for_function("document.querySelectorAll('.product-card').length===8",timeout=10000)
 print('products:',p.locator('.product-card').count(),'width:',p.evaluate('document.documentElement.scrollWidth'))
 p.locator('#entry-btn').click()
 p.wait_for_function("document.querySelector('#entry-result').textContent.includes('成功')")
 p.locator('.add-btn').first.click()
 p.locator('#checkout-btn').click()
 p.wait_for_function("document.querySelector('#payment-result').textContent.includes('订单')")
 print('order:',p.locator('#payment-result').inner_text())
 p.locator('#pay-btn').click()
 p.wait_for_function("document.querySelector('#payment-result').textContent.includes('模拟支付成功')")
 print('paid:',p.locator('#payment-result').inner_text())
 p.wait_for_function("document.querySelector('#my-orders').textContent.includes('模拟支付成功')")
 p.wait_for_function("document.querySelector('#my-orders').textContent.includes('real_money=false')")
 p.wait_for_function("document.querySelector('#entry-status').textContent.includes('实体门未打开')")
 assert 'refund' not in p.locator('#panel-shop').inner_text().lower()
 assert '退款' not in p.locator('#panel-shop').inner_text()
 p.locator('[data-panel="admin"]').click()
 p.locator('#admin-key').fill('A'*40)
 p.locator('#admin-login').click()
 p.wait_for_function("!document.querySelector('#admin-body').hidden")
 print('admin:',p.locator('#m-orders').inner_text(),'errors:',errors)
 p.screenshot(path=str(root/'preview-mobile-v2.png'),full_page=True)
 p.set_viewport_size({'width':1440,'height':900})
 p.screenshot(path=str(root/'preview-desktop-v2.png'),full_page=True)
 print('desktop width:',p.evaluate('document.documentElement.scrollWidth'))
 b.close()

t.cleanup()
