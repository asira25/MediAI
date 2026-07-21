-- =========================
-- NOTIFICATION SYSTEM UPGRADE
-- =========================
-- Adds is_read column to existing notifications table
-- Run this ONCE against your mediai database

ALTER TABLE notifications
ADD COLUMN IF NOT EXISTS is_read TINYINT(1) NOT NULL DEFAULT 0
COMMENT '0=unread, 1=read';