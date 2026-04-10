-- Migration: Add packing_lists, boxes and box_workers tables
-- Date: 2026-04-05
-- Description: Create tables for packing list and box management (入库流程)

-- -----------------------------------------------------------------------------
-- packing_lists (装箱单)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS packing_lists (
    uid             VARCHAR(32)     NOT NULL,
    list_number     VARCHAR(64)     NOT NULL,  -- 唛头：客户名-月日-3位编号
    customer_id     INT             NOT NULL,
    photos          TEXT,                       -- JSON数组存储照片路径
    creator_id      INT             NOT NULL,   -- 创建人
    status          VARCHAR(32)     DEFAULT 'draft',  -- draft / completed
    create_date     VARCHAR(32),
    update_date     VARCHAR(32),
    archive         TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (uid),
    UNIQUE KEY uq_packing_lists_number (list_number),
    CONSTRAINT fk_pl_customer
        FOREIGN KEY (customer_id) REFERENCES customers (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_pl_creator
        FOREIGN KEY (creator_id) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_pl_customer ON packing_lists (customer_id);
CREATE INDEX idx_pl_creator ON packing_lists (creator_id);
CREATE INDEX idx_pl_status ON packing_lists (status);

-- -----------------------------------------------------------------------------
-- boxes (箱子)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS boxes (
    uid                 VARCHAR(32)     NOT NULL,
    packing_list_uid    VARCHAR(32)     NOT NULL,
    item_name           VARCHAR(256),           -- 品名
    weight              FLOAT           DEFAULT NULL,  -- 重量(kg)，NULL表示未称重
    target_order_uid    VARCHAR(32)     DEFAULT NULL,  -- 分配到的订单
    status              VARCHAR(32)     DEFAULT 'pending',  -- pending / assigned
    create_date         VARCHAR(32),
    update_date         VARCHAR(32),
    archive             TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (uid),
    CONSTRAINT fk_box_packing_list
        FOREIGN KEY (packing_list_uid) REFERENCES packing_lists (uid)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_box_order
        FOREIGN KEY (target_order_uid) REFERENCES orders (uid)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_box_packing_list ON boxes (packing_list_uid);
CREATE INDEX idx_box_order ON boxes (target_order_uid);
CREATE INDEX idx_box_status ON boxes (status);

-- -----------------------------------------------------------------------------
-- box_workers (箱子-工人关联表)
-- 记录打包工人，每个箱子最多关联4个工人，用于后续工人计薪功能
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_workers (
    id              INT             NOT NULL AUTO_INCREMENT,
    box_uid         VARCHAR(32)     NOT NULL,
    worker_id       INT             NOT NULL,
    create_date     VARCHAR(32),
    PRIMARY KEY (id),
    CONSTRAINT fk_bw_box
        FOREIGN KEY (box_uid) REFERENCES boxes (uid)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_bw_worker
        FOREIGN KEY (worker_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_bw_box ON box_workers (box_uid);
CREATE INDEX idx_bw_worker ON box_workers (worker_id);
