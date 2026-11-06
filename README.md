# OpenRetail V2 · 自建小型超市交易与设备集成平台

[English](README.en.md)

> **状态：可部署的分阶段试点源码 / NOT CLEARED FOR UNATTENDED PRODUCTION。**
> 可用于本地演示、集成测试，以及在商户/支付/网络/人员审核后开展**有人值守收银试点**。
> **不能直接代替无人超市成品**：未接入已验证手机号/身份、未开真实电锁、没有完整远程人工值守、没有商品级防盗及正式退款/对账/现场消防验收。

为 20–50㎡日用百货小店设计。集成 **OSPOS CSV / ERPNext Frappe REST / Home Assistant REST / ESPHome 只读门磁 / Frigate MQTT** 五个参考开源项目的接口边界，不复制、混合它们的上游源码。

## 1. 本次已实现的完整功能

- **商品/货架**：条码、名称、价格、上下架、库存可售数；中文响应式 Web UI、USB 扫码枪输入、部分浏览器 `BarcodeDetector`。
- **订单**：服务端定价，`request_id` 幂等，单库 `BEGIN IMMEDIATE`，下单即时预留库存，取消/超时释放，结算后同时扣总库存和预留库存，库存流水和订单审计。
- **支付**：演示模式使用 `MOCK_NOT_REAL_MONEY`；提供微信支付 APIv3 **Native QR 适配器**（RSA-SHA256 请求签名、平台回包/通知验签、AES-256-GCM 通知解密、金额/商户/币种校验、重复通知幂等），人工发起的商户查单与超时关单后释放库存。**未用真实商户凭证完成实付验证，也不含微信或支付宝退款。** 演示模式可以本地查单、关单、超时释放、幂等确认，以及模拟退款（只把 SQLite 库存加回，`verified=0`），这些都不会访问 `api.mch.weixin.qq.com`。
- **管理员**：PBKDF2 密码哈希、HttpOnly/SameSite Cookie、CSRF 保护、失败登录锁定、审计、库存/订单/事件管理；旧 `X-Admin-Key` 仅演示模式可用，正式试点禁用。
- **店内试点准入**：有人营业时，员工在后台签发 **120秒一次性结账 QR**，顾客扫码兑换1小时购物会话；不代表身份核验，不授权电锁，不能用于无人值守。
- **门禁**：Home Assistant 连通性/事件适配器，实体开锁始终 **禁止**。演示模式可以模拟门禁动作；断网/断电/应急离店属于现场专业硬件验收项。
- **监控**：Frigate `frigate/events` MQTT 桥接，可展示人形检测事件，不能判定偷盗；ESPHome 示例仅示意只读门磁。
- **进销存桥接**：OSPOS 风格 CSV 首次导入；产生订单后拒绝覆盖库存；ERPNext 的 `Item` 只读 REST 预览。禁止把 OSPOS、ERPNext 和 OpenRetail 三套库存同时视为权威。
- **自托管**：SQLite WAL 单实例、自动数据结构升级、离线测试、Docker Compose 单实例/非 root/loopback、SQLite 在线备份工具、健康检查、部署检查脚本。

## 2. 配置档

`APP_MODE` 只有三档。`pilot` 仍可作为 `staging` 的旧别名。

| 档 | 用途 | 模拟支付 | 实体开锁 |
|---|---|---|---|
| `demo` | 本机演示 | 允许，状态是 `MOCK_NOT_REAL_MONEY` | 启动时拒绝 |
| `staging` | 有人值守预发 | 拒绝，不能当成真实交易 | 启动时拒绝 |
| `production` | 正式环境 | 拒绝 | 启动时拒绝，Compose 也强制 `LIVE_DOOR_ENABLED=false` |

示例：`.env.demo.example`、`.env.staging.example`、`.env.production.example`。真实密钥只放在未提交的 `.env`。

## 3. Windows 本地启动、停止、备份和恢复

前提 Python 3.11+。在 `OpenRetail_V2` 目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\init_env.py
.\.venv\Scripts\python.exe scripts\doctor.py --init-demo
.\.venv\Scripts\python.exe -m uvicorn openretail.main:app --host 127.0.0.1 --port 8000
```

`--init-demo` 只会在演示档、且业务库还不存在时建库。预发、正式，以及已有业务库，都不会被这个命令创建或覆盖。日常检查不要带这个参数：

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
```

浏览器打开 http://127.0.0.1:8000 。演示流程是生成访客会话、加商品、创建订单、模拟支付。后台演示登录使用 `.env` 里的 `ADMIN_KEY`，密钥不会写进页面。预发和正式改用管理员密码：

```powershell
.\.venv\Scripts\python.exe scripts\set_admin_password.py
```

停止服务：在运行 uvicorn 的窗口按 Ctrl+C。如果窗口已经关掉，只结束监听 8000 端口的那个进程：

```powershell
$procId = (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
Stop-Process -Id $procId
```

备份使用 SQLite 在线备份，不直接拷贝 WAL 半成品：

```powershell
.\.venv\Scripts\python.exe scripts\backup.py
```

恢复必须写到另一个文件，脚本拒绝覆盖 `DB_PATH` 指向的活动库：

```powershell
.\.venv\Scripts\python.exe scripts\restore.py --backup .\backups\openretail-时间戳.sqlite3 --dest .\restore-drill\restored.sqlite3
```

确认恢复文件的完整性输出为 PASS 后，再由人工决定是否在停机窗口替换活动库。本命令本身不会做这一步。

回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 4. Docker

