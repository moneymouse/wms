-- Migration: Add order_customers association table
-- Date: 2026-04-03
-- Description: Create many-to-many relationship between orders and customers

-- Create the order_customers association table
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

-- Add index for customer_id for better query performance
CREATE INDEX idx_oc_customer ON order_customers (customer_id);
