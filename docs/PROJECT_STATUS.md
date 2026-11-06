# 项目状态（2026-11-06 复核）

复核对象：公开仓库 `https://github.com/tahffo68hk-hash/OpenRetail`，`main` HEAD `2e408a1fff5698e3c00aa58231e65df214cc840b`。结论只来自本次阅读、官方文档查阅和本机实际运行。更早的代理记录在被本次复现之前都算未核实。

完全无人值守经营仍是 **NOT_APPROVED**。示例配置里的真实支付和实体开锁都是关闭的。

## 本增量（从今日摘要查看求助）

已在代码和测试里做到，并在本机复跑：

- 「今日需要处理」增加「查看待处理求助」，只滚动到原来的顾客求助区，并把筛选设成未结案（`OPEN` 加 `ACKNOWLEDGED`），和摘要里的未结案数是同一批。也可以改回全部，或只看已处理、待处理、已确认。
- 没有匹配时仍显示「没有求助」。筛选和跳转不改求助状态，不写库存流水，不开门，不调用支付机构。确认和处理完成仍不把门或离店付款标成 true。未登录仍是 401。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**77 passed，1 warning，8.17s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。77 = 上一轮 76 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍用「生成访客会话」完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金 · 已扣库存」。点「查看待处理求助」之后，求助仍是「请到货架帮忙」和「待处理」，没有被自动确认；随后的「已确认」仍由原来的按钮完成。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。这条 PR 仍未合并。

## 本增量（按动作筛选操作记录）

已在代码和测试里做到，并在本机复跑：

- 管理页的操作记录可以按动作名称筛选，例如 `INVITE_CREATED` 和 `INVITE_REDEEMED`。留空仍是最近的全部记录。没有匹配时仍显示「没有操作记录」，不是错误页。
- 筛选只读。不新增记录，不改账面或预留，不写流水，不关单，不开门，不调用支付机构。未登录仍是 401。没有修改或删除接口。
- `INVITE_CREATED` 仍只记 `lifetime_seconds=120`。`INVITE_REDEEMED` 仍只记会话编号前缀和 identity_verified=false、door_authorized=false。都不记邀请码。演示「生成访客会话」不写 `INVITE_REDEEMED`。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**76 passed，1 warning，8.04s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。76 = 上一轮 75 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍用「生成访客会话」完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金 · 已扣库存」。下架之后按 `PRODUCT_UNLISTED` 筛选，列表含该动作和条码，不含 `INVITE_CREATED`，然后把筛选清空。没有关单。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。这条 PR 仍未合并。

## 本增量（今日摘要里的未付款占用）

已在代码和测试里做到，并在本机复跑：

- 「今日需要处理」显示「未付款占用 N 笔」，数字和原来的占用列表是同一批 `PENDING` / `PAYMENT_PENDING` 订单。没有未付款占用时是「未付款占用 0 笔」，占用区仍写「没有占用库存的未付款订单」。
- 「查看未付款占用」只滚动到已有的占用区，不关单、不改库存、不开门、不调用支付机构。读取这个数字不写流水，也不提前让预留到期。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**75 passed，1 warning，7.85s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。75 = 上一轮 74 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍用「生成访客会话」完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金 · 已扣库存」。进入管理页后，「今日需要处理」含「未付款占用 0 笔」，占用区含「没有占用库存的未付款订单」，并点了「查看未付款占用」，没有关单。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（领取邀请码写入操作记录）

已在代码和测试里做到，并在本机复跑：

- 成功领取结账邀请码追加 `INVITE_REDEEMED`。内容是新会话编号前 12 位，以及 identity_verified=false、door_authorized=false。不记录邀请码本身。创建邀请码仍是 `INVITE_CREATED`，只记 120 秒，也不记码。
- 再用返回「邀请码已使用」，过期返回「邀请码已过期」。这两种都不新建会话，也不把码写进操作记录。领取不改库存，响应里 physical_door_opened、door_authorized、identity_verified 仍是 false。
- 演示「生成访客会话」不写 `INVITE_REDEEMED`。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**74 passed，1 warning，7.71s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。74 = 上一轮 73 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍用「生成访客会话」完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金 · 已扣库存」。管理页仍可创建邀请码。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（扫码后准备下一枪）

已在代码和测试里做到，并在本机复跑：

- 顾客页扫码成功后，条码框清空并重新获得焦点，提示仍是「已添加」加商品名。失败（未找到条码、已下架、可售库存不足）仍用原来的文字，同时清空条码框并聚焦，下一枪不会接在失败的码后面。
- 管理页、邀请码输入和求助框正在使用时，不会把焦点抢走。生成访客会话或成功领取邀请码之后，如果还在顾客页，焦点回到条码框。这次只动输入焦点，不改库存、上下架、门或支付。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**73 passed，1 warning，7.58s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。73 = 上一轮 73。这一轮是页面行为，没有新增 pytest。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。未知条码失败后，提示含「未找到条码」，条码框为空且处于焦点。接着扫 `6901234567892`，提示含「已添加」和「瓶装饮用水」，条码框再次为空且处于焦点，购物车是 ¥2.00。顾客没有领取邀请码，随后仍是「模拟支付成功 · 非真实资金 · 已扣库存 · ¥2.00」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（访客会话过期提示）

已在代码和测试里做到，并在本机复跑：

