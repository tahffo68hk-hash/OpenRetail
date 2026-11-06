# API 与外部服务清单

日期：2026-11-06。凡是「本次验证」，都指本仓库这台云端环境里实际跑过或实际打开过的官方页面。没有调用任何需要密钥的外部服务，也没有把密钥写进仓库。

「真正可用」指今天能不能拿来完成门店动作，不是指源码文件是否存在。

## 本仓库里的集成

### OpenRetail HTTP API（本进程）

- 用途：商品、库存预留、订单、模拟支付、管理登录、健康检查。实现在 `openretail/main.py`。
- 官方文档：无外部文档。行为以源码和 `tests/` 为准。demo 模式才暴露 `/docs`。
- 是否真正可用：本地 TestClient 可用。没有对外发布的服务。
- 免费额度/限制：单机 SQLite，一个写入进程。不是多店接口。
- 店主授权/密钥：运行前需要 `ADMIN_KEY`、`INTEGRATION_KEY`、`APP_SECRET`（各至少 24 字符）。staging/production 还要密码哈希、`https://` 的 `PUBLIC_BASE_URL` 和 `TRUSTED_PROXY_TLS=true`。
- 是否可能产生费用：进程本身不扣款。
- 本次验证：pytest 35 passed。`/api/health` 在 demo 测试中 `real_payment=false`、`real_door=false`。

### 微信支付 APIv3 Native

- 用途：另一台设备上的收款二维码。代码在 `openretail/wechat.py`。本服务入口是 `POST /api/orders/{id}/wechat-native`、`POST /api/payments/wechat-notify`、`POST /api/admin/orders/{id}/reconcile-wechat`。
- 官方文档（2026-11-06 打开）：
  - 下单 `POST /v3/pay/transactions/native`：<https://pay.weixin.qq.com/doc/v3/merchant/4012791877>
  - 查单 `GET /v3/pay/transactions/out-trade-no/{out_trade_no}?mchid=`：<https://pay.weixin.qq.com/doc/v3/merchant/4012791880>
  - 关单 `POST /v3/pay/transactions/out-trade-no/{out_trade_no}/close`：<https://pay.weixin.qq.com/doc/v3/merchant/4012791881>
  - 支付成功回调（`AEAD_AES_256_GCM`，应答需验签）：<https://pay.weixin.qq.com/doc/v3/merchant/4012791882>
  - 回调与查单指引：<https://pay.weixin.qq.com/doc/v3/merchant/4012075249>
  - 文档中的主域名是 `https://api.mch.weixin.qq.com`。授权方案示例为 `WECHATPAY2-SHA256-RSA2048`。
- 是否真正可用：**不能用来收真钱。** 适配器覆盖了上述三个商户接口和回调验签/解密，默认 `PAYMENT_PROVIDER=disabled`。官方要求商户订单号 6–32 位；本仓库用 32 位十六进制订单号。没有 JSAPI、小程序、H5，也没有微信退款。演示模式另有本地 `mock:` 查单、关单、超时、幂等通知和模拟退款，只改 SQLite，`verified=0`，不访问微信。本次没有在官方文档里确认一个仍可用的免扣款沙箱域名，所以 `MockTransport` 和 `mock:` 都不能称作微信沙箱验收。
- 免费额度/限制：查单文档列出 `429 FREQUENCY_LIMITED`。没有公开的「免费调用包」。真实成功交易按微信支付规则收费。
- 店主授权/密钥：需要商户号、AppID、商户证书序列号、商户私钥文件、平台公钥或平台证书、APIv3 密钥（代码要求 32 字节）和 HTTPS 回调。这些都要店主申请，不能放进 Git。
- 是否可能产生费用：**会。** 一旦对真实用户下单并支付，就是真实资金和手续费。在店主批准前保持 `disabled`。
- 本次验证：`test_signed_wechat_native_flow_and_reconciliation` 用本地 RSA 密钥和 `MockTransport` 通过。没有 DNS 请求打到 `api.mch.weixin.qq.com`。

