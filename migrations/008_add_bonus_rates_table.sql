-- Migration: Add bonus_rates table for worker settlement base rates
-- Date: 2026-04-10
-- Description:
--   1) 新增 bonus_rates 表（1~4 人合打奖金基数）
--   2) 初始化 1~4 人默认基数为 0

CREATE TABLE IF NOT EXISTS bonus_rates (
    team_size       INT             NOT NULL,
    base_amount     FLOAT           NOT NULL DEFAULT 0,
    updated_by      INT             DEFAULT NULL,
    update_date     VARCHAR(32),
    PRIMARY KEY (team_size),
    CONSTRAINT fk_bonus_rate_user
        FOREIGN KEY (updated_by) REFERENCES users (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO bonus_rates (team_size, base_amount)
VALUES (1, 0), (2, 0), (3, 0), (4, 0)
ON DUPLICATE KEY UPDATE base_amount = VALUES(base_amount);
