-- MediAI schema export (structure only; no application or patient data).
CREATE TABLE `appointments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `patient_id` int DEFAULT NULL,
  `doctor_id` int DEFAULT NULL,
  `doctor_name` varchar(100) DEFAULT NULL,
  `specialist` varchar(100) DEFAULT NULL,
  `clinic` varchar(100) DEFAULT NULL,
  `date` varchar(50) DEFAULT NULL,
  `time` varchar(50) DEFAULT NULL,
  `queue_number` int DEFAULT NULL,
  `priority` varchar(20) DEFAULT NULL,
  `wait_time` varchar(50) DEFAULT NULL,
  `status` varchar(20) DEFAULT NULL,
  `urgency` varchar(20) DEFAULT 'normal',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `triage_id` int DEFAULT NULL,
  `clinic_id` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `clinic_admin` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(100) NOT NULL,
  `password` varchar(100) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `clinics` (
  `id` int NOT NULL AUTO_INCREMENT,
  `clinic_name` varchar(100) DEFAULT NULL,
  `clinic_type` varchar(100) DEFAULT NULL,
  `address` text,
  `location` varchar(100) DEFAULT NULL,
  `distance` varchar(50) DEFAULT NULL,
  `waiting_time` int DEFAULT NULL,
  `map_link` text,
  `status` varchar(30) DEFAULT 'Open',
  `opening_time` time DEFAULT NULL,
  `closing_time` time DEFAULT NULL,
  `contact_number` varchar(20) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `consultations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `appointment_id` int DEFAULT NULL,
  `diagnosis` text,
  `remarks` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `doctors` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `password` varchar(100) DEFAULT NULL,
  `clinic_code` varchar(50) DEFAULT NULL,
  `username` varchar(50) DEFAULT NULL,
  `specialist` varchar(100) DEFAULT NULL,
  `clinic_name` varchar(100) DEFAULT NULL,
  `status` varchar(30) DEFAULT 'Active',
  `availability` varchar(30) DEFAULT 'Available',
  `consultation_duration` int DEFAULT '15',
  `clinic_id` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `health_announcements` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(255) NOT NULL,
  `category` enum('Clinic Notice','Health Advisory','Vaccination','Holiday Notice','System Notice','General Announcement') NOT NULL DEFAULT 'General Announcement',
  `message` text NOT NULL,
  `start_date` date NOT NULL,
  `expiry_date` date NOT NULL,
  `status` enum('Active','Inactive') NOT NULL DEFAULT 'Active',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `notifications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `patient_id` int DEFAULT NULL,
  `title` varchar(255) DEFAULT NULL,
  `message` text,
  `notification_key` varchar(64) DEFAULT NULL,
  `is_read` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_notifications_notification_key` (`notification_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `patients` (
  `id` int NOT NULL AUTO_INCREMENT,
  `full_name` varchar(100) DEFAULT NULL,
  `age` int DEFAULT NULL,
  `gender` varchar(20) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `password` varchar(100) DEFAULT NULL,
  `address` text,
  `emergency_contact` varchar(20) DEFAULT NULL,
  `allergies` text,
  `contact_number` varchar(20) DEFAULT NULL,
  `medical_history` text,
  `username` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `prescriptions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `consultation_id` int DEFAULT NULL,
  `medicine_name` varchar(100) DEFAULT NULL,
  `dosage` varchar(50) DEFAULT NULL,
  `frequency` varchar(50) DEFAULT NULL,
  `duration` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `triage_results` (
  `id` int NOT NULL AUTO_INCREMENT,
  `patient_id` int DEFAULT NULL,
  `clinic_name` varchar(255) DEFAULT NULL,
  `symptoms` text,
  `duration` varchar(100) DEFAULT NULL,
  `severity` varchar(100) DEFAULT NULL,
  `urgency` varchar(100) DEFAULT NULL,
  `age` int DEFAULT NULL,
  `ai_score` int DEFAULT NULL,
  `priority_level` varchar(50) DEFAULT NULL,
  `emergency_detected` varchar(10) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

