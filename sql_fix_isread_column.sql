-- Fix is_read column type from varchar to TINYINT
-- Run this ONCE to fix the existing column

-- Step 1: Update existing 'No' values to 0
UPDATE notifications
SET is_read = 0
WHERE is_read = 'No' OR is_read IS NULL;

-- Step 2: Change column type to TINYINT(1)
ALTER TABLE notifications
MODIFY COLUMN is_read TINYINT(1) NOT NULL DEFAULT 0
COMMENT '0=unread, 1=read';