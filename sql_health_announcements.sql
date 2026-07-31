-- =========================
-- HEALTH ANNOUNCEMENTS TABLE
-- =========================
-- Run this SQL to create the health_announcements table
-- for the Clinic Health Announcement Board feature

CREATE TABLE IF NOT EXISTS health_announcements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    category ENUM(
        'Clinic Notice',
        'Health Advisory',
        'Vaccination',
        'Holiday Notice',
        'System Notice',
        'General Announcement'
    ) NOT NULL DEFAULT 'General Announcement',
    message TEXT NOT NULL,
    start_date DATE NOT NULL,
    expiry_date DATE NOT NULL,
    status ENUM('Active', 'Inactive') NOT NULL DEFAULT 'Active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;