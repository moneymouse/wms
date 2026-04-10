-- =============================================================================
-- WMS Database DDL
-- Target: MySQL 8.0+
-- Charset: utf8mb4 / utf8mb4_unicode_ci
-- =============================================================================

CREATE DATABASE IF NOT EXISTS wms_db
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE wms_db;

-- -----------------------------------------------------------------------------
-- orders
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    uid             VARCHAR(32)     NOT NULL,
    order_id        VARCHAR(128),
    customer_name   VARCHAR(256),
    transportation  VARCHAR(128),
    receiver        VARCHAR(256),
    receiver_phone  VARCHAR(64),
    mail            VARCHAR(256),
    country         VARCHAR(128),
    province        VARCHAR(128),
    city            VARCHAR(128),
    address         TEXT,
    en_name         VARCHAR(256),
    cn_name         VARCHAR(256),
    total_weight    FLOAT,
    cargo_count     INT             DEFAULT 0,
    archive         TINYINT(1)      NOT NULL DEFAULT 0,
    post_code       VARCHAR(64),
    zip_code        VARCHAR(64),
    order_date      VARCHAR(32),
    tag_all         VARCHAR(256),
    create_date     VARCHAR(32),
    update_date     VARCHAR(32),
    salesman_id     INT             DEFAULT NULL,
    PRIMARY KEY (uid),
    CONSTRAINT fk_order_salesman
        FOREIGN KEY (salesman_id) REFERENCES users (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- cargos
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cargos (
    uid                 VARCHAR(32)     NOT NULL,
    origin_id           VARCHAR(128),
    transfer_id         VARCHAR(256)    DEFAULT '',
    tag                 VARCHAR(128)    DEFAULT 'init',
    count               INT             DEFAULT 0,
    weight              FLOAT           DEFAULT 0,
    real_en_name        VARCHAR(256),
    price               FLOAT,
    status              INT             DEFAULT 0,
    archive             TINYINT(1)      NOT NULL DEFAULT 0,
    date                VARCHAR(32),
    waybill_id          VARCHAR(256)    DEFAULT '',
    target_order_uid    VARCHAR(32),
    create_date         VARCHAR(32),
    update_date         VARCHAR(32),
    PRIMARY KEY (uid),
    CONSTRAINT fk_cargo_order
        FOREIGN KEY (target_order_uid) REFERENCES orders (uid)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX IF NOT EXISTS idx_cargos_order   ON cargos (target_order_uid);
CREATE INDEX IF NOT EXISTS idx_cargos_transfer ON cargos (transfer_id);
CREATE INDEX IF NOT EXISTS idx_cargos_waybill  ON cargos (waybill_id);

-- -----------------------------------------------------------------------------
-- customers
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id      INT             NOT NULL AUTO_INCREMENT,
    name    VARCHAR(256)    NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_customers_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- receivers
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS receivers (
    id              INT             NOT NULL AUTO_INCREMENT,
    customer_name   VARCHAR(256)    NOT NULL,
    receiver        VARCHAR(256),
    receiver_phone  VARCHAR(64),
    mail            VARCHAR(256),
    country         VARCHAR(128),
    province        VARCHAR(128),
    city            VARCHAR(128),
    address         TEXT,
    zip_code        VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT fk_receiver_customer
        FOREIGN KEY (customer_name) REFERENCES customers (name)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX IF NOT EXISTS idx_receivers_customer ON receivers (customer_name);

-- -----------------------------------------------------------------------------
-- order_customers (many-to-many association table)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_customers (
    order_uid       VARCHAR(32)     NOT NULL,
    customer_id     INT             NOT NULL,
    PRIMARY KEY (order_uid, customer_id),
    CONSTRAINT fk_oc_order
        FOREIGN KEY (order_uid) REFERENCES orders (uid)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_oc_customer
        FOREIGN KEY (customer_id) REFERENCES customers (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX IF NOT EXISTS idx_oc_customer ON order_customers (customer_id);

-- -----------------------------------------------------------------------------
-- operation_logs
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operation_logs (
    id          INT             NOT NULL AUTO_INCREMENT,
    ip          VARCHAR(64),
    pc_name     VARCHAR(256),
    `desc`      VARCHAR(512),
    kwargs      TEXT,
    json_body   TEXT,
    method      VARCHAR(16),
    log_date    VARCHAR(32),
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX IF NOT EXISTS idx_logs_date ON operation_logs (log_date);

-- -----------------------------------------------------------------------------
-- users (RBAC user accounts)
-- roles: admin | store_manager | salesperson | clerk | finance
-- status: pending (awaiting approval) | approved | rejected
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          INT             NOT NULL AUTO_INCREMENT,
    phone       VARCHAR(32)     NOT NULL,
    name        VARCHAR(128)    NOT NULL,
    password    VARCHAR(512)    NOT NULL,
    role        VARCHAR(32)     DEFAULT NULL,
    status      ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
    remark      VARCHAR(256)    DEFAULT NULL,
    create_date VARCHAR(32),
    update_date VARCHAR(32),
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);

-- -----------------------------------------------------------------------------
-- packing_lists (装箱单)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS packing_lists (
    uid             VARCHAR(32)     NOT NULL,
    list_number     VARCHAR(64)     NOT NULL,  -- 唛头：用户输入，重复时自动追加日期后缀
    customer_id     INT             DEFAULT NULL,
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
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_pl_creator
        FOREIGN KEY (creator_id) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX IF NOT EXISTS idx_pl_customer ON packing_lists (customer_id);
CREATE INDEX IF NOT EXISTS idx_pl_creator ON packing_lists (creator_id);
CREATE INDEX IF NOT EXISTS idx_pl_status ON packing_lists (status);

-- -----------------------------------------------------------------------------
-- boxes (箱子)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS boxes (
    uid                 VARCHAR(32)     NOT NULL,
    packing_list_uid    VARCHAR(32)     NOT NULL,
    item_name           VARCHAR(256),           -- 品名
    box_number          INT             NOT NULL DEFAULT 1,  -- 箱号（每个装箱单内递增）
    piece_count         INT             NOT NULL DEFAULT 1,  -- 件数
    weight              FLOAT           DEFAULT NULL,  -- 重量(kg)，NULL表示未称重
    target_order_uid    VARCHAR(32)     DEFAULT NULL,  -- 分配到的订单
    status              VARCHAR(32)     DEFAULT 'pending',  -- pending / assigned
    create_date         VARCHAR(32),
    update_date         VARCHAR(32),
    archive             TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (uid),
    UNIQUE KEY uq_box_list_number (packing_list_uid, box_number),
    CONSTRAINT fk_box_packing_list
        FOREIGN KEY (packing_list_uid) REFERENCES packing_lists (uid)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_box_order
        FOREIGN KEY (target_order_uid) REFERENCES orders (uid)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX IF NOT EXISTS idx_box_packing_list ON boxes (packing_list_uid);
CREATE INDEX IF NOT EXISTS idx_box_order ON boxes (target_order_uid);
CREATE INDEX IF NOT EXISTS idx_box_status ON boxes (status);

-- -----------------------------------------------------------------------------
-- box_workers (箱子-工人关联表)
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

CREATE INDEX IF NOT EXISTS idx_bw_box ON box_workers (box_uid);
CREATE INDEX IF NOT EXISTS idx_bw_worker ON box_workers (worker_id);

-- -----------------------------------------------------------------------------
-- bonus_rates (1~4人合打奖金基数)
-- -----------------------------------------------------------------------------
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
