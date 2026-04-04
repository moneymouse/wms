-- 迁移脚本：为customers表添加phone和wechat字段
-- 创建时间：2026-04-03
-- 说明：添加客户联系方式字段（敏感数据，只有admin、store_manager、salesperson可访问）

-- 添加phone字段
ALTER TABLE customers
ADD COLUMN phone VARCHAR(64) DEFAULT NULL
COMMENT '客户联系电话（敏感字段）';

-- 添加wechat字段
ALTER TABLE customers
ADD COLUMN wechat VARCHAR(128) DEFAULT NULL
COMMENT '客户微信号（敏感字段）';
