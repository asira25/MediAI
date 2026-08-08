-- =========================
-- NOTIFICATION SYSTEM UPGRADE
-- =========================
-- Adds notification fields required by the application to existing tables.
-- Run this ONCE after sql_fix_isread_column.sql.

ALTER TABLE notifications
ADD COLUMN notification_key VARCHAR(64) NULL
COMMENT 'Unique event key used to prevent duplicate notifications';

CREATE UNIQUE INDEX uq_notifications_notification_key
ON notifications (notification_key);
