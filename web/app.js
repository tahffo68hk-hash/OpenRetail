'use strict';
const $=id=>document.getElementById(id);
const state={products:[],cart:new Map(),token:sessionStorage.getItem('retail_guest')||'',csrf:'',orderId:'',paymentPollId:null,paymentProvider:'MOCK_ONLY',scanner:null,scanTimer:null};
const money=cents=>'¥'+(Number(cents||0)/100).toFixed(2);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=t=>t?new Date(t*1000).toLocaleString('zh-CN'):'—';
let toastTimer;
function toast(msg){$('toast').textContent=msg;$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),4500)}
async function api(path,{method='GET',body,admin=false,guest=false,form=false}={}){
 const headers={};if(admin&&state.csrf&&method!=='GET')headers['X-CSRF-Token']=state.csrf;if(guest&&state.token)headers.Authorization='Bearer '+state.token;
 if(body&&!form)headers['Content-Type']='application/json';
 const res=await fetch(path,{method,headers,body:body?(form?body:JSON.stringify(body)):undefined,cache:'no-store',credentials:'same-origin'});
 let data;try{data=await res.json()}catch{data={detail:'请求返回非JSON响应'}}
 if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
 return data;
}
async function store(){const s=await api('/api/public/store');state.paymentProvider=s.payment;document.querySelector('.notice b').textContent=s.demo?'演示付款与模拟门禁':'有人值守试点 · 实体门禁仍关闭';document.querySelector('.notice p').textContent=s.demo?'不采集真实身份、不执行实际开锁、不进行真实扣款。':'顾客仅凭员工签发邀请码结账；实际付款需官方商户配置并以服务端验签结果为准。无人营业和实体门禁均未开放。';if(!s.demo){$('entry-btn').disabled=true;$('entry-btn').textContent='访客自助开户未开放';$('door-btn').disabled=true;$('pay-btn').textContent=s.payment==='WECHAT_NATIVE'?'生成微信收款二维码':'正式支付未配置';$('cart-pay').textContent=s.payment==='WECHAT_NATIVE'?'生成收款码':'创建未付款订单'}else{$('cart-pay').textContent='模拟结算（非真实扣款）'} $('top-mode').textContent=s.store_mode==='UNATTENDED'?'无人值守演示':'有人营业演示';$('shop-mode-chip').textContent=s.store_mode==='UNATTENDED'?'🌙 无人模式':'☀️ 有人模式';return s}
async function loadProducts(){state.products=await api('/api/products');renderProducts();renderCart()}
const pict=['▣','◈','◉','▤','▥','◎','◇','▧'];
function renderProducts(){$('catalog').innerHTML=state.products.map((p,i)=>`<div class="product-card"><div class="product-icon">${pict[i%pict.length]}</div><div class="product-info"><b title="${esc(p.name)}">${esc(p.name)}</b><small>${esc(p.barcode)} · 可售 ${p.available_stock}</small><span class="price">${money(p.price_cents)}</span></div><button class="add-btn" data-add="${p.id}" ${p.available_stock<=0?'disabled':''} aria-label="添加 ${esc(p.name)}">+</button></div>`).join('')||'<p class="muted">没有商品</p>'}
function add(pid){const p=state.products.find(x=>x.id===Number(pid));if(!p)return;const old=state.cart.get(p.id)||0;if(state.orderId){toast('已有待付款订单，请先完成付款或取消订单');return}if(old>=p.available_stock){toast('库存不足');return}state.cart.set(p.id,old+1);state.orderId='';$('pay-btn').disabled=true;renderCart()}
function renderCart(){const items=[...state.cart.entries()];$('cart-count').textContent=items.reduce((sum,[,q])=>sum+q,0)+'件';const total=items.reduce((sum,[id,q])=>sum+(state.products.find(p=>p.id===id)?.price_cents||0)*q,0);$('cart-total').textContent=money(total);$('checkout-btn').disabled=!state.token||!items.length||!!state.orderId;
 $('cart').innerHTML=items.length?items.map(([id,qty])=>{const p=state.products.find(x=>x.id===id);return p?`<div class="cart-line"><div><b>${esc(p.name)}</b><small>${money(p.price_cents)} × ${qty}</small></div><div class="qty-tools"><button data-minus="${id}" aria-label="减少">−</button><span>${qty}</span><button data-add="${id}" aria-label="增加">+</button></div></div>`:''}).join(''):'<div class="cart-empty">购物车为空，先从货架添加商品。</div>';if($('cart-pay'))$('cart-pay').disabled=!state.token||(!items.length&&!state.orderId)}
