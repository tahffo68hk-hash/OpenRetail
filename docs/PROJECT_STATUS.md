# 项目状态（2026-11-06 复核）

复核对象：公开仓库 `https://github.com/tahffo68hk-hash/OpenRetail`，`main` HEAD `2e408a1fff5698e3c00aa58231e65df214cc840b`。结论只来自本次阅读、官方文档查阅和本机实际运行。更早的代理记录在被本次复现之前都算未核实。

完全无人值守经营仍是 **NOT_APPROVED**。示例配置里的真实支付和实体开锁都是关闭的。

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
2. 让 `scripts/ui_bridge_smoke.py` 在导入应用之前自行准备演示环境。页面还没有模拟退款按钮；退款目前只在 API 测试里验证过。
3. 有人值守试点前先过 `PRODUCTION_GATE.md` 的 A 节。无人值守保持关闭。
4. 店内运行放在本地机器上。这台开发用云端虚拟机不是门店运行时。