### 支付宝

- 用途：无。README 把它列为未完成项。
- 官方文档：本次不编造接口。
- 是否真正可用：不可用。仓库内没有支付宝客户端、回调或配置项。
- 免费额度/限制：不适用。
- 店主授权/密钥：不适用。
- 是否可能产生费用：当前代码路径不会。
- 本次验证：在 `openretail/` 搜索无支付宝实现。

### Home Assistant REST

- 用途：连通性检查和可选事件发布。`HomeAssistantAdapter` 请求 `GET {HA_URL}/api/` 和 `POST {HA_URL}/api/events/{event_type}`。`unlock()` 在开关关闭时返回 `SIMULATED`，打开开关则被配置层拒绝。
- 官方文档（本次打开）：
  - REST：<https://developers.home-assistant.io/docs/api/rest/>
  - 锁实体（`lock.lock` / `lock.unlock` / `lock.open`，由其他集成提供）：<https://www.home-assistant.io/integrations/lock/>
  - 二进制传感器，含 `device_class: door`（开/关）：<https://www.home-assistant.io/integrations/binary_sensor/>
- 是否真正可用：本仓库不能控锁。官方 REST 可以读状态、调 service、发事件；锁动作必须来自单独安装的锁集成。OpenRetail 没有调用 `lock.unlock`。告警应走官方 `notify` 一类集成，本仓库没有接上。
- 免费额度/限制：软件本地自建，没有供应商调用配额。远程访问若使用付费云，本次没有核价，也不要开通。
- 店主授权/密钥：长期访问令牌由店主在自己的 Home Assistant 里签发。示例里 `HA_ENABLED=false`，令牌为空。
- 是否可能产生费用：自建软件本身不收费。不要为了这个项目去买远程访问套餐。
- 本次验证：`test_ha_no_real_unlock` 通过。没有运行 Home Assistant。

### ESPHome

- 用途：只读门磁示例，`integrations/esphome/door_contact_READ_ONLY.example.yaml`。GPIO 二进制传感器，`device_class: door`。文件写明不是锁控制器。
- 官方文档（本次打开）：
  - 产品说明（自制设备、常用 ESP32、本地控制）：<https://esphome.io/>
  - GPIO 二进制传感器：<https://esphome.io/components/binary_sensor/gpio/>
  - 二进制传感器与 `device_class`：<https://esphome.io/components/binary_sensor/>
- 是否真正可用：示例未烧录，不能当前使用。官方定位是自制智能家居固件。商业门的生命安全不能只靠这段 DIY ESP32 逻辑；应急出门必须由合格门禁和现场电气完成。
- 免费额度/限制：固件可本地使用。没有云配额。
- 店主授权/密钥：Wi-Fi 和 API encryption key 用 ESPHome `!secret`，不进 Git。
- 是否可能产生费用：固件不收费。硬件采购另计，且本次不采购。
- 本次验证：只阅读了示例 YAML 和官方页面。没有编译或刷写。

### Frigate 与 MQTT

- 用途：本地 NVR 的人形/活动事件。`workers/frigate_mqtt.py` 订阅 `frigate/events`，把 `type` 为 `new`、`update` 或 `end` 且 `label=person` 的消息转到 `POST /api/integrations/frigate-event`。其他 label 不转发。返回值包含 `theft_detected=false`。管理页把已存的 person 事件显示为「有人」。
- 官方文档（本次打开）：
  - 项目：<https://github.com/blakeblackshear/frigate>（本地 NVR，IP 摄像头实时目标检测）
  - MQTT：<https://docs.frigate.video/integrations/mqtt/>（`frigate/events` 的 `new` / `update` / `end`；示例 `label` 可为 `person`）