function stopCamera(){if(state.scanTimer){clearInterval(state.scanTimer);state.scanTimer=null}if(state.scanner){state.scanner.getTracks().forEach(t=>t.stop());state.scanner=null}$('scanner-video').hidden=true}
async function cameraScan(){if(state.scanner){stopCamera();$('camera-btn').textContent='尝试摄像头识别';return}if(!('BarcodeDetector'in window)||!navigator.mediaDevices?.getUserMedia){toast('此浏览器不支持 BarcodeDetector 或缺少安全 HTTPS 环境，请使用扫码枪或输入条码');return}
 try{const detector=new BarcodeDetector({formats:['ean_13','ean_8','code_128','upc_a']});const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});state.scanner=stream;const video=$('scanner-video');video.srcObject=stream;video.hidden=false;await video.play();$('camera-btn').textContent='关闭摄像头';state.scanTimer=setInterval(async()=>{if(video.readyState<2)return;try{const codes=await detector.detect(video);if(codes.length){$('barcode').value=codes[0].rawValue;stopCamera();$('camera-btn').textContent='尝试摄像头识别';tryScan()}}catch{}},600)}catch(e){stopCamera();toast('摄像头无法启动：'+e.message)}}
function tryScan(){const code=$('barcode').value.trim();const p=state.products.find(p=>p.barcode===code);if(!p){toast('未找到条码：'+code);return}add(p.id);$('barcode').value='';toast('已添加 '+p.name)}
function describePayment(order){
 if(!order||!order.status)return {text:'尚未创建订单',cls:''};
 if(order.status==='PAID'&&order.payment_kind==='MOCK_NOT_REAL_MONEY')return {text:'模拟支付成功 · 非真实扣款 · 已扣库存 · '+money(order.total_cents),cls:'mock-paid'};
 if(order.status==='PAID'&&order.real_money)return {text:'已验签付款 · '+money(order.total_cents),cls:'mock-paid'};
 if(order.status==='EXPIRED')return {text:'已超时 · 未付款 · 预留已释放，请重新下单',cls:'timeout'};
 if(order.status==='CANCELLED')return {text:'已取消 · 未付款 · 预留已释放',cls:'timeout'};
 if(order.status==='REFUNDED')return {text:'演示库存已由店员退回',cls:''};
 if(order.status==='PAYMENT_REVIEW')return {text:'待人工核对 · 请勿重复付款',cls:'timeout'};
 if(order.status==='PENDING'||order.status==='PAYMENT_PENDING')return {text:'未付款 · 库存已预留 · 订单 '+(order.id||'').slice(0,10)+' · '+money(order.total_cents),cls:'unpaid'};
 return {text:order.status,cls:''};
}
function showPay(order){const box=$('payment-result');const view=describePayment(order);box.textContent=view.text;box.className='inline-note pay-banner'+(view.cls?' '+view.cls:'')}
async function refreshMine(){if(!state.token){$('my-orders').innerHTML='<p class="muted">还没有订单</p>';return}const rows=await api('/api/orders',{guest:true});$('my-orders').innerHTML=rows.length?rows.map(o=>{const view=describePayment(o);return `<article class="${esc(view.cls)}"><b>${esc(view.text.split('·')[0].trim())}</b><div>${money(o.total_cents)} · ${time(o.created_at)}</div><small>${esc(o.payment_kind)} · verified=${o.verified} · real_money=${o.real_money?'true':'false'}</small></article>`}).join(''):'<p class="muted">还没有订单</p>'}
async function showEntryStatus(){const status=await api('/api/entry/status',{guest:true});const latest=status.events[0];$('entry-status').textContent='实体门未打开 · physical_door_opened=false · 虚拟事件 '+(latest?latest.result+' / '+latest.detail:'无')}
async function createOrder(){if(!state.token)throw Error('先创建访客会话');const req={request_id:(crypto.randomUUID?.()||('demo-'+Date.now()+'-'+Math.random())),lines:[...state.cart].map(([product_id,quantity])=>({product_id,quantity}))};const r=await api('/api/orders',{method:'POST',body:req,guest:true});state.orderId=r.id;$('cancel-order-btn').disabled=false;$('pay-btn').disabled=state.paymentProvider==='DISABLED';$('payment-qr').hidden=true;showPay(r);await refreshMine();return r}
async function confirmMock(){const r=await api('/api/payments/mock-confirm',{method:'POST',body:{order_id:state.orderId},guest:true});showPay(r);if(r.status==='PAID'){state.cart.clear();state.orderId='';$('cancel-order-btn').disabled=true;$('pay-btn').disabled=true;await loadProducts()}await refreshMine();return r}
function fundLabel(order){if(order.status==='PAID'&&order.provider==='MOCK_NOT_REAL_MONEY')return '模拟销售额';if(Number(order.verified)===1)return '已验签真实资金';if(order.status==='REFUNDED'&&order.provider==='MOCK_NOT_REAL_MONEY')return '模拟退回';return '未收款'}
async function adminRefresh(){if(!state.csrf)return;const [overview,orders,events,ledger,help]=await Promise.all([api('/api/admin/overview',{admin:true}),api('/api/admin/orders',{admin:true}),api('/api/admin/events',{admin:true}),api('/api/admin/inventory-ledger',{admin:true}),api('/api/admin/help-requests',{admin:true})]);$('admin-body').hidden=false;$('m-orders').textContent=overview.paid_orders;$('m-sales').textContent=money(overview.simulated_revenue_cents);$('m-real').textContent=money(overview.verified_revenue_cents);$('today-summary').textContent='今日订单 '+overview.today_order_count+' · 模拟销售额（非真实资金） '+money(overview.today_simulated_revenue_cents)+' · 已验签金额（真实资金） '+money(overview.today_verified_revenue_cents);$('help-attention').textContent='待处理求助 '+overview.help_needs_attention+'（未结案，含已确认） · 已处理 '+overview.help_resolved;$('low-stock-list').innerHTML=(overview.low_stock||[]).map(p=>`<div class="event"><span>${esc(p.barcode)} ${esc(p.name)} · 账面 ${p.stock} · 预留 ${p.reserved_stock} · 可售 ${p.available_stock}</span><time>阈值 ${overview.low_stock_threshold}</time></div>`).join('')||'<p class="muted">没有账面库存达到或低于阈值的商品</p>';$('m-products').textContent=overview.products;$('m-entries').textContent=overview.door_events;$('mode-info').textContent='当前模式：'+(overview.mode==='UNATTENDED'?'无人值守':'有人经营')+'（实物门锁不受控制）';$('ha-state').textContent=overview.home_assistant.status;$('mode-staffed').classList.toggle('selected',overview.mode==='STAFFED');$('mode-unattended').classList.toggle('selected',overview.mode==='UNATTENDED');$('order-table').innerHTML=orders.map(o=>{const refund=o.status==='PAID'&&o.provider==='MOCK_NOT_REAL_MONEY'&&Number(o.verified)!==1?`<button class="btn secondary" type="button" data-mock-refund="${esc(o.id)}">模拟退款</button>`:'';return `<tr><td title="${esc(o.id)}">${esc(o.id.slice(0,12))}…</td><td><span class="status ${o.status==='PAID'?'paid':''}">${esc(o.status)}</span></td><td>${money(o.total_cents)}</td><td>${esc(fundLabel(o))}</td><td>${time(o.created_at)}</td><td>${refund}</td></tr>`}).join('')||'<tr><td colspan="6">暂无订单</td></tr>';$('ledger-balance').textContent=(ledger.balanced?'流水合计与账面一致':'流水与账面不一致，需要人工核对')+' · 权威是本库 SQLite · 模拟金额不是真实资金';$('ledger-table').innerHTML=ledger.products.map(p=>`<tr><td>${esc(p.barcode)}</td><td>${p.stock}</td><td>${p.reserved_stock}</td><td>${p.ledger_stock}</td><td>${p.balanced?'一致':'不一致'}</td></tr>`).join('')||'<tr><td colspan="5">没有商品</td></tr>';$('ledger-moves').innerHTML=ledger.movements.slice(0,8).map(m=>`<li>${esc(m.reason)} 库存 ${m.stock_delta} / 预留 ${m.reserved_delta}</li>`).join('');const helpLabel={OPEN:'待处理',ACKNOWLEDGED:'已确认',RESOLVED:'已处理'};$('help-list').innerHTML=(help.requests||[]).map(h=>{const buttons=h.status==='RESOLVED'?'':`<button class="btn secondary" type="button" data-help-id="${esc(h.id)}" data-help-status="ACKNOWLEDGED">确认</button> <button class="btn secondary" type="button" data-help-id="${esc(h.id)}" data-help-status="RESOLVED">处理完成</button>`;return `<div class="event"><span>${esc(h.message)} · ${esc(helpLabel[h.status]||h.status)} · 会话 ${esc((h.session_id||'无').slice(0,8))} · 订单 ${esc((h.order_id||'无').slice(0,8))} ${buttons}</span><time>${time(h.created_at)}</time></div>`}).join('')||'<p class="muted">没有求助</p>';$('door-lock-note').textContent=events.physical_door_opened===false?'physical_door_opened=false · 没有实体开锁':'门状态异常';$('door-event-list').innerHTML=(events.door||[]).map(e=>`<div class="event"><span>${esc(e.result)} · ${esc(e.detail)} · 实体门未打开</span><time>${time(e.created_at)}</time></div>`).join('')||'<p class="muted">没有虚拟进门记录</p>';const incident=events.frigate.map(e=>({name:'Frigate 人员事件 · '+e.camera+' · '+e.event_type,t:e.created_at})),doors=events.door.map(e=>({name:'虚拟门禁 · '+e.result+' · '+e.detail,t:e.created_at}));$('event-list').innerHTML=[...incident,...doors].sort((a,b)=>b.t-a.t).slice(0,15).map(e=>`<div class="event"><span>${esc(e.name)}</span><time>${time(e.t)}</time></div>`).join('')||'<p class="muted">暂无设备事件</p>'}
async function run(fn){try{await fn()}catch(e){toast(e.message);console.error(e)}}
document.addEventListener('click',e=>{const refund=e.target.closest('[data-mock-refund]');if(refund){run(async()=>{const r=await api('/api/admin/orders/'+refund.dataset.mockRefund+'/mock-refund',{admin:true,method:'POST'});toast(r.real_money?'异常：模拟退款不应产生真实资金':'模拟退款已回补库存，不是微信退款');await adminRefresh();await loadProducts()});return}const helpAction=e.target.closest('[data-help-status]');if(helpAction){run(async()=>{const r=await api('/api/admin/help-requests/'+helpAction.dataset.helpId+'/status',{admin:true,method:'POST',body:{status:helpAction.dataset.helpStatus}});if(r.physical_door_opened||r.payment_required_to_leave||r.door_authorized)throw Error('处理求助不应开门或要求付款');toast(r.status==='RESOLVED'?'求助已处理，门未打开':'已确认求助，门未打开');await adminRefresh()});return}const nav=e.target.closest('[data-panel]');if(nav){document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n===nav));['shop','admin'].forEach(p=>$('panel-'+p).hidden=p!==nav.dataset.panel);$('current-title').textContent=nav.dataset.panel==='shop'?'顾客自助购物':'店主工作台';if(nav.dataset.panel==='admin')run(adminRefresh)}const addButton=e.target.closest('[data-add]');if(addButton)add(addButton.dataset.add);const minus=e.target.closest('[data-minus]');if(minus){if(state.orderId){toast('请先完成或取消当前订单');return}const id=Number(minus.dataset.minus);const q=(state.cart.get(id)||0)-1;if(q<=0)state.cart.delete(id);else state.cart.set(id,q);state.orderId='';$('pay-btn').disabled=true;renderCart()}});
$('entry-btn').onclick=()=>run(async()=>{const s=await api('/api/entry',{method:'POST'});state.token=s.guest_token;sessionStorage.setItem('retail_guest',state.token);$('entry-result').textContent='访客会话创建成功（未进行身份核验）；有效期至 '+time(s.expires_at);$('door-btn').disabled=false;await showEntryStatus();renderCart();toast('演示访客会话已创建')});
$('door-btn').onclick=()=>run(async()=>{if(!state.token)throw Error('请先创建会话');const r=await api('/api/door/open',{method:'POST',guest:true});if(r.physical_door_opened)throw Error('实体门状态异常');$('entry-result').textContent='开门结果：'+r.result+'。实际门锁未动作。';$('entry-status').textContent='实体门未打开 · physical_door_opened=false · 虚拟事件 '+(r.events||[]).map(e=>e.result).join('、');toast('仅模拟开门成功')});
$('help-btn').onclick=()=>run(async()=>{const message=$('help-message').value.trim();const r=await api('/api/help',{method:'POST',body:{message,order_id:state.orderId||null},guest:!!state.token});if(r.physical_door_opened||r.payment_required_to_leave)throw Error('求助状态异常');$('help-result').textContent='已通知店员 · '+time(r.created_at)+' · 不会打开实体门 · 离店不需要付款';$('help-message').value='';toast('已呼叫店员')});
$('scan-form').onsubmit=e=>{e.preventDefault();tryScan()};$('camera-btn').onclick=()=>run(cameraScan);
$('checkout-btn').onclick=()=>run(async()=>{$('checkout-btn').disabled=true;try{await createOrder();toast('订单已预留库存，等待支付确认')}finally{renderCart()}});
$('pay-btn').onclick=()=>run(async()=>{if(!state.orderId)throw Error('尚无待付订单');$('pay-btn').disabled=true;
 if(state.paymentProvider==='WECHAT_NATIVE'){
   const r=await api('/api/orders/'+state.orderId+'/wechat-native',{method:'POST',guest:true});
   $('payment-qr').src=r.qr_data_uri;$('payment-qr').hidden=false;$('cancel-order-btn').disabled=true;pollVerifiedPayment(state.orderId);
   $('payment-result').textContent='未付款 · 请从另一台设备扫描微信支付二维码；付款后以服务端验签为准。';
   $('payment-result').className='inline-note pay-banner unpaid';
   toast('收款二维码已生成，请通过后台核对实际付款状态');return;
 }
 if(state.paymentProvider!=='MOCK_ONLY')throw Error('没有配置可用的收款渠道');
 const r=await confirmMock();
 toast(r.status==='PAID'?'模拟支付完成（没有真实资金流转）':describePayment(r).text)});
