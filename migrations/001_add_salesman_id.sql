-- Migration: Add salesman_id to orders table
-- Date: 2026-03-28
-- Description: Add foreign key to link orders with their salesman (user)

-- Add salesman_id column
ALTER TABLE orders
ADD COLUMN salesman_id INT DEFAULT NULL;

-- Add foreign key constraint
ALTER TABLE orders
ADD CONSTRAINT fk_order_salesman
    FOREIGN KEY (salesman_id) REFERENCES users (id)
    ON DELETE SET NULL ON UPDATE CASCADE;

-- Add index for better query performance
CREATE INDEX idx_orders_salesman ON orders (salesman_id);