- 保存的访客令牌如果过期，接口返回「访客会话已过期」。页面清掉这个令牌。演示里提示可以再次使用「生成访客会话」，不会自动新建会话。非演示门店提示向店员领取结账邀请码，并写明这不是身份核验，也不会开门，也不会重新打开「生成访客会话」。
- 令牌仍然有效时，页面写明已恢复，并显示门店时区的到期时间，不再写「可能已过期」。
- 访客令牌过期不会取消未付款订单，也不改账面或预留。900 秒预留和外部支付中的释放规则没有改。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**73 passed，1 warning，7.83s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。73 = 上一轮 71 + 本增量 2。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍用「生成访客会话」完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金 · 已扣库存」。会话过期由 pytest 核对，没有等待真实的会话时长。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（同一会话只保留一张未付款订单）

已在代码和测试里做到，并在本机复跑：

- 会话里已经有 `PENDING` 或 `PAYMENT_PENDING` 时，用新的请求号再下单返回 409「已有待付款订单，请先完成付款或取消订单」。不会插入新订单，也不会再预留库存或写流水。同一个请求号仍然返回原来的订单。
- 取消、按原规则超时释放，或付款（含模拟支付）之后，同一会话可以再下一单。别的会话不受这张未付款订单阻挡，只受可售库存限制。未登录下单仍是 401。
- 顾客页的结算、创建订单和模拟确认付款在请求进行中不会再发第二次。被拒绝的重复下单会把已有未付款订单（含「预留至」）显示出来。演示结账仍不需要邀请码。900 秒预留和外部支付中的释放规则没有改。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**71 passed，1 warning，7.20s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。71 = 上一轮 70 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍用「生成访客会话」完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金 · 已扣库存」。重复下单由 pytest 核对，没有做不稳定的双击。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（结账邀请码的失败提示和审计）

已在代码和测试里做到，并在本机复跑：

- 非演示门店里，没有会话的顾客不能自己开访客会话。页面和接口都会提示向店员领取结账邀请码，并写明这不是身份核验，也不会开门。`/api/public/store` 的 `invite_required` 在非演示时为 true。
- 过期码返回「邀请码已过期」，用过的码返回「邀请码已使用」。这两种都不会新建会话。成功领取仍是 identity_verified=false、door_authorized=false、physical_door_opened=false。
- 创建邀请码追加 `INVITE_CREATED`，只记 120 秒有效期和管理员身份，不记邀请码本身。这次记录不改库存、不开门、不调用支付机构。
- 演示里的「生成访客会话」仍然不需要邀请码。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**70 passed，1 warning，7.38s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。70 = 上一轮 69 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍用「生成访客会话」完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金」。管理页仍能创建邀请码。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是身份核验或真实收款。

## 本增量（有人值守的结账邀请码）

已在代码和测试里做到，并在本机复跑：

- 管理页原来的「创建2分钟邀请码」现在把码、约 120 秒和到期时间显示出来，并标明 identity_verified=false、door_authorized=false、physical_door_opened=false。顾客页可以领取这个码。领取不开门，也不要求付款才能离开。
- 同一码再用一次会被拒绝。过期的码也会被拒绝。演示里的「生成访客会话」仍然不需要邀请码，模拟支付仍可完成。未登录创建邀请码返回 401。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**69 passed，1 warning，6.99s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。69 = 上一轮 68 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客没有领取邀请码，仍完成 ¥2.00 模拟支付，并含「模拟支付成功 · 非真实资金」。管理页创建邀请码后，结果含「120」、identity_verified=false、door_authorized=false 和 physical_door_opened=false。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是身份核验或真实收款。

## 本增量（刷新后恢复本会话订单）

已在代码和测试里做到，并在本机复跑：

- 访客令牌本来就能读到本会话的订单。刷新后购物车和付款按钮只留在内存里，所以预留还在，页面却像空的。现在同一会话会把未付款订单的行、金额、编号和「预留至」填回去；模拟支付成功后仍显示小票、完整订单编号和「非真实资金」。
- 这次读取不新建订单，也不因此改账面或预留。别的会话看不到这张订单。未登录读订单返回 401。到期规则没有改。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**68 passed，1 warning，6.98s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。68 = 上一轮 67 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。未付款 ¥2.00 且含「预留至」时清空页面内存再拉回同一会话，购物车仍是 ¥2.00，订单编号不变。模拟支付后再拉一次，小票仍是「模拟支付成功 · 非真实资金 · 已扣库存 · ¥2.00」，购物车合计是 ¥0.00。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（从低库存打开商品）

已在代码和测试里做到，并在本机复跑：

- 「今日需要处理」里的低库存行仍显示条码、账面、预留和可售。新增「在商品里查找」，把条码填进原来的商品搜索，筛选保持「全部」，并滚到商品区。没有第二套目录。
- 这样查找不改库存、不新增流水、不改上下架、不开门、不调用支付机构。已下架的商品用同一条码、筛选为全部时仍能找到。未登录看概览或商品搜索返回 401。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**67 passed，1 warning，6.82s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。67 = 上一轮 66 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。账面为 4 的条码 `6900000099991` 出现在低库存列表后，点「在商品里查找」，商品区含该条码和「预留」。之后的改库存、下架、顾客扫码「已下架」和「活动库未替换」仍通过。模拟支付仍含「非真实资金」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（未付款预留何时结束）