- 是否真正可用：不能。没有 broker、没有摄像头、没有跑 worker。`person` 是目标类别，不是偷盗或未付款商品判定。
- 免费额度/限制：软件本地运行。可选的付费模型订阅本次没有打开价目页，不要开通。
- 店主授权/密钥：broker 账号和 `INTEGRATION_KEY` 放在未提交的 `.env`。`requirements-optional.txt` 才包含 `paho-mqtt`，默认测试依赖不含它。
- 是否可能产生费用：自建不产生 API 账单。摄像头和硬盘是硬件，本次不买。
- 本次验证：HTTP 接口单测通过（未授权 401、重复事件不重复入库、`car` 不入库）。没有连接 MQTT。

### ERPNext / Frappe REST

- 用途：只读预览 `GET {ERPNEXT_URL}/api/resource/Item`，字段仅 `item_code`、`item_name`、`disabled`。响应标明 `ready_for_sale=false`，不同步价格、条码、库存或订单。
- 官方文档（本次打开）：
  - REST（`Authorization: token api_key:api_secret`，`/api/resource/:doctype`）：<https://docs.frappe.io/framework/user/en/api/rest>
  - Item 文档：<https://docs.frappe.io/erpnext/item>
  - 仓库许可证文件开头为 GNU GPL 3.0：<https://github.com/frappe/erpnext>
- 是否真正可用：不能作为本店库存权威，也不建议现在部署。官方 REST 可以读写 DocType，但那会变成第二套账。本仓库客户端只做了 Item 列表预览。
- 免费额度/限制：自建没有供应商配额。Frappe Cloud 一类托管是另一条付费路径，不要开通。
- 店主授权/密钥：需要店主自己的站点、API key 和 secret。示例为空。
- 是否可能产生费用：自建软件不直接扣款；托管和多余的服务器会花钱。当前调用未配置，测试使用 `MockTransport`。
- 本次验证：`test_erpnext_frappe_readonly_api` 通过。没有 ERPNext 站点。

### OSPOS

- 用途：商品、条码、销售和库存的候选上游收银。本仓库只解析类似导出的 CSV（`item_number`、`name`、`unit_price`、`quantity` 等列名），见 `openretail/importer.py` 和 `examples/ospos_import_sample.csv`。有订单后禁止全量覆盖库存。
- 官方文档（本次打开）：
  - 仓库与 README：<https://github.com/opensourcepos/opensourcepos>
  - README 写明 PHP、MySQL/MariaDB，功能包括库存、销售登记、条码生成、客户和进货。README 的功能列表里没有稳定的外部 API。
  - 许可证要求保留每个页面上的页脚署名：<https://github.com/opensourcepos/opensourcepos/blob/master/LICENSE>
  - REST API 讨论：<https://github.com/opensourcepos/opensourcepos/issues/2463>
  - 实现 PR：<https://github.com/opensourcepos/opensourcepos/pull/4408>。2026-11-06 该 PR 状态为 **open**。页面上的审查意见写明提交版本还不能用、测试在 CI 失败。本环境没有部署 OSPOS 去复现那条审查，因此结论只是：不能把外部 API 当成已合并、已稳定的接口。
- 是否真正可用：CSV 导入代码可用；实时商品/销售/库存 API 不可用。不要假设存在稳定外部 API。
- 免费额度/限制：自建软件，无供应商配额。页脚署名是许可证条件，不是费用。
- 店主授权/密钥：若以后自建 OSPOS，数据库和管理员账号由店主保管。本仓库不保存这些。
- 是否可能产生费用：软件本身按该 MIT 许可证使用。主机和运维另计。
- 本次验证：CSV 单测通过。没有安装 OSPOS，没有拿它的真实导出文件导入。

### SQLite

- 用途：当前进程内的商品、订单、支付、流水和会话存储。`openretail/database.py`。
- 官方文档：Python 标准库 `sqlite3`，备份用 `Connection.backup`。
- 是否真正可用：对单进程演示和测试可用。不是多副本，也不能放在 NFS 上。
- 免费额度/限制：本地文件。
- 店主授权/密钥：数据库文件本身要限制权限。不要提交。
- 是否可能产生费用：否。
- 本次验证：pytest 覆盖预留、扣减、迁移和恢复；`/tmp` 备份恢复演练通过。

### Docker Compose

