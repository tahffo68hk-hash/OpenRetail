# 五个上游开源项目映射（独立接口集成，不复制上游源码）

| 上游项目 | 接口及许可证注意 | OpenRetail V2 现状 |
|---|---|---|
| [OSPOS](https://github.com/opensourcepos/opensourcepos) | PHP/CodeIgniter4/MySQL；其 LICENSE 额外要求保留可见页脚署名 | 仅 CSV 导入/预览；订单/库存不进行实时双写 |
| [Home Assistant](https://developers.home-assistant.io/docs/api/rest/) | 本地 REST 与事件总线；须单独部署 | 连接检查 + 状态/事件，不对真实门禁发动作 |
| [ESPHome](https://esphome.io/) | 可对接门磁等辅助设备，不能替代商业安全门禁 | 只读门磁样例，需要实际烧录/连通测试 |
| [Frigate](https://docs.frigate.video/integrations/mqtt/) | MQTT `frigate/events`，原始视频不导入本系统 | Python worker + 鉴权记录 person 事件；未实机验证 |
| [ERPNext/Frappe](https://docs.frappe.io/framework/user/en/api/rest) | GPLv3/Token REST API；部署及二次分发须核查许可 | Item 列表只读预览；不写订单库存 |

OpenRetail 是独立实现，许可证见 `LICENSE`。不能把它误描述为五套系统已经内置、一键启动或具备同等的原生功能。