已在代码和测试里做到，并在本机复跑：

- 未付款订单本来就在创建后 900 秒到期。顾客页和占用库存列表现在显示门店时区的到期时间（默认 Asia/Shanghai）以及剩余秒数。只是读出这个时间，不因此改库存。
- 到期后仍按原来的规则：`PENDING` 和 `mock:` 的 `PAYMENT_PENDING` 会释放预留，状态变为已超时未付款。微信或其他非 `mock:` 的 `PAYMENT_PENDING` 到点也不会被这个计时释放。
- 店员关闭占用仍走原来的 `mock-close`。未登录看占用列表返回 401。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**66 passed，1 warning，6.80s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。66 = 上一轮 65 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。未付款的 ¥2.00 订单在加减数量和付款之前显示「预留至 2026-11-06 13:39 Asia/Shanghai」。随后模拟支付仍是「模拟支付成功 · 非真实资金 · 已扣库存 · ¥2.00」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（扫码和加数量的失败提示）

已在代码和测试里做到，并在本机复跑：

- 未知条码仍是「未找到条码」。已下架仍是「该商品已下架，暂不销售」。可售数量不够时，提示是「商品名 可售库存不足」，比较的是账面减去已预留。失败后购物车行、账面和预留都不变，流水仍与账面一致。
- 扫码失败不会再被写成「已添加」。这些失败不开门，不调用支付机构。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**65 passed，1 warning，7.07s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。65 = 上一轮 64 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。扫描 `0000000000000` 后提示含「未找到条码」，购物车合计仍是 ¥0.00。随后的模拟支付仍是 ¥2.00，并含「非真实资金」。可售库存不足由 pytest 核对，没有在浏览器里把种子商品加到库存上限。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（从求助打开对应订单）

已在代码和测试里做到，并在本机复跑：

- 顾客已经有未付款订单，或刚完成模拟支付，求助会带上这张订单。没有订单时仍只记会话，不编造订单编号。
- 管理页原来的求助行如果有订单编号，会显示完整编号，并用原来的订单查找打开它。模拟付款仍是 `MOCK_NOT_REAL_MONEY` / 非真实资金。只有会话编号时就显示会话编号。
- 从求助打开订单不会把求助改成已确认或已处理，不改库存，不开门，不调用支付机构。没有订单的求助仍可确认。未登录查看求助或订单返回 401。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**64 passed，1 warning，6.63s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。64 = 上一轮 63 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。顾客求助仍显示「请到货架帮忙」和「不会打开实体门」。管理页该行有「查看这张订单」。点开后查找状态含「已找到订单」和「非真实资金」，求助仍是「待处理」，之后的「已确认」仍在。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（管理工作台分区）

已在代码和测试里做到，并在本机复跑：

- 原有管理页按区块加上页内链接：今日需要处理、商品、订单、未付款占用、求助、备份、操作记录、门禁事件、设置。没有新的管理应用，也没有删掉原来的表单和按钮。
- 分区跳转只滚动到对应标题，不改库存、不开门、不调用支付机构。接口行为没有改。
- 顾客页和原来的状态文字还在，包括非真实资金、已下架、活动库未替换、模拟退回、已确认、虚拟进门和未付款占用的空列表。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**63 passed，1 warning，6.40s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。63 = 上一轮 62 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。模拟支付仍显示「模拟支付成功 · 非真实资金 · 已扣库存 · ¥2.00」。管理页后续核对仍通过，包括未付款占用空列表、流水「一致」、订单查找与导出、下架、操作记录和「活动库未替换」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（店员释放未付款预留）

已在代码和测试里做到，并在本机复跑：

- 管理页列出状态为 `PENDING` 或 `PAYMENT_PENDING`、仍占用预留的订单。每行有编号、门店当地时间、金额、状态、商品摘要，并标明「未付款 · 非真实资金」。这些行不会被写成已完成的销售。
- 关闭仍走原来的 `mock-close`：本地未付款和 `mock:` 支付中会释放预留，账面库存不变，流水仍与账面一致。再关一次是 `IDEMPOTENT`，不会第二次释放。已付款、已退回的订单返回 409，库存不再变。
- 外部支付引用不是 `mock:` 的 `PAYMENT_PENDING` 仍返回 409，预留保持不动，也不会去访问微信。关闭追加 `ORDER_CLOSED`，只记订单编号和管理员身份。未登录返回 401。关闭不开门。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**62 passed，1 warning，6.32s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。62 = 上一轮 61 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。模拟支付完成并进入管理页后，「占用库存的未付款订单」显示「没有占用库存的未付款订单」。脚本没有去关闭那笔已经模拟支付的订单。释放预留由 pytest 核对。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（未付款订单改数量）

已在代码和测试里做到，并在本机复跑：

- 购物车原有的加减按钮，在未付款订单上会改同一张订单的行，而不是另做一个篮子。增加时比较的是账面库存减去已预留。超过可售数量返回 409，订单行、账面和预留都不变。
- 减少或删掉一行会释放对应预留，流水仍与账面一致。删掉最后一行后订单变为 `CANCELLED`，购物车清空，不会留下金额为 0 却还能付款的订单。
- 已模拟付款的订单不能再改数量。已下架商品不能通过加数量重新加回。别的会话或未登录会被拒绝。这些请求不开门、不调用支付机构。顾客页没有退款按钮。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**61 passed，1 warning，6.73s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。61 = 上一轮 60 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。未付款订单先是 ¥2.00，点增加后购物车合计变为 ¥4.00，点减少后回到 ¥2.00，随后的模拟支付仍是 ¥2.00 且带「非真实资金」。顾客页没有「退款」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（顾客小票）