$('cart-pay').onclick=()=>run(async()=>{if(state.paymentProvider==='WECHAT_NATIVE'){if(!state.orderId)await createOrder();$('pay-btn').click();return}if(state.paymentProvider!=='MOCK_ONLY')throw Error('没有配置可用的收款渠道');if(!state.orderId)await createOrder();const r=await confirmMock();toast(r.status==='PAID'?'模拟支付完成（没有真实资金流转）':describePayment(r).text)});
$('redeem-btn').onclick=()=>run(async()=>{
 const invite=$('invite-token').value.trim();const r=await api('/api/entry/redeem',{method:'POST',body:{invite}});
 state.token=r.guest_token;sessionStorage.setItem('retail_guest',state.token);
 $('invite-token').value='';$('entry-result').textContent='已领取员工发放的结账会话；不会打开门禁。';
 await showEntryStatus();await loadProducts();toast('已领取有效结账会话');
});
const inviteFromUrl=new URLSearchParams(location.search).get('invite');
if(inviteFromUrl){history.replaceState(null,'',location.pathname);$('invite-token').value=inviteFromUrl;
 run(async()=>{const r=await api('/api/entry/redeem',{method:'POST',body:{invite:inviteFromUrl}});
 state.token=r.guest_token;sessionStorage.setItem('retail_guest',state.token);$('invite-token').value='';
 $('entry-result').textContent='结账会话已领取；这不是进店权限。';await showEntryStatus();await loadProducts();toast('结账会话已激活')});}
