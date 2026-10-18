# API v1.46：拍照核对后生成草稿装箱单

`POST /api/intakes/<uid>/confirm` 在上传者核对并提交 `{version, reviewed: true}` 后，新生成装箱单的业务状态改为 `draft`。此规则替代 [API v1.30](API-v1.30-uploader-check-and-shipping-drafts-page.md) 中确认后直接生成 `completed` 装箱单的行为。

纸单来源记录仍为 `status: "confirmed"`，保留 `confirmed_by`、`confirmed_at`、`packing_list_uid` 及原图关联。确认响应中的 `data.status` 表示来源记录的确认状态，不是装箱单业务状态。箱子、逐箱工人绑定及来源确认仍在同一事务内写入；上传者权限、明确勾选核对、版本及字段校验保持原有规则。

`GET /api/intakes/my-packing-lists` 对该新单返回 `source: "paper"`、`status: "draft"`，可通过 `status=draft` 筛选并进入装箱单详情继续处理。装箱单后续沿用现有完成流程。

仅改变此次流程中新建装箱单的初始业务状态，不新增数据库字段或迁移，不批量改写历史数据。已确认来源的重复请求继续返回同一 `packing_list_uid`，不重复创建装箱单、箱子或工人绑定，也不重置已有装箱单的业务状态；历史已完成装箱单继续保持 `completed`。