已在代码和测试里做到，并在本机复跑：

- 顾客页原来的支付结果和「本会话订单」改成可读的小票，没有新的应用。模拟支付成功后能看到完整订单编号、商品摘要、金额、状态，以及「非真实资金 · MOCK_NOT_REAL_MONEY · real_money=false」。编号在只读框里，可以选中复制。
- 未付款和已超时仍用原来的文字，并带上完整订单编号，方便交给店员查找。顾客页没有退款按钮。顾客退款接口仍是 404。
- 再次读取订单不会改库存、不会新增付款记录、不会写门禁事件。演示里的已验签金额仍是 0。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**60 passed，1 warning，6.29s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。60 = 上一轮 60。小票断言加在原有的顾客订单测试里，没有新增测试函数。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。模拟支付 ¥2.00 之后，小票含完整订单编号、「非真实资金」、「MOCK_NOT_REAL_MONEY」和「瓶装饮用水」，本会话订单含同一编号和「¥2.00」。顾客页文本没有「退款」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（按门店日期看订单，并按编号查找）

已在代码和测试里做到，并在本机复跑：

- 仍是原来的订单表和 `GET /api/admin/orders.csv`。可选一个门店当地日期，缺省是 `store_settings.store_timezone`（默认 `Asia/Shanghai`）的今天。窗口和今日摘要一样：带时区的本地零点到下一个本地零点，用 UTC 纪元秒比较。上海时间当天 01:00 属于这一天；没选中的另一天不会出现。
- 按完整订单编号精确查找。找到的订单用同一组字段：编号、当地时间、金额、状态、商品摘要、资金标签。模拟付款是 `MOCK_NOT_REAL_MONEY`，`verified` 为 0。不存在的编号返回 404「订单不存在」，不是空的成功结果。编号和日期对不上时返回 404，不会把别的日期混进来。
- CSV 列仍是 `order_id,local_time,timezone,status,amount_yuan,payment_label,real_money,items`。按日期导出只含那一天；按编号导出只含那一张。成功导出追加 `ORDERS_EXPORTED`，内容是条数、时区和日期。没有密钥。
- 未登录的列表、查找和导出返回 401。这些请求不改库存、不开门、不调用支付机构。演示里的已验签金额仍是 0。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**60 passed，1 warning，6.18s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。60 = 上一轮 59 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。模拟支付 ¥2.00 之后，日期框有门店当天的日期。用表格里的订单编号查找后，状态含「已找到订单」和「非真实资金」，表格仍含「¥2.00」。导出状态含「已导出该订单」和「非真实资金」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。脚本没有做浏览器内的时间穿越；昨天和 01:00 边界由 pytest 固定时间戳覆盖。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（管理端商品查找和筛选）

已在代码和测试里做到，并在本机复跑：

- 仍是原来的管理商品列表 `GET /api/admin/products`，没有第二套目录。空的查找条件返回原来的全部商品。
- 可以按条码或名称做子串查找，并筛选全部、上架、下架。低库存用 `store_settings.low_stock_threshold`（默认 5）比较账面 `products.stock`，`stock<=阈值` 的商品会出现，更高的不会。查找可以和筛选一起用。下架且账面不超过阈值的商品也会出现在低库存筛选里；今日摘要里的低库存列表仍只含在售商品。
- 这是管理员接口。未登录返回 401。查询参数只有查找词和筛选条件，不带管理员密钥。查找和筛选不改库存、不改流水、不开门、不调用支付机构。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**59 passed，1 warning，5.91s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。59 = 上一轮 58 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。下架条码 `6900000099991` 之后，按该条码并选择「下架」筛选，商品列表含该条码和「已下架」，不含种子条码 `6901234567892`。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机。

## 本增量（今日订单列表和 CSV）

已在代码和测试里做到，并在本机复跑：

- 管理页原有的「最近订单」改为同一张「今日订单」表，按 `store_settings.store_timezone`（默认 `Asia/Shanghai`）的自然日。比较方式和今日摘要一样：带时区的本地零点换成 UTC 纪元秒。上海时间当天 01:00 的订单在列表里，前一个当地日历日的订单不在。
- 每行有订单编号、当地时间、金额、订单状态、商品摘要，以及资金标签。模拟付款显示「模拟销售额（非真实资金）」，接口里的 `money_label` 是 `MOCK_NOT_REAL_MONEY`，`verified` 为 0。已验签金额在演示流程里仍是 0。
- `GET /api/admin/orders.csv` 导出同一批今日订单。列是 `order_id,local_time,timezone,status,amount_yuan,payment_label,real_money,items`。模拟行的 `payment_label` 为 `MOCK_NOT_REAL_MONEY`，`real_money` 为 `false`。文件里没有管理员密钥或支付凭证。成功导出追加 `ORDERS_EXPORTED`，只记条数和时区。
- 未登录查看或导出返回 401。查看和导出不改库存、不开门、不调用支付机构。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**58 passed，1 warning，6.02s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。58 = 上一轮 57 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。模拟支付 ¥2.00 之后，今日订单表含「非真实资金」和「¥2.00」，导出状态含「已导出今日订单」和「非真实资金」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。脚本没有做浏览器内的时间穿越；01:00 边界由 pytest 固定时间戳覆盖。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（管理操作审计）

