# WMS Backend API 接口文档 - v1.1 更新

**版本:** 1.1 (2026-08-30)

## 创建订单时生成首版报价

- `POST /api/create` 新增 `salesman_id` 和可选的 `quote` 字段。
- `quote` 包含 `unit_price`、`surcharge`、`quote_remark`；提供时，创建订单后复用报价服务自动生成第 1 版报价。
- 首版报价的 `quoter_id`、`quoter_name` 取 `salesman_id` 对应的业务员，不取请求操作人；实际操作人继续记录在审计日志中。
- 报价字段会在订单写入前完成格式校验。
