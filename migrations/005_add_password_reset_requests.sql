-- Migration: Add password reset requests table
-- Description: 添加密码重置申请表，用于存储忘记密码的用户申请

CREATE TABLE IF NOT EXISTS password_reset_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    new_password_hash VARCHAR(512) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    remark VARCHAR(256),
    create_date VARCHAR(32),
    update_date VARCHAR(32),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Index for faster lookup of pending requests
CREATE INDEX IF NOT EXISTS idx_password_reset_requests_status ON password_reset_requests(status);
CREATE INDEX IF NOT EXISTS idx_password_reset_requests_user_id ON password_reset_requests(user_id);