已在代码和测试里做到，并在本机复跑：

- 复用已有的 `audit_events` 表，没有把这些记录塞进虚拟门禁事件。
- 新增、改价、库存调整、上架、下架、模拟退款、求助确认/处理、门店时区与低库存阈值、备份下载、隔离恢复预览都会追加一行。字段是时间、动作、目标条码或编号、以及现有管理员身份（演示密钥登录记为 `demo-admin-key`，密码会话记为 `operator`）。不记录密钥、备份内容和支付凭证。
- `GET /api/admin/audit` 需要管理员身份，未登录返回 401。没有修改或删除接口；对不存在的删除路径返回 404，记录仍在。
- 下架不改库存。库存调整只改变调整数量本身。审计响应里 `physical_door_opened=false`，`payment_required_to_leave=false`。
- 管理页登录后能看到最近的操作记录。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**57 passed，1 warning，5.91s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。57 = 上一轮 56 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。下架条码 `6900000099991` 之后，操作记录含 `PRODUCT_UNLISTED` 和该条码。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机。

## 本增量（单品上架 / 下架）

已在代码和测试里做到，并在本机复跑：

- 复用商品表已有的 `active` 字段，没有新的库存表，也没有删除商品。
- `POST /api/admin/products/{id}/listing` 只改在售状态。库存、预留和流水条数都不变。未登录返回 401。
- 顾客货架不再显示已下架商品。按条码查询返回 409「该商品已下架，暂不销售」，不是当成没有这个条码。直接下单也被拒绝。再次上架后可以下单。
- 已经有订单的商品仍可下架。管理页可以改它的名称、售价和库存。上下架不会开门，也不访问支付机构。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**56 passed，1 warning，5.58s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。56 = 上一轮 55 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。管理页把条码 `6900000099991` 下架后，状态含「已下架」和「库存仍为 6」。回到顾客页扫描该条码，提示含「已下架」，货架文本里没有这个条码。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机。

## 本增量（管理端备份与隔离恢复预览）

已在代码和测试里做到，并在本机复跑：

- 管理员 `GET /api/admin/backup` 用 SQLite 在线备份 API 下载副本，不复制可能写到一半的库文件。未登录返回 401。下载的临时文件会删掉，不写入仓库。
- `POST /api/admin/restore-preview` 把上传文件恢复到另一份临时库并返回 `integrity_check`、商品数和订单数。响应 `live_replaced=false`。活动库的库存不变。
- 把恢复目标指到活动库会被拒绝，活动库库存和订单仍在。不是 SQLite 的上传返回 422，活动库不动。
- 管理页有下载和隔离预览。没有「替换正在使用的库」按钮。备份和预览不会开门，也不访问支付机构。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**55 passed，1 warning，5.43s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。55 = 上一轮 53 + 本增量 2。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。管理页点击下载备份后，状态含「活动库未替换」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。隔离预览的一致性数字由 pytest 核对；浏览器脚本没有上传文件。这仍是 Chrome 到 TestClient 的桥，不是真机。

## 本增量（上海营业日和可改的低库存阈值）

已在代码和测试里做到，并在本机复跑：

- 今日订单、今日模拟销售额、今日已验签金额按门店时区的自然日计算。`store_settings.store_timezone` 默认 `Asia/Shanghai`。比较用带时区的本地零点换成 UTC 纪元秒，不把 naive 时间当成当地时间，也不改主机时区。
- 上海时间当天 01:00 的模拟订单计入当天，即使它的 UTC 日期是前一天。前一个当地日历日的订单不计入。无法识别的时区名称返回 422，原设置不变。
- 管理页可以保存低库存阈值和时区，沿用管理员登录和 CSRF。账面库存 5 在阈值 5 时出现，改成 4 后不再出现。已验签金额仍是 0。保存设置不会开门。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**53 passed，1 warning，4.97s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。53 = 上一轮 52 + 本增量 1。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。今日摘要含 `Asia/Shanghai`、模拟销售额和「已验签金额（真实资金） ¥0.00」。账面为 4 的新商品先出现在低库存列表；把阈值存成 3 之后，该条码从列表消失。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。脚本没有做浏览器内的时间穿越；01:00 边界由 pytest 固定时间戳覆盖。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（今日摘要和低库存）

已在代码和测试里做到，并在本机复跑：

- `GET /api/admin/overview` 增加 UTC 自然日的今日订单数、今日模拟销售额、今日已验签金额。演示里的模拟付款只进模拟销售额，已验签金额保持 0。昨天的订单不计入今日。
- 未结案求助 = `OPEN` + `ACKNOWLEDGED`。`RESOLVED` 单独计数，不算待处理。
- 低库存读取 `store_settings.low_stock_threshold`，缺省为 5，比较的是账面 `products.stock`。列表同时给出 `reserved_stock` 和可售数。库存 5 会出现，库存 6 不会。这不是第二套库存。
- 管理页登录后能看到「今日需要处理」。没有开锁按钮，也没有支付机构操作。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**52 passed，1 warning，5.20s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。52 = 上一轮 50 + 本增量 2。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。今日摘要含「模拟销售额（非真实资金）」和「已验签金额（真实资金） ¥0.00」，并含模拟订单的 ¥2.00。新增账面库存 4 的商品后，低库存列表出现该条码和「预留」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（有订单后的单品维护）

