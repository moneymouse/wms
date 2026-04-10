-- Migration: Make packing list customer optional and add box_number sequence
-- Date: 2026-04-09
-- Description:
--   1) packing_lists.customer_id 改为可空
--   2) boxes 新增 box_number（每个装箱单内递增）
--   3) 添加 (packing_list_uid, box_number) 唯一约束

-- -----------------------------------------------------------------------------
-- packing_lists: customer_id 可空 + 外键改为 ON DELETE SET NULL
-- -----------------------------------------------------------------------------
ALTER TABLE packing_lists DROP FOREIGN KEY fk_pl_customer;
ALTER TABLE packing_lists MODIFY COLUMN customer_id INT NULL;
ALTER TABLE packing_lists
    ADD CONSTRAINT fk_pl_customer
    FOREIGN KEY (customer_id) REFERENCES customers (id)
    ON DELETE SET NULL ON UPDATE CASCADE;

-- -----------------------------------------------------------------------------
-- boxes: 新增 box_number，并为历史数据回填序号
-- -----------------------------------------------------------------------------
ALTER TABLE boxes ADD COLUMN box_number INT NULL AFTER item_name;

UPDATE boxes b
JOIN (
    SELECT
        uid,
        ROW_NUMBER() OVER (
            PARTITION BY packing_list_uid
            ORDER BY create_date, uid
        ) AS rn
    FROM boxes
) ranked ON ranked.uid = b.uid
SET b.box_number = ranked.rn
WHERE b.box_number IS NULL OR b.box_number = 0;

ALTER TABLE boxes MODIFY COLUMN box_number INT NOT NULL;
ALTER TABLE boxes ADD UNIQUE KEY uq_box_list_number (packing_list_uid, box_number);
