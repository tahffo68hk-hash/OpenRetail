# V2 验证记录（2026-11-04）

> 2026-11-06 的复核在 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。下文是历史记录：其中的 27/27 已被后来增加的测试超过，当前计数以那次实际运行的 pytest 输出为准。文中「尚未执行线下恢复演练」也只描述 2026-11-04；同日之后的隔离恢复见项目状态文档。

- 27/27 pytest 测试通过（V1回归 + V2交易/安全/迁移/离线支付签名）。
- `python -m compileall -q openretail scripts`、`node --check web/app.js` 通过。
- FastAPI 本地 HTTP 服务 `/api/health` 返回 200；SQLite `PRAGMA quick_check=ok`。
- RSA 平台响应/回调验签、AES-256-GCM 解密使用本地生成的测试密钥与 MockTransport；**没有真实微信商户请求或实际资金流动**。
- 迁移测试覆盖 V1 已结算历史订单外键、支付记录与再次启动；实际 V1 归档空订单数据库迁移也通过 FK 检查。
- `python scripts/backup.py` 在线备份生成并通过 `PRAGMA integrity_check=ok`，尚未执行线下恢复演练。
- **实际 Chromium UI 测试已在隔离测试桥完成**：用 Chromium 渲染原始 HTML/CSS/JS，浏览器网络请求通过 TestClient 进程内桥转交真实 FastAPI 路由；完成创建访客会话 → 添加商品 → 创建订单 → 模拟付款 → 管理员密码登录，390px宽/1440px宽无横向溢出，`pageerror` 0。截图为 `preview-mobile-v2.png` 和 `preview-desktop-v2.png`。可执行 `python scripts/ui_bridge_smoke.py`（需已安装 Playwright 与系统 Chromium）。
- Chromium 直接导航本地 HTTP 地址被运行环境安全策略阻断 `ERR_BLOCKED_BY_ADMINISTRATOR`；桥接测试**不等于公网 HTTPS、真实手机、真实浏览器 Cookie/CSP、视频和设备接入验收**。
- 尚未运行真实 Docker Engine、实际 RTSP 摄像头/Frigate、Home Assistant/ESPHome 设备、微信真实商户支付、ERPNext/OSPOS 实机集成或现场设备和真实手机端测试；未通过无人营业正式 Gate。