已在代码和测试里做到，并在本机复跑：

- 新增商品写入 `OPENING_BALANCE`。重复条码返回 409，不会覆盖已有库存。
- 修改名称和售价不改变 `stock`，也不新增库存流水。
- 库存调整必须带原因，写入流水。减少后如果低于 0 或低于已预留数量，返回 409，账面不变。数量 0 返回 422。
- 已有订单时，CSV 确认导入仍是 409；同一时刻单品新增、改价和调整仍然成功，总账 `balanced=true`。
- 管理页有这三组表单，沿用管理员 Cookie 和 CSRF。顾客页没有退款按钮。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**50 passed，1 warning，4.97s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。50 = 上一轮 48 + 本增量 2。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0。在已经产生订单并完成模拟退款之后，脚本新增条码 `6900000099991`、把售价改掉且状态含「库存仍为 4」、再按「到货入库」调到「库存已调整为 6」，流水仍含「一致」。390 宽 `scrollWidth` 390，1440 宽 `scrollWidth` 1440，`pageerror` 为空。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是真实收款。

## 本增量（商品 CSV、求助处理、虚拟进门列表）

已在代码和测试里做到，并在本机复跑：

- `GET /api/admin/export-products` 导出 `barcode,name,price,stock`。同一文件可以预览导入，预览不改库存。坏行整表拒绝，已有订单时确认导入仍返回 409，库存合计不变。权威仍是本库 SQLite。
- 员工可以把求助标成 `ACKNOWLEDGED` 或 `RESOLVED`。重复标记是幂等的。已处理后不能改回确认。响应保持 `physical_door_opened=false`、`payment_required_to_leave=false`，门禁事件条数不变。
- 管理页单独列出 `SESSION_ISSUED` 等虚拟进门记录，并写 `physical_door_opened=false`。没有新增开锁按钮。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**48 passed，1 warning，4.64s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。48 = 上一轮 46 + 本增量 2。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0：390 宽 `scrollWidth` 390；管理页出现 `SESSION_ISSUED` 和 `physical_door_opened=false`；求助被点成「已确认」；随后模拟退款仍显示「模拟退回」；`pageerror` 为空；1440 宽 `scrollWidth` 1440。导出按钮没有在这次浏览器脚本里点击，导出列由 pytest 核对。这仍不是真机，也不是微信退款。

## 本增量（管理端流水、模拟退款、顾客求助、示例库路径）

已在代码和测试里做到，并在本机复跑：

- 管理页读取 `GET /api/admin/inventory-ledger`，显示账面、预留、流水合计和是否一致，并写明权威是本库 SQLite。
- 管理页对 `MOCK_NOT_REAL_MONEY` 且 `verified` 不是 1 的已付订单提供「模拟退款」。顾客页没有这个按钮。桥接脚本点过后，订单资金列变为「模拟退回」。已验签金额显示 ¥0.00，模拟销售额单独显示。
- 顾客可 `POST /api/help` 留下文字、时间和可选的会话/订单。员工在管理页能看到。响应里 `physical_door_opened=false`、`payment_required_to_leave=false`。求助不增加门禁事件。
- `.env.demo.example`（以及 `init_env.py` 所复制的 `.env.example`）使用 `./data/demo/openretail.sqlite3`，预发和正式示例分别使用 `./data/staging/` 与 `./data/production/`。没有迁移或删除已有数据库文件。

`/tmp/openretail-venv/bin/python -m pytest -q`（工作目录 `/workspace`，Python 3.12.3）：**46 passed，1 warning，4.36s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。46 = 上一轮 44 + 本增量 2。

`scripts/ui_bridge_smoke.py` 在去掉密钥环境变量后退出码 0：390 宽 `scrollWidth` 390；未付款与「模拟支付成功 · 非真实扣款」文案仍在；管理端已付订单数为 1、已验签金额为 ¥0.00；求助文案「请到货架帮忙」和「不会打开实体门」出现；流水核对含「一致」；模拟退款后订单表含「模拟退回」；`pageerror` 为空；1440 宽 `scrollWidth` 1440。这仍是 Chrome 到 TestClient 的桥，不是真机，也不是微信退款。

## 本增量（顾客界面、演示启动、虚拟门事件）

已在代码和测试里做到，并在本机复跑：

- 导入 `openretail.main` 不再立刻 `create_app()`。干净进程里演示档可以不带密钥完成导入；真正创建应用时，缺的演示密钥只生成在内存中，并把一次性 `ADMIN_KEY` 打到标准错误，不写磁盘。`APP_MODE=staging` 且没有配置时，访问 `app` 仍会失败。`LIVE_DOOR_ENABLED=true` 仍拒绝启动。
- 顾客页显示未付款、已超时、模拟支付成功（非真实扣款）和 `real_money=false`。购物车有一步「模拟结算」。没有顾客自助退款按钮。
- 演示进店写入 `SESSION_ISSUED`，员工邀请兑换写入 `CHECKOUT_SESSION`，模拟开门仍是 `SIMULATED`。这些记录的 `physical_door_opened` 都是 false。

