# API v1.31：统一供应商对账明细与应付草稿

日期：2026-10-06。前缀 `/api/supplier-reconciliation`，JWT；文员 `clerk`、财务 `finance`、管理员 `admin` 均可以上传、查阅全部批次和异常。财务账单生效、贷项和付款仍使用财务 v2 权限，不赋予文员过账权限。

## 模板与核对规则

`GET /template` 下载 `供应商对账统一模板.xlsx`。仅 `.xlsx`，最大 10 MB，工作表名为 `对账明细`，第一行为标题，最多 5000 数据行。

| 列名 | 规则 |
| --- | --- |
| 原单号 | 必填文本，先匹配 `Cargo.transfer_id`，无任何包裹候选时再精确匹配 `Order.order_id`，保留前导零；详情见 [v1.33](API-v1.33-order-level-supplier-reconciliation.md) |
| 转单号 | 可选文本；包裹级提供时必须等于 `Cargo.waybill_id`；订单级保留上传证据，不核对某一个包裹 |
| 重量(kg) | 必填，正数，最多 3 位小数；重量差=上传重量−系统原始实重。包裹级允许 [-0.5, 0] kg（含边界）；订单级按未归档包裹实重总和，允许 [-5, 0) kg，上传重量必须严格小于订单总实重 |
| 最终费用(元) | 必填，正数，最多 2 位小数；CNY，按供应商最终金额生成草稿，不代表已验证采购价 |
| 费用说明 | 可选，最多 512 字 |

列顺序可变，可省略两列可选字段，其余列名须与模板一致。公式必须先粘贴为值。数字号码最多允许 15 位整数；更长数字及科学计数法视为精度异常，需从原账单重新粘贴完整文本。纯 `000...` 数字格式保存的前导零可以恢复。上传不修改货物重量、单号、订单资料或旧估算成本。

文件格式、工作表、标题错误使整次请求失败；行缺值、无效重量/费用、负金额、公式、找不到原单号、多候选、归档/无订单、转单号/重量不符、重复收费均保存为异常，不影响其他正常行。文件内重复原单号的所有行都异常。相同供应商+货物+系统转单号若其他批次已有关联草稿或生效账单，标记疑似重复，费用不同也不能绕过检查。补差、扣款和供应商贷项由财务另行审核处理。

订单级同供应商的费用若覆盖已有费用的发运包裹（包裹 UID 和系统转单号）亦为异常；整单之间、整单与逐包裹之间有重叠均须核对。同文件重叠行不生成草稿；已取消草稿不再阻止重新核对。该规则按具体发运包裹核对，不永久占用订单 UID；只有新的发运集合与旧费用完全不重叠才能自动通过。

## 接口

| 方法与路径 | 参数与结果 |
| --- | --- |
| GET `/vendors?q=&p=&s=` | 限定供应商选项，仅启用供应商 `{items:[{id,name}],total,page,page_size}`，不公开余额、账户或联系方式 |
| POST `/batches` | multipart `file`、`vendor_id`、`period`（YYYY-MM），自动解析、核对并生成通过行的 `vendor_bill` 草稿，返回详情结构 |
| GET `/batches?q=&vendor_id=&period=&p=&s=` | `{items:[batch],total,page,page_size}`，按最新批次排序 |
| GET `/batches/:id?row_status=&p=&s=` | `{batch,rows:{items,total,page,page_size}}`；状态可为 `passed`/`exception`，默认全部 |
| POST `/batches/:id/reconcile` | JSON `{version}`，重新核对未生成账单的异常行，新通过行追加草稿；旧通过行及其账单保持不变 |
| GET `/orders/:order_uid/costs` | 订单供应商成本，含手工与导入供应商账单；生效/草稿分开，贷项带负号 |

同一供应商、账期、文件 SHA-256 重复上传返回 HTTP 409，原文件字节与原行值保存在批次，不覆盖历史。普通错误 400、权限 403、不存在 404、版本/重复/资料变化 409。列表默认每页 50、最大 200。

