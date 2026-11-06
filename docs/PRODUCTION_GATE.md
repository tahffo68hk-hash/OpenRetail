# 投产门槛

日期：2026-11-06。HEAD `2e408a1`。

| 门槛 | 状态 | 依据 |
|---|---|---|
| 本地自动化测试 | PASS | `python -m pytest -q`：35 passed，1 warning，退出码 0 |
| 有人值守、真实收款的试点 | NOT_VERIFIED | 没有商户号、没有真实回调、没有退款、没有在店内网络跑过 |
| 完全无人值守 | **NOT_APPROVED / BLOCKED** | 代码固定 `unattended_approved=false`；非 demo 不能进入 `UNATTENDED`；实体开锁启动即拒绝 |

有人值守试点和无人值守不是同一扇门。A 节全部完成也只允许讨论「有人在店、可以收一笔真钱」。B 节未完成时，无人值守保持关闭。

## A. 有人值守试点之前还缺什么

这些都还没做。勾选权在店主和现场验收，不在这次文档更新。

- [ ] 经营主体、微信商户号、已开通的 Native 产品权限、公网 HTTPS 和可到达的回调地址。
- [ ] 在隔离环境用真实商户材料验证下单、平台验签、错误签名、重复通知、金额不符、查单、超时关单。官方查单会返回 `429 FREQUENCY_LIMITED`，需要自己的重试上限。
- [ ] 退款、`PAYMENT_REVIEW`、`PAYMENT_PENDING` 的负责人和时限。**退款路由尚未编写**，所以不能宣布可以正式收费。
- [ ] 日终对账。官方指引要求用交易账单核对，本仓库没有账单下载。
- [ ] 管理员强密码、只经 HTTPS、后台不暴露在公开店面网络、密钥轮换。
- [ ] 活动库的异地备份，以及一次在停机窗口里由人决定是否替换活动库的演练。2026-11-06 只做了**写到另一个文件**的恢复，脚本拒绝覆盖 `DB_PATH`。
- [ ] 真实商品、价格、库存和票据/限售核对。演示种子数据不是货架。
- [ ] 顾客自己的手机、微信内打开页面、断网、重复点击、回调延迟。本次浏览器结果是 Chrome 加 TestClient 桥，见 `PROJECT_STATUS.md`。

staging 与 production 的示例已经拒绝模拟支付。不要为了演示方便在这两档打开 `MOCK_PAYMENTS_ENABLED`。

## B. 完全无人值守还缺什么（现在不做）

- [ ] 真实的进店身份或手机号核验。120 秒结账邀请不是进店凭证，代码里 `identity_verified` 为 false。
- [ ] 适合该门的商业门禁、机械/电气应急释放、UPS，以及当地消防和断电失效的现场签字。
- [ ] 门禁控制器的正式集成和状态回读。付款不得作为出门条件。
- [ ] 有人的远程值守和失联处置。Frigate 的 `person` 事件不是盗损结论，接口返回 `theft_detected=false`。
- [ ] 漏扫、叠放、尾随、支付失败、老人和儿童场景的损耗评估。
- [ ] 先在有人值守下跑完一个试运营周期，再谈是否申请无人值守。店主仍可拒绝。

## C. 本次证据里已经排除的误读

- 模拟支付的 provider 字符串是 `MOCK_NOT_REAL_MONEY`，`verified=0`。它出现在 `simulated_revenue_cents`，不出现在 `verified_revenue_cents`。
- 微信测试没有离开进程：本地生成的 RSA 密钥加 `httpx.MockTransport`。
- `real_payment=true` 只表示配置里的 `PAYMENT_PROVIDER` 不是 `disabled`。示例文件是 `disabled`，因此健康检查里该项为 false。它不等于已经发生扣款。
- Docker 健康检查、真实 RTSP、Home Assistant、ESPHome 和店内 Wi-Fi 都没有在本次运行。
- 三档示例的数据库相对路径相同。隔离靠人把 demo、预发和正式放到不同机器或不同文件，本次没有启动三套服务。

## 参考

- 微信支付 Native 下单、查单、关单、回调：见 `API_INVENTORY.md` 中的官方 URL。
- OSPOS、Home Assistant、ESPHome、Frigate、ERPNext：同文件。不要把未合并的 OSPOS REST PR 当成可用 API。