`scripts/ui_bridge_smoke.py` 在去掉 `ADMIN_KEY`、`INTEGRATION_KEY`、`APP_SECRET` 后退出码 0：8 个商品；390 宽 `scrollWidth` 为 390；未付款文案含订单金额；支付文案为「模拟支付成功 · 非真实扣款」；订单列表含 `real_money=false`；进门状态含「实体门未打开」；`pageerror` 为空；1440 宽 `scrollWidth` 为 1440。这仍是 Chrome 到 TestClient 的桥，不是真机。

随后的 pytest（`/tmp/openretail-venv/bin/python -m pytest -q`，工作目录 `/workspace`，Python 3.12.3）：**44 passed，1 warning，4.29s，退出码 0**。警告仍是 Starlette 的 `httpx` TestClient 弃用提示。44 = 上一轮 41 + 本增量 3（`tests/test_customer_ux.py`）。下面保留的 41 是更早一次运行，不是当前总数。

## 店主决定（2026-11-06）

库存系统权威是本仓库的 SQLite。这是已决定的事实，不是建议。OSPOS 与 ERPNext 不得作为第二套权威去扣减同一库存。OSPOS 以后只可再评估为可选适配器。详见 `DECISIONS.md`。

## 随后实现的模拟支付与库存流水

在上述决定之后，演示模式增加了本地沙箱，不访问 `api.mch.weixin.qq.com`：

- `POST /api/orders/{id}/mock-checkout`：进入本地 `PAYMENT_PENDING`，引用以 `mock:` 开头。
- `GET /api/orders/{id}/mock-payment` 与 `POST /api/admin/orders/{id}/reconcile-mock`：查本地状态。
- `POST /api/admin/orders/{id}/mock-close`：关闭未支付的本地单并释放预留。
- 超时：`PENDING`，以及 `payment_reference` 以 `mock:` 开头的 `PAYMENT_PENDING`，到期后释放库存。微信 `PAYMENT_PENDING`（`weixin://` 或尚未写回引用）不会被这个计时器释放。
- `POST /api/payments/mock-notify`：按 `event_id` 幂等确认。重复事件或已支付后再通知，不会第二次扣库存。
- `POST /api/payments/mock-confirm`：仍是一步模拟确认。记账名 `MOCK_NOT_REAL_MONEY`，`payments.verified=0`。
- `POST /api/admin/orders/{id}/mock-refund`：只接受未核验的模拟支付，把 SQLite 库存加回，订单变为 `REFUNDED`。重复退款不重复加库存。已核验或非模拟支付返回 409，不会调用机构退款。
- `GET /api/admin/inventory-ledger`：用库存流水合计核对 `stock` / `reserved_stock`。没有流水的商品在初始化时补一条 `OPENING_BALANCE`。

这些行为由 `tests/test_mock_ledger.py` 覆盖，包括并发抢一件库存、取消释放和退款回补。支付宝没有新增。`LIVE_DOOR_ENABLED` 仍会拒绝启动。

该增量之后的 pytest（工作目录 `/workspace`，Python 3.12.3）：

```bash
/tmp/openretail-venv/bin/python -m pytest -q
```

**41 passed，1 warning，3.19s，退出码 0。** 警告仍是 Starlette 对 `httpx` TestClient 的弃用提示。41 = 原有 35 + 新增 6。同一命令在实现刚完成时是 3.56s，文档定稿前再跑一次是 3.19s，两次都是 41 passed、退出码 0。

## 第一次源码复核（改业务代码之前）

下面这一节是同一天较早的只读复核。当时还没有模拟查单、关单、退款和总账接口。表里的「没有退款代码」描述的是那一次，不是现在。

## 本次实际跑过的命令

环境：Linux，Python 3.12.3。干净机器上没有 `python3-venv`，先安装了系统包 `python3.12-venv`，没有改仓库。

```bash
python3 -m venv /tmp/openretail-venv
/tmp/openretail-venv/bin/pip install -r requirements-dev.txt
/tmp/openretail-venv/bin/python -m pytest -q
```

工作目录 `/workspace`。结果：**35 passed，1 warning，2.61s，退出码 0**。唯一警告是 Starlette 提示 `TestClient` 仍使用 `httpx`、建议改用 `httpx2`，不是失败，也没有因此改代码。测试文件合计 35 个用例（`test_business.py` 11、`test_integrations.py` 6、`test_ops.py` 8、`test_v2.py` 10）。

另外：

- `node --check web/app.js` 退出码 0。
- `/tmp` 里用演示库执行 `scripts/backup.py` 与 `scripts/restore.py`：备份 `integrity_check=ok`（139264 bytes）；恢复到另一个文件，`products=8`、`orders=0`、一致性 PASS；再恢复到活动库被拒绝，退出码 1。没有替换任何业务库，产物留在 `/tmp`，未提交。
- 本机没有 `docker` 或 `docker-compose` 命令，所以没有执行 `docker compose config`，也没有启动容器。
- 文档里的 `python scripts/ui_bridge_smoke.py` 在干净环境直接失败：`openretail/main.py` 在导入时调用 `create_app()`，而当时没有密钥。随后只在**进程环境变量**里放入与该脚本相同的演示密钥（未写 `.env`、未提交），再跑脚本，退出码 0。见下表。

## 先前声称对照

