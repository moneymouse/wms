# API v1.20 — 财务账簿、结算与审计

实现日期：2026-10-05。前端入口为 `/finance`。新增 API 统一在 `/api/finance/v2`，旧订单、报价和收款路由继续保留。新账簿默认人民币，未接入的新旧数据不会自动合并为一个总额。

## 通用约定

- 使用现有 `x-token` JWT；所有新账簿接口要求 `finance` 或 `admin`。业务员可按既有数据权限查看其旧收款历史。
- 成功：`{code:200,data:...}`。列表为 `data:{items,total,page,page_size}`。查询参数使用 `p`、`s`、`q`。
- 金额返回固定两位小数字符串，单价、数量四位。金额以 `Decimal` 计算后按分舍入，拒绝 NaN/Infinity、负数和超限输入。
- 草稿更新及状态操作传 `version`；版本过期返回 HTTP 409。创建及关键命令支持 `idempotency_key`，相同键和请求返回原结果，键复用为不同内容拒绝。
- 单据、分配、会计分录和成功审计在同一事务提交。期间检查和过账共用账簿锁；MySQL 行锁并发用例需在专用测试库执行。
- 已生效单据不能原地修改金额或删除，通过关联贷项或冲销更正；核销撤销保留原记录。

## 客户、供应商、账单与资金

完整字段与命令见 [Finance v2 contract](finance-v2-contract.md)。主要路由：

| 路由 | 方法 | 用途 |
| --- | --- | --- |
| `/documents` | GET / POST | 四类账单：客户账单、供应商账单、客户贷项、供应商贷项 |
| `/documents/:id` | GET / PATCH | 详情 / 编辑草稿 |
| `/documents/:id/post` | POST | 确认生效并生成平衡凭证 |
| `/documents/:id/cancel` | POST | 记录原因，取消草稿 |
| `/documents/:id/reverse` | POST | 生成并生效完整贷项，冲抵原单未结部分 |
| `/payments`、`/payments/:id` | GET / POST / PATCH | 收付款、预收预付与退款 |
| `/payments/:id/post` | POST | 确认实际资金，生成凭证 |
| `/payments/:id/cancel`、`/reverse` | POST | 草稿取消 / 错误资金登记冲销 |
| `/allocations` | GET / POST | 多单、部分、贷项与资金核销 |
| `/allocations/:id/reverse` | POST | 保留原核销并释放对应余额 |
| `/vendors`、`/accounts` | GET / POST | 供应商及资金账户 |
| `/vendors/:id`、`/accounts/:id` | PATCH | 修改资料；有历史记录的账户身份冻结 |
| `/partners` | GET | 客户/供应商选择；历史对账可 `include_inactive=1` |
| `/dashboard`、`/aging` | GET | 账簿概览 / 未结账单账龄 |

`allocation_date` / `reversal_date` 是核销及撤销的生效日期，不能进入已关账期间，也不能造成任何历史时点余额透支。付款冲销先撤销其全部核销；已经银行匹配的资金先撤销匹配。退款上限涵盖可用贷项和未分配预收预付，扣除已经登记的退款，防止重复退款。

`is_opening=true` 仅适用于客户/供应商期初账单和正常方向的期初预收预付，记账日须等于建账日且期初尚未确认。期初单据对冲期初权益，不计入本期收入、成本或资金流水。实际现金银行期初通过期初凭证录入；期初预收预付不能银行匹配。

账龄显示正额未结账单，贷项和预收余额单列；净往来余额查往来对账单。`available_amount` 是扣除已用于退款的余额后的可核销金额。

## 会计设置、凭证与期间

以下路由前缀 `/api/finance/v2/accounting`：

| 路由 | 方法 | 说明 |
| --- | --- | --- |
| `/settings` | GET / PUT | 主体、建账日、收入政策、期初状态、版本 |
| `/opening-confirmation` | POST | `{version,reason}`，确认完整期初核对 |
| `/accounts` | GET / POST | 科目表；新增 `{code,name,account_type}` |
| `/entries` | GET / POST | 凭证列表 / 手工或期初草稿 |
| `/entries/:id` | GET | 凭证与分录 |
| `/entries/:id/post`、`/cancel`、`/reverse` | POST | 过账、作废草稿、反向凭证 |
| `/entries/:id/history` | GET | 凭证变更历史 |
| `/periods` | GET / POST | 期间列表 / `{name,date_from,date_to}` |
| `/periods/:id/checks` | GET | 关账检查结果 |
| `/periods/:id/close`、`/reopen` | POST | `{version,reason}`；重开仅管理员 |

