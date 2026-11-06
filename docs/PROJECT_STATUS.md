# 项目状态（2026-11-06 复核）

复核对象：公开仓库 `https://github.com/tahffo68hk-hash/OpenRetail`，`main` HEAD `2e408a1fff5698e3c00aa58231e65df214cc840b`。结论只来自本次阅读、官方文档查阅和本机实际运行。更早的代理记录在被本次复现之前都算未核实。

完全无人值守经营仍是 **NOT_APPROVED**。示例配置里的真实支付和实体开锁都是关闭的。

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