| 声称 | 本次结论 |
|---|---|
| pytest 35/35 PASS | **证实。** 计数、命令和警告见上。`docs/VERIFICATION.md` 里的 27/27 是 2026-11-04 旧记录，不要再当成当前结果。 |
| 顾客扫码 + 模拟支付的浏览器流程 | **部分证实。** 桥接脚本在补上演示环境变量后通过：8 个商品；390 宽时 `scrollWidth` 为 390；服务端金额 ¥2.00；页面文案是「模拟支付成功 · 已原子扣库存」；管理端已付订单数为 1；`pageerror` 为空；1440 宽时 `scrollWidth` 为 1440。这是本机 Chrome 把 `fetch` 转到 FastAPI `TestClient`，不是公网 HTTPS、不是顾客手机、也不是微信里打开。干净工作区直接跑文档命令会失败。 |
| 付款后库存减少 | **证实（自动化）。** `test_purchase_and_duplicate_pay` 断言模拟支付后 `stock` 减少下单数量。微信用例在 `MockTransport` 验签成功后把库存从 2 减到 1。UI 脚本只打印了「已原子扣库存」文案，没有单独打印库存数字。 |
| 数据库备份/恢复演练 | **证实（隔离文件）。** pytest 的 `test_restore_is_isolated_and_consistent` 通过，并且上面的脚本演练通过。没有在停机窗口换上生产库。 |
| demo / staging / production 隔离 | **部分证实。** 测试证明三档的启动校验不同：非 demo 拒绝模拟支付和匿名访客，`LIVE_DOOR_ENABLED` 一律拒绝。三份示例文件的 `DB_PATH` 都是 `./data/openretail.sqlite3`。本次没有同时跑起三套进程。 |
| STAFFED 模式 | **证实为默认营业模式，不是已开业的有人店。** 建库时 `store_settings.mode=STAFFED`。非 demo 拒绝改成 `UNATTENDED`。有人值守结账邀请码在 TestClient 里可用，有效期 120 秒、一次性，且 `identity_verified=false`、`door_authorized=false`。 |
| 微信支付 APIv3 部分适配 | **代码和离线密码学测试证实；真实商户未接通。** 路径与本次读到的官方文档一致，见 `API_INVENTORY.md`。测试密钥是临时生成的，流量停在 `MockTransport`。没有退款代码。没有支付宝代码。 |
| 管理端认证 + CSRF | **证实。** Cookie 会话、错误 CSRF 返回 403、登出后 401、连续失败锁定 429，均在 pytest 中通过。demo 仍可用 `X-Admin-Key`；staging/production 示例要求密码哈希。 |
| 健康检查 | **HTTP 路由证实，容器探针未跑。** `/api/health` 在测试里返回 `real_door=false`。`/api/readiness` 固定 `unattended_approved=false`。Compose 里的 healthcheck 没有实际执行。 |
| Home Assistant / Frigate 桩接口 | **单测证实，设备未接通。** HA `unlock()` 在门禁开关关闭时返回 `SIMULATED`。Frigate 接口只存 `person`，并返回 `theft_detected=false`。没有 MQTT broker、摄像头或 HA 实例。 |
| 真实支付未启用 | **证实。** 示例 `PAYMENT_PROVIDER=disabled`。模拟支付的 provider 是 `MOCK_NOT_REAL_MONEY`，`payments.verified=0`，后台把这笔钱放进 `simulated_revenue_cents`，不放进 `verified_revenue_cents`。 |
| 实体门锁禁止 | **证实。** `LIVE_DOOR_ENABLED=true` 时进程拒绝启动。Compose 再次把它写成 `false`。演示开门返回 `physical_door_opened=false`。健康检查里的 `real_door` 是写死的 `false`。 |
| Compose 配置已校验，但 Docker 引擎没跑 | **「引擎没跑」证实；「配置已校验」本次不能复核。** 本机没有 Docker 命令。只阅读了 `docker-compose.yml`：发布地址是 `127.0.0.1:8000`，强制 `LIVE_DOOR_ENABLED=false`，只读根文件系统、丢弃全部 capabilities、单服务。`env_file: .env`，而仓库里没有 `.env`。 |

## 代码里已经有、本次没有改的行为

- 库存账本是这一进程里的 SQLite：`stock` 是账面数量，`reserved_stock` 是未结算占用，可售数是二者之差。下单用 `BEGIN IMMEDIATE` 预留；模拟支付或验签成功的微信结果在同一事务里扣减账面和预留。有订单之后，全量 CSV 覆盖库存会被拒绝。
- OSPOS 只是 CSV 列名适配。ERPNext 只读 `Item` 预览，且 `ready_for_sale=false`。二者都不是第二套正在运行的库存权威。
- `docs/VERIFICATION.md` 写「尚未执行线下恢复演练」。那是 2026-11-04 的句子。2026-11-06 的隔离恢复演练已经做过，见上。

## 下一步（尚未做到）

1. 真实微信仍未联调。官方域名还是 `api.mch.weixin.qq.com`。本地 `MockTransport` 和 `mock:` 沙箱都不是微信沙箱验收。真实退款和日终账单仍没有。
2. 顾客页仍然没有模拟退款按钮；退款仍只在管理端 API。桥接脚本已能在干净环境导入，但不是公网或真机验收。
3. 有人值守试点前先过 `PRODUCTION_GATE.md` 的 A 节。无人值守保持关闭。
4. 店内运行放在本地机器上。这台开发用云端虚拟机不是门店运行时。
