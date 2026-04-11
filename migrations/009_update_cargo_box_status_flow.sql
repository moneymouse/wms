-- 009_update_cargo_box_status_flow.sql
-- 兼容旧系统：cargo.status 为主状态字段
-- status: 0=待出库, 1=已出库
-- 装箱箱子的中间态由 target_order_uid / waybill_id 推导，不依赖 box_status

ALTER TABLE cargos
    MODIFY COLUMN box_status VARCHAR(32) DEFAULT 'pending';

-- 仅对装箱箱子修正 status 到旧系统语义
UPDATE cargos
SET status = 1
WHERE packing_list_uid IS NOT NULL
  AND (
    box_status = 'outbound'
    OR status = 1
  );

UPDATE cargos
SET status = 0
WHERE packing_list_uid IS NOT NULL
  AND status <> 1;