$('issue-invite').onclick=()=>run(async()=>{
 const r=await api('/api/admin/checkout-invite',{admin:true,method:'POST'});
 $('invite-result').textContent='一次性链接，有效期至 '+time(r.expires_at)+'。请让顾客扫码，不能作为进门凭证。';
 $('invite-qr').src=r.qr_data_uri;$('invite-qr').hidden=false;
});
$('cancel-order-btn').onclick=()=>run(async()=>{if(!state.orderId)return;
 const r=await api('/api/orders/'+state.orderId+'/cancel',{method:'POST',guest:true});
 state.orderId='';$('pay-btn').disabled=true;$('cancel-order-btn').disabled=true;
 $('payment-qr').hidden=true;showPay(r);await refreshMine();
 await loadProducts();toast('已取消未付款订单');
});
async function pollVerifiedPayment(orderId){
 if(state.paymentPollId)clearTimeout(state.paymentPollId);
 const began=Date.now();
 async function check(){
  if(state.orderId!==orderId)return;
  try{
   const r=await api('/api/orders/'+orderId,{guest:true});
   if(r.status==='PAID'||r.status==='EXPIRED'||r.status==='CANCELLED'||r.status==='PAYMENT_REVIEW'){
    showPay(r);await refreshMine();
    if(r.status==='PAID'){$('payment-qr').hidden=true;state.cart.clear();state.orderId='';await loadProducts();toast(r.real_money?'已验签付款':'付款状态已更新');return}
    if(r.status!=='PAYMENT_REVIEW'){$('payment-qr').hidden=true;state.orderId='';return}
    return;
   }
  }catch(e){/* 临时断网，不代表支付成功或失败 */}
  if(Date.now()-began<120000)state.paymentPollId=setTimeout(check,5000);
  else $('payment-result').textContent='付款结果仍待商户确认，请联系工作人员查单。请勿重复付款。';
 }
 state.paymentPollId=setTimeout(check,3000);
}
$('admin-login').onclick=()=>run(async()=>{const r=await api('/api/admin/login',{method:'POST',body:{password:$('admin-key').value}});state.csrf=r.csrf;$('admin-key').value='';await adminRefresh();toast('已安全登录管理工作台')});
$('admin-logout').onclick=()=>run(async()=>{if(state.csrf)await api('/api/admin/logout',{admin:true,method:'POST'});state.csrf='';$('admin-key').value='';$('admin-body').hidden=true;toast('已退出管理会话')});
for(const [id,mode] of [['mode-staffed','STAFFED'],['mode-unattended','UNATTENDED']])$(id).onclick=()=>run(async()=>{await api('/api/admin/mode',{admin:true,method:'PUT',body:{mode}});await adminRefresh();await store();toast('模拟营业模式已切换')});
$('refresh-admin').onclick=()=>run(async()=>{await adminRefresh();await loadProducts();toast('数据已刷新')});
async function adminProduct(barcode){const rows=await api('/api/admin/products',{admin:true});const found=rows.find(item=>item.barcode===barcode);if(!found)throw Error('找不到条码 '+barcode);return found}
$('product-form').onsubmit=e=>{e.preventDefault();run(async()=>{const f=new FormData(e.target);const r=await api('/api/admin/products',{admin:true,method:'POST',body:{barcode:String(f.get('barcode')).trim(),name:String(f.get('name')).trim(),price_cents:Math.round(Number(f.get('price'))*100),stock:Number(f.get('stock')),active:true}});$('product-status').textContent='已新增 '+r.barcode+'，期初库存 '+r.stock+' 已入账';e.target.reset();await adminRefresh();await loadProducts();toast('商品已新增')})};
$('edit-form').onsubmit=e=>{e.preventDefault();run(async()=>{const f=new FormData(e.target);const before=await adminProduct(String(f.get('barcode')).trim());const r=await api('/api/admin/products/'+before.id,{admin:true,method:'PATCH',body:{name:String(f.get('name')).trim(),price_cents:Math.round(Number(f.get('price'))*100)}});if(r.stock!==before.stock||r.stock_changed)throw Error('改价不应改库存');$('product-status').textContent='已改名称和售价，库存仍为 '+r.stock;await loadProducts();toast('名称和售价已更新')})};
$('adjust-form').onsubmit=e=>{e.preventDefault();run(async()=>{const f=new FormData(e.target);const product=await adminProduct(String(f.get('barcode')).trim());const r=await api('/api/admin/products/'+product.id+'/adjust-stock',{admin:true,method:'POST',body:{quantity_delta:Number(f.get('delta')),reason:String(f.get('reason'))}});$('product-status').textContent='库存已调整为 '+r.stock+'，流水已记录';await adminRefresh();await loadProducts();toast('库存已调整')})};
async function uploadCsv(dry){const file=$('csv-file').files?.[0];if(!file)throw Error('请先选择 CSV 文件');if(!dry&&!confirm('仅允许首次建账导入；已有订单将拒绝覆盖库存。确定继续？'))return;const data=new FormData();data.append('file',file);const r=await api('/api/admin/import-products?dry_run='+String(dry),{admin:true,method:'POST',form:true,body:data});$('csv-status').textContent=dry?'检查通过，共 '+r.count+' 条：'+r.preview.map(x=>x.name).slice(0,4).join('、'):'已导入 '+r.count+' 条商品。注意不会自动同步到 OSPOS。';if(!dry){await loadProducts();await adminRefresh()}toast(dry?'CSV 检查通过':'CSV 已导入')}
$('csv-preview').onclick=()=>run(()=>uploadCsv(true));$('csv-import').onclick=()=>run(()=>uploadCsv(false));
$('csv-export').onclick=()=>run(async()=>{const res=await fetch('/api/admin/export-products',{credentials:'same-origin',cache:'no-store'});if(!res.ok)throw Error('导出失败');const text=await res.text();const blob=new Blob([text],{type:'text/csv'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='openretail-products.csv';link.click();URL.revokeObjectURL(link.href);if(!text.startsWith('barcode,name,price,stock'))throw Error('导出列不正确');$('csv-status').textContent='已导出当前 SQLite 商品，列与导入相同。';toast('商品 CSV 已导出')});
if(state.token){$('door-btn').disabled=false;$('entry-result').textContent='已恢复当前浏览器的访客会话（可能已过期）';run(async()=>{await showEntryStatus();await refreshMine()})}
// 管理员密码和 CSRF 令牌仅存在内存中；刷新页面后需重新登录。
run(async()=>{await store();await loadProducts()});