- 用途：单容器、环回端口、强制关锁的部署草稿。`docker-compose.yml`、`Dockerfile`。
- 官方文档：本次未运行 Docker，故不引用某次本机 `docker compose config` 的输出。
- 是否真正可用：在这台机器上不可用。
- 免费额度/限制：不适用。
- 店主授权/密钥：Compose 读取未提交的 `.env`。
- 是否可能产生费用：否。
- 本次验证：阅读了 YAML。`command -v docker` 与 `command -v docker-compose` 均为空。先前「配置已校验」的说法本次不能复核。

## 操作者另一台 Grok Bot 计算机上的免费 LLM / 开发能力

这些条目**只**存在于操作者单独的那台电脑上的环境变量或本地文件。它们不是 OpenRetail 的依赖，门店运行时也不要调用它们。

本次 OpenRetail 云端检查**没有**读取那些文件，**没有**复现这些调用，**没有**复制任何密钥。下面的「已验证」是任务说明里给出的、日期为 2026-11 的操作者记录，不是本仓库这次跑出来的结果。不要把任何 key 粘贴进 Git、Issue 或日志。

| 服务 | 用途 | 官方记录中的状态（操作者提供，本环境未复测） | 费用 | 店主/操作者密钥 | 本次 OpenRetail 环境 |
|---|---|---|---|---|---|
| Google Gemini / AI Studio | 开发辅助 | 经 OmniRoute 可用；模型 `gemini-3.5-flash-lite`；账单为免费；没有开通付费计划 | 按该记录为免费档 | 只在那台电脑 | 未调用 |
| Mistral | 开发辅助 | 可用：`open-mistral-nemo`、`ministral-8b-latest`；Free plan；`mistral-small` 出现过一些 429 | 免费档；429 是限流不是升级理由 | 只在那台电脑 | 未调用 |
| OpenRouter | 开发辅助 | 可用；`is_free_tier true`；余额 $0；`:free` 大约 20 RPM / 50 RPD | 不要充值 | 只在那台电脑 | 未调用 |
| SambaNova | 开发辅助 | 可用；`gemma-4-31B-it`；未绑卡。文档声称的免费档约 20 RPM / 20 RPD / 200K TPD。控制台会提示加卡 | **不要加卡** | 只在那台电脑 | 未调用 |
| Cloudflare Workers AI | 开发辅助 | 可用；`@cf/meta/llama-4-scout-17b-16e-instruct`；每天 10,000 Neurons，00:00 UTC 重置。超出后若开 Workers Paid 约为 $0.011 / 1,000 Neurons | **不要开付费** | 只在那台电脑 | 未调用 |
| Cloudflare Playground | 开发辅助 | 无密钥；此前验证过 | 按无密钥用法 | 不需要把密钥放进本仓库 | 未调用 |
| AI Horde | 开发辅助 | 匿名；此前验证过；没有原生工具调用 | 匿名免费档 | 不把令牌写入本仓库 | 未调用 |
| SiliconFlow | 开发辅助 | 有密钥，但 2026-11 为 `credits_exhausted` / HTTP 402 | 不可用；不要充值来打通 | 只在那台电脑 | 未调用 |
| DeepInfra | 开发辅助 | 密钥闲置，因为余额 $0 且没有免费推理 | 不要充值 | 只在那台电脑 | 未调用 |
| Groq | 开发辅助 | 从云 IP 注册被拦 | 未开通 | 无可用密钥可复制 | 未调用 |
| NVIDIA NIM、Fireworks | 开发辅助 | 手机 OTP 受阻 | 未开通 | 无 | 未调用 |
| ModelScope | 开发辅助 | GitHub Mobile 批准受阻 | 未开通 | 无 | 未调用 |
| Hugging Face | 开发辅助 | 跳过（这条路径没有 Google SSO；免费推理需要额度） | 不要为了推理去买额度 | 无 | 未调用 |

上表的 RPM/RPD/TPD、Neurons 和单价都来自操作者记录，本次没有打开各家控制台复核。