建账：`{company_name,opening_date,revenue_policy}`。`deferred` 先确认待履约收入，履约后分次确认；`invoice` 按服务账单生效确认收入。已有生效凭证后收入政策及建账日不可直接修改。初始科目仅是基础配置，不代表替公司决定准则及税务政策。

手工凭证：`{entry_date,kind:manual|opening,description,cashflow_activity,lines:[{account_code,debit,credit,fund_account_id?,memo?}],idempotency_key}`。每行只能有一侧正额，借贷总额相等。应收、应付及待履约控制科目由业务流程生成。现金银行行必须关联资金账户。业务自动凭证不得绕过来源单据直接冲销。

期间不能重叠。关账检查期初确认、期内草稿、银行未匹配、凭证平衡及更早期间关闭等事项；重开按从后往前顺序并记录原因。凭证和生效单据不能写入关闭期间。

## 履约收入

路由前缀 `/api/finance/v2/revenue`：

- `GET /`：客户账单的待履约和已确认收入，支持 `p,s,q,open_only`。
- `GET /:invoice_id`：收入确认及冲销凭证列表。
- `POST /:invoice_id/recognize`：`{version,amount,recognition_date,reason,idempotency_key}`。
- `POST /entries/:entry_id/reverse`：`{version,reversal_date,reason,idempotency_key}`。

部分确认借待履约、贷服务收入。客户贷项优先冲减该账单尚未履约部分，其余冲减已确认收入。回溯确认、贷项和撤销会校验相关历史日期，拒绝导致负待履约或负收入的操作。

## 银行流水与对账

- `GET /accounting/bank-transactions?account_id=&status=&p=&s=`。
- `POST /accounting/bank-transactions/preview` / `/import`：`{account_id,rows:[{transaction_date,amount,reference,description}]}`，每批最多1000行。
- `POST /accounting/bank-transactions/:id/match`：`{version,payment_id}`。
- `POST /accounting/bank-transactions/:id/unmatch`：`{version,reason}`。

导入先预览，按账户与流水号去重；同流水号但金额或日期变化会拒绝整批。匹配要求资金账户、金额、方向一致。现支持一个已生效收付款匹配一笔银行交易；组合银行交易应先核实并按真实交易登记资金。银行联网和真实转账不在这些接口内。

## 报表和往来对账

- `GET /accounting/reports?date_from=&date_to=&account_code=`：试算平衡、科目明细、利润、资产负债和按凭证类别归集的资金流。
- `GET /accounting/reports/export`：同日期参数，CSV试算平衡表。
- `GET /accounting/partner-statement?partner_type=&partner_id=&date_from=&date_to=`：期初、增减、逐笔余额、期末。
- `GET /accounting/partner-statement/export`：CSV往来对账单。

报表仅包含已过账凭证，使用单据与分录快照，货重和业务归档不会改变账簿。客户正余额为应收，负余额为预收/应退；供应商正余额为应付，负余额为预付/应退。资金流视图按凭证类别归集，期初和调拨单列。未完成完整期初及政策核对前明确显示待核对口径。

## 旧订单接入

见接入接口实现及 `finance-v2-contract.md` 的接入契约。接入是需要操作者确认的期初余额迁移，不会在部署时自动搬账。使用来源快照及摘要哈希防止预览到确认期间的数据变化；源订单只建立一次关联。原订单工作流保持可用，来源变动进入待核对清单，不静默覆盖新账簿。

## 变更历史与全局审计

- 旧收款：`GET /api/receipts/:id/history?p=&s=`，沿用该收款的访问权限。
- 新账单、收付款、供应商、资金账户：相应 `/:id/history`。
- `GET /api/audit-logs` 仍仅管理员；新增 `event_type,target_type,target_id,action,operator_name,date_from,date_to,q` 筛选。

单据历史返回 `{items,total,page,page_size,history_complete,notice}`。事件含 `changes:[{field,before,after}]`、操作者及角色快照、原因、时间、`correlation_id` 和 `legacy`。同一数据库事务共享关联号。旧系统未保存的变更不会伪造；界面提示历史记录范围，原有事件仍可查看。

## 设计参考

参考 Odoo 的草稿与过账、独立资金与核销、贷项、历史记录和期间控制，按货运业务保留订单作业流程：

- [客户账单](https://www.odoo.com/documentation/19.0/applications/finance/accounting/customer_invoices.html)
- [收付款与核销](https://www.odoo.com/documentation/19.0/applications/finance/accounting/payments.html)
- [账务不可变性](https://www.odoo.com/documentation/19.0/applications/finance/accounting/reporting/data_inalterability.html)

本实现未连接生产数据库、未迁移实际Excel账册、未自动付款。上线前需演练迁移、核对真实期初与科目政策，并在专用MySQL环境执行并发测试。
