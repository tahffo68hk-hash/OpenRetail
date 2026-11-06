# 决策记录

只记录已经生效的约束，以及明确还没拍板的事项。建议写在 `TECH_ROADMAP.md`，不写进本文件当结论。

复核日期：2026-11-06。决策生效日：2026-11-06。

## 已生效

### 库存权威是本仓库的 SQLite

**状态：店主已于 2026-11-06 决定。**

OpenRetail 的库存系统权威（system of record）就是本仓库自己的 SQLite。下单预留、支付扣减、取消释放、超时释放和模拟退款回补，都只写这一份账本。

不要把 OSPOS 或 ERPNext 当成第二套库存权威，去独立扣减同一批库存。OSPOS 以后只可以作为可选适配器再评估。ERPNext 现在不引入。

CSV 导入和 ERPNext 的只读 Item 预览都不是权威账。有订单之后，全量 CSV 不得覆盖库存。

### 真实收款和实体开锁必须另获店主批准

**状态：已生效，且本次维持关闭。**

未获店主对具体商户号、回调域名和金额路径的批准之前，不启用真实支付。未获店主对门体、消防疏散和合格门禁设备的批准之前，不启用实体开锁。

代码已经按这个方向失败关闭：

- `PAYMENT_PROVIDER` 只接受 `disabled` 或 `wechat_native`。三份示例都是 `disabled`。demo 若打开模拟支付，记账名是 `MOCK_NOT_REAL_MONEY`，`verified=0`。
- 非 demo 不允许 `MOCK_PAYMENTS_ENABLED=true`。
- `LIVE_DOOR_ENABLED=true` 会在启动时抛错。`docker-compose.yml` 再次把该变量写成 `false`。
- `/api/health` 的 `real_door` 固定为 `false`。`/api/readiness` 的 `unattended_approved` 固定为 `false`。

本次没有打开这两项，也没有连接微信商户或任何锁。

### 仓库已经是公开仓库

**状态：已核实。**

2026-11-06 用只读的 `gh repo view tahffo68hk-hash/OpenRetail --json visibility,isPrivate` 得到 `visibility=PUBLIC`、`isPrivate=false`。地址：`https://github.com/tahffo68hk-hash/OpenRetail`。

因此：

- 不提交 `.env`、API 密钥、商户私钥、证书、`*.pem`、`*.key`、生产库、顾客库或备份。
- `.gitignore` 已经忽略 `.env`、`*.sqlite3*`、`*.pem`、`*.key` 和 `backups/`。示例文件只含占位符。
- 操作者另一台电脑上的 LLM 密钥只留在那台机器，不复制进本仓库。清单见 `API_INVENTORY.md`，其中没有密钥值。

### 完全无人值守不批准

**状态：NOT_APPROVED。**

有人值守的代码路径（员工签发 120 秒结账邀请）存在，但也不等于已经可以收真实的钱。无人入店、无人看店、把付款当成出门条件，都未批准。`scripts/doctor.py` 会打印「无人营业验收：NOT_APPROVED」。

### 上游用适配器，不把源码混进来

**状态：已生效。**

OSPOS、Home Assistant、ESPHome、Frigate、ERPNext 都只在本仓库留下接口、示例或只读客户端。不要把它们的源码拷进这棵树。OSPOS 的页脚署名和 ERPNext 的 GPLv3 在二次分发上游本身时另行遵守；本仓库的 `LICENSE` 只覆盖 OpenRetail 自己的代码。

### 不启动付费计划和真实扣款

**状态：已生效。**

不购买云套餐，不升级付费 API，不绑定被控制台要求添加的银行卡，不打开 Cloudflare Workers Paid，不把模拟支付说成真实交易。