默认只把端口发布到本机 `127.0.0.1:8000`，容器内单 worker，数据在命名卷里。没有 Docker Engine 时不要把配置检查当成启动成功。

```powershell
docker compose config
docker compose up --build -d
docker compose ps
docker compose exec openretail python scripts/backup.py
docker compose down
```

镜像以 SQLite 单机事务运行，不能把数据卷放到 NFS，也不能起多个写入副本。

## 5. 有人值守试点（仅在配置完成后）

1. 单独备份原数据；创建管理员密码，设置 `APP_MODE=staging` 或 `production`、`MOCK_PAYMENTS_ENABLED=false`、`TRUSTED_PROXY_TLS=true`、`PUBLIC_BASE_URL=https://你的已配置域名`。必须实际配置 HTTPS 反向代理，不能只把环境变量设为 true。`production` 同样拒绝模拟支付和实体开锁。
2. 为真实收款向微信支付申请商户资质/Native 支付权限，设置 `PAYMENT_PROVIDER=wechat_native` 与 `.env.example` 中要求的商户号、证书私钥、平台公钥、APIv3 密钥及回调地址。**绝不把私钥、证书或 `.env` 提交给 Agent 仓库或 Git**。
3. 完成官方支付测试（订单号/金额/重复回调/掉线/查单/关单/超时/退款和日终对账）。其中**退款尚未编码**，需要实现或落实独立人工退款操作规程后才能收真实款项。
4. 打开管理端，创建商品与库存，员工签发120秒一次性结账二维码，顾客扫码获取自助购物会话；在**另一台屏幕/设备**展示微信 Native 收款 QR 供顾客扫码。微信内 H5/JSAPI 同机支付当前未实现。
5. 所有已发起支付但未回调的订单，操作员可使用 `POST /api/admin/orders/{order_id}/reconcile-wechat` 查单；仅在**微信确认 CLOSED** 后释放预留。支付成功以官方回调或商户查单验签结果为准。

`staging` 和 `production` 无法匿名生成访客会话、无法切换到无人值守经营、无法控制实际电锁。这是故意设置的安全边界。`pilot` 是 `staging` 的旧别名。

## 6. 对上游项目的真实依赖与限制

| 项目 | 本仓库实现 | 需要额外部署/开发 |
|---|---|---|
| [OSPOS](https://github.com/opensourcepos/opensourcepos) | CSV 商品导入和预览 | OSPOS 必须单独部署；没有实时订单双写；需保留其特殊页脚署名要求 |
| [Home Assistant](https://developers.home-assistant.io/docs/api/rest/) | 连接检测、事件发布 | 必须单独部署，实体门禁仍禁止控制 |
| [ESPHome](https://esphome.io/) | 只读门磁配置样例 | 烧录/传感器/安全电气施工，不用自制继电器作为唯一商业门禁 |
| [Frigate](https://docs.frigate.video/integrations/mqtt/) | MQTT 事件桥接服务 | 配置 broker、摄像头、NVR 与录像容量；非商品级偷盗检测 |
| [ERPNext](https://docs.frappe.io/framework/user/en/api/rest) | Frappe `Item` 只读 API | 正式 ERP/库存/订单映射、所有权及冲突策略待定 |

OSPOS 的特殊 LICENSE 署名条件、ERPNext 的 GPLv3 和其他上游许可证应在二次分发时分别核查；本仓库未拷贝它们的源码。

## 7. 安全边界和交付验收

- **默认不发送真实收费请求**，不提供商户密钥，不连接实体门锁。
- **不能用付款作为离店先决条件**；现场电锁必须有独立应急逃生和符合所在地消防/建筑规范的供电失效策略。
- **不能仅靠 Frigate person 检测宣称防盗**。需要人工远程介入、货损盘点、顾客隐私告知和异常处置。
- 正式手机支付/支付宝、退款和结算对账、远程人工客服、手机号/身份核验、真实可控门禁、商品级防损、ERP 双向实时一致性、生产数据库 HA 均不是当前完成项。
- 安全门禁、收款资质、视频隐私、网络部署和财务对账必须结合实际地址、门体、商户与设备条件验收。

详细路径：`docs/ARCHITECTURE.md`、`docs/AGENT_HANDOFF.md`。

2026-11-06 根据源码和当次运行写的长期管理文档（中文，区分已核实和未核实）：

- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- [`docs/DECISIONS.md`](docs/DECISIONS.md)
- [`docs/API_INVENTORY.md`](docs/API_INVENTORY.md)
- [`docs/HARDWARE_PLAN.md`](docs/HARDWARE_PLAN.md)
- [`docs/PRODUCTION_GATE.md`](docs/PRODUCTION_GATE.md)
- [`docs/TECH_ROADMAP.md`](docs/TECH_ROADMAP.md)

## 8. 浏览器隔离交互验证（可选）

```bash
pip install -r requirements-ui.txt
# 需要 Chromium 已安装（系统 chromium/google-chrome 或 Playwright browser）
python scripts/ui_bridge_smoke.py
```

脚本将实际 Chromium 页面中的 HTTP 请求桥接到 FastAPI TestClient，避免测试电脑禁止 localhost 网页导航。它适合离线 UI 回归，但不替代真实域名/HTTPS/手机浏览器/支付终端验收。干净工作区可以直接运行：导入应用不会先要求密钥。真正启动 `uvicorn openretail.main:app` 时，若演示档还没有 `.env`，进程会在内存里生成一次性 `ADMIN_KEY` 并打印到标准错误，不会写进磁盘。预发和正式档仍然缺少配置就拒绝启动。
