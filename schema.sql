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
