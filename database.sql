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
  `is_read` varchar(10) DEFAULT 'No',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
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

-- Demo seed data for local development. These records are fictional.
-- Change or remove the demo credentials before using the application outside development.
INSERT INTO `clinic_admin` (`id`, `username`, `password`) VALUES
  (1, 'admin', 'admin123');

INSERT INTO `clinics` (`id`, `clinic_name`, `clinic_type`, `address`, `location`, `distance`, `waiting_time`, `map_link`, `status`, `opening_time`, `closing_time`, `contact_number`) VALUES
  (1, 'MediAI Community Clinic', 'General Practice', '123 Demo Street', 'Central District', '1.2 km', 10, NULL, 'Open', '08:00:00', '17:00:00', '000-000-0001'),
  (2, 'MediAI Family Health', 'Family Medicine', '456 Example Avenue', 'North District', '2.5 km', 15, NULL, 'Open', '09:00:00', '18:00:00', '000-000-0002');

INSERT INTO `doctors` (`id`, `name`, `email`, `password`, `clinic_code`, `username`, `specialist`, `clinic_name`, `status`, `availability`, `consultation_duration`, `clinic_id`) VALUES
  (1, 'Dr. Alex Tan', 'alex.tan@example.test', 'doctor123', 'MED-001', 'dr_alex', 'General Practitioner', 'MediAI Community Clinic', 'Active', 'Available', 15, 1),
  (2, 'Dr. Sam Lee', 'sam.lee@example.test', 'doctor123', 'MED-002', 'dr_sam', 'Family Medicine', 'MediAI Family Health', 'Active', 'Available', 20, 2);

INSERT INTO `patients` (`id`, `full_name`, `age`, `gender`, `email`, `password`, `address`, `emergency_contact`, `allergies`, `contact_number`, `medical_history`, `username`) VALUES
  (1, 'Demo Patient One', 30, 'Female', 'patient.one@example.test', 'patient123', '10 Sample Road', '000-000-1001', 'None reported', '000-000-1000', 'No significant history', 'demo_patient_1'),
  (2, 'Demo Patient Two', 42, 'Male', 'patient.two@example.test', 'patient123', '20 Sample Road', '000-000-2001', 'Penicillin', '000-000-2000', 'Seasonal allergies', 'demo_patient_2');

INSERT INTO `triage_results` (`id`, `patient_id`, `clinic_name`, `symptoms`, `duration`, `severity`, `urgency`, `age`, `ai_score`, `priority_level`, `emergency_detected`) VALUES
  (1, 1, 'MediAI Community Clinic', 'Mild headache and fatigue', '2 days', 'Mild', 'Low', 30, 20, 'Normal', 'No'),
  (2, 2, 'MediAI Family Health', 'Persistent cough', '3 days', 'Moderate', 'Medium', 42, 45, 'Normal', 'No');

INSERT INTO `appointments` (`id`, `patient_id`, `doctor_id`, `doctor_name`, `specialist`, `clinic`, `date`, `time`, `queue_number`, `priority`, `wait_time`, `status`, `urgency`, `triage_id`, `clinic_id`) VALUES
  (1, 1, 1, 'Dr. Alex Tan', 'General Practitioner', 'MediAI Community Clinic', '2026-08-10', '09:00', 1, 'Normal', '10 minutes', 'Booked', 'normal', 1, 1),
  (2, 2, 2, 'Dr. Sam Lee', 'Family Medicine', 'MediAI Family Health', '2026-08-10', '10:00', 1, 'Normal', '15 minutes', 'Booked', 'normal', 2, 2);

INSERT INTO `consultations` (`id`, `appointment_id`, `diagnosis`, `remarks`) VALUES
  (1, 1, 'Demo consultation', 'This is fictional development data.');

INSERT INTO `prescriptions` (`id`, `consultation_id`, `medicine_name`, `dosage`, `frequency`, `duration`) VALUES
  (1, 1, 'Demo medicine', '1 tablet', 'Once daily', '3 days');

INSERT INTO `health_announcements` (`id`, `title`, `category`, `message`, `start_date`, `expiry_date`, `status`) VALUES
  (1, 'Welcome to MediAI', 'General Announcement', 'This is a sample announcement created for local development.', '2026-01-01', '2027-01-01', 'Active');

INSERT INTO `notifications` (`id`, `patient_id`, `title`, `message`, `is_read`) VALUES
  (1, 1, 'Welcome', 'Your demonstration account is ready.', 'No');
