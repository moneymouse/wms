-- Migration: Add piece_count to boxes
-- Date: 2026-04-10
-- Description:
--   1) boxes 增加件数字段 piece_count
--   2) 历史数据回填默认值 1

ALTER TABLE boxes ADD COLUMN piece_count INT NULL AFTER box_number;

UPDATE boxes
SET piece_count = 1
WHERE piece_count IS NULL OR piece_count <= 0;

ALTER TABLE boxes MODIFY COLUMN piece_count INT NOT NULL DEFAULT 1;