`batch` 字段：`id,number,vendor_id,vendor_name,period,filename,status,version,created_at,updated_at,created_by_name`，`status` 为 `reconciled` 或 `exceptions`；`summary:{total_rows,passed_rows,exception_rows,passed_amount,total_valid_amount}`，`documents:[{id,number,status,total_amount,version}]`，`weight_difference_range:{min:"-0.500",max:"0.000"}`、`notice`。兼容字段 `weight_tolerance:"0.500"` 表示上传重量最多可少 0.5 kg，不代表双向容差；上限严格为 0。

订单级容差另返回 `order_weight_difference_range:{min:"-5.000",max:"0.000",min_inclusive:true,max_inclusive:false}`。包裹级兼容字段不变。

`passed_amount` 只统计通过行，`total_valid_amount` 是有正数有效费用的所有行金额（含重量/单号异常行），不是已经确认的成本。无效和负费用不计入该金额。

明细字段：`id,source_row,original_number,waybill_number,weight,final_fee,description,status,issues:[{code,message}],cargo_uid,order_uid,order_number,system_weight,system_waybill,weight_difference,finance_document_id,finance_document_line_id`。`raw_values` 以模板中文列名为键，返回读取到的原始值文本，异常值可以显示给文员。重量/差异为 3 位小数字符串，费用为 2 位小数字符串，无法解析的值为 `null`，原值仍保存。比较使用未进位的系统原始重量，显示才保留 3 位小数。

新增 `match_type:"cargo"|"order"|null`、`system_weight_scope:"cargo"|"order_total"|null`；订单级 `cargo_uid`、`system_waybill` 为 `null`，`system_weight` 为订单总实重，`order_uid` 关联应付明细，不虚构或拆分包裹费用。

## 应付与成本

上传只生成**供应商应付账单草稿**，异常行不生成账单。超过 200 个通过行会拆成多个可追溯草稿，每个账单明细关联来源行；账单日期默认上传当天，账期仅为对账分类。最终费用采用数量 1、单价=最终费用、税率 0；第一版未提供税票拆分，不自动认定可抵扣税额。

财务通过原财务 v2 生效接口确认账单；生效前 `validate_import_document_for_post` 在同事务重新验证供应商、单据金额、货物单号、重量、订单归属与归档状态，资料变化会阻止生效。导入来源账单的费用行、供应商和期初属性不能改写；普通 PATCH 可修改日期、备注等元信息，也接受内容完全不变的 `lines`，并保留原账单行 ID 与来源关系。费用变化应取消原草稿、修正资料并重新上传。重新核对仅处理仍为异常的行。

订单级生效前再次执行原单号优先匹配、订单唯一性及严格重量规则，并核对订单号、未归档包裹集合、各包裹原始重量与转单号。新增/移走/归档包裹、改变重量、出现原单号候选或重复订单号均阻止旧草稿生效，即使总重碰巧不变也须重新核对。

订单成本响应：`{confirmed_amount,pending_amount,confirmed_net_amount,total,items,scope}`。生效的 `vendor_bill` 正数、`vendor_credit` 负数，原账单与已生效冲销贷项共同计算；取消草稿不计入，期初余额及其贷项不计入本期成本。`confirmed_net_amount` 为未税净成本。全部明细参与汇总，`items` 最多显示 100 行：`document_id,number,document_type,status,line_id,description,total_amount,subtotal,currency,source_batch_id,source_row`。草稿仅体现在 `pending_amount`；过账和付款核销不会再生成第二份订单成本。

成本 `items` 新增 `match_type`、`source_original_number`、`source_system_weight`（3 位小数字符串），用于区分整单/包裹导入费用；手工账单这些来源字段为 `null`。整单费用与包裹费用均按应付行的 `order_uid` 参与原有汇总。

## 数据迁移

新增 Alembic revision `79e4f5a6b7c8`（父版本 `68d3e4f5a6b7`），新增 `supplier_reconciliation_batches` 和 `supplier_reconciliation_rows`。启动应用和 Alembic metadata 须导入模型并注册控制器。自动化测试使用独立 SQLite 测试数据；不自动迁移或改写已有业务数据。
