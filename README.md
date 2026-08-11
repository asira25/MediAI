# MediAI

## Overview

MediAI is a Flask web application for managing clinic appointments, patient triage, live queues, consultations, prescriptions, clinic announcements, and clinic/doctor administration. Its symptom assessment and appointment-priority scoring use rule-based logic; they are not based on a trained machine-learning model.

## Features

- Patient registration, login, appointment booking, and appointment history
- Rule-based symptom assessment, priority scoring, and priority-based appointment queues
- Live queue and appointment monitoring
- Doctor consultation workflow, prescriptions, and consultation history
- Clinic administration, operating hours, doctor availability, and announcements
- PDF consultation and prescription output

## Requirements

- Python 3.10 or later
- MySQL 8.0 or compatible server

## Setup

1. Create and activate a virtual environment.

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies.

   ```powershell
   pip install -r requirements.txt
   ```

3. Create the database and import the schema.

   ```sql
   CREATE DATABASE mediai CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   ```

   ```powershell
   Get-Content database.sql | mysql -u root -p mediai
   ```

4. Set the database connection variables for your session.

   ```powershell
   $env:MEDIAI_DB_HOST = "127.0.0.1"
   $env:MEDIAI_DB_USER = "root"
   $env:MEDIAI_DB_PASSWORD = "your-password"
   $env:MEDIAI_DB_NAME = "mediai"
   $env:MEDIAI_SECRET_KEY = "a-long-random-secret"
   ```

5. Start the application.

   ```powershell
   python app.py
   ```

Open the local address printed by Flask in your browser.

## Database

`database.sql` contains the complete MediAI database schema. The development/demo environment may contain clinic administrator and doctor accounts used for system testing and demonstration.

### Database Tables

| Table | Purpose |
| --- | --- |
| `appointments` | Booked appointments, queue position, status, and priority |
| `clinic_admin` | Clinic-administrator login accounts |
| `clinics` | Clinic details, contact details, status, and operating hours |
| `consultations` | Consultation diagnosis and remarks |
| `doctors` | Doctor accounts, clinic assignment, availability, and clinic login code |
| `health_announcements` | Clinic and health announcements |
| `notifications` | Patient notifications |
| `patients` | Patient profiles and login accounts |
| `prescriptions` | Medicines prescribed during a consultation |
| `triage_results` | Patient symptom-triage results |

## Account Access

Doctors log in with their username or email, password, and the unique clinic code in `doctors.clinic_code`. Clinic administrators log in with their username and password.

### Demo Clinic Administrator Login

| ID | Username | Password |
| --- | --- | --- |
| 1 | `clinicadmin` | `admin123` |

### Demo Doctor Login Directory

| ID | Doctor | Username | Email | Password | Clinic code | Specialist | Clinic | Status | Availability | Duration (minutes) | Clinic ID |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Dr Ahmad | `drahmad` | `drahmad@gmail.com` | `ahmad123` | `BG001` | General Medicine | Klinik Bangi Care | Active | Available | 15 | 4 |
| 2 | Dr Sarah | `drsarah` | `drsarah@gmail.com` | `sarah123` | `BG002` | Pediatrics | Klinik Bangi Care | Active | Available | 15 | 4 |
| 3 | Dr Jason | `drjason` | `drjason@gmail.com` | `jason123` | `BG003` | Family Medicine | MedCare Bangi | Active | Available | 15 | 5 |
| 4 | Dr Lim | `drlim` | `drlim@gmail.com` | `lim123` | `BG004` | Dermatology | MedCare Bangi | Active | Available | 15 | 5 |
| 5 | Dr Hafiz | `drhafiz` | `drhafiz@gmail.com` | `hafiz123` | `BG005` | Emergency Medicine | Bangi Healthcare | Active | Available | 15 | 6 |
| 6 | Dr Aisyah | `draisyah` | `draisyah@gmail.com` | `aisyah123` | `BG006` | Internal Medicine | Bangi Healthcare | Active | Available | 15 | 6 |
| 7 | Dr Adam | `dradam` | `dradam@gmail.com` | `adam123` | `KL001` | Cardiology | KL Health Clinic | Active | Available | 20 | 7 |
| 8 | Dr Siti | `drsiti` | `drsiti@gmail.com` | `siti123` | `KL002` | Neurology | KL Health Clinic | Active | Available | 20 | 7 |
| 9 | Dr Farah | `drfarah` | `drfarah@gmail.com` | `farah123` | `KL003` | Family Medicine | Klinik Dr Azman | Active | Available | 15 | 8 |
| 10 | Dr Kumar | `drkumar` | `drkumar@gmail.com` | `kumar123` | `KL004` | Orthopedic | Klinik Dr Azman | Active | Available | 15 | 8 |
| 11 | Dr Melissa | `drmelissa` | `drmelissa@gmail.com` | `melissa123` | `KL005` | General Surgery | CityCare Medical | Active | Available | 25 | 9 |
| 12 | Dr Tan | `drtan` | `drtan@gmail.com` | `tan123` | `KL006` | ENT Specialist | CityCare Medical | Active | Available | 15 | 9 |
| 13 | Dr Amir | `dramir` | `dramir@gmail.com` | `amir123` | `PJ001` | General Medicine | PJ Care Clinic | Active | Available | 15 | 10 |
| 14 | Dr Nisha | `drnisha` | `drnisha@gmail.com` | `nisha123` | `PJ002` | Pediatrics | PJ Care Clinic | Active | Available | 15 | 10 |
| 15 | Dr Wong | `drwong` | `drwong@gmail.com` | `wong123` | `PJ003` | Family Medicine | Klinik Damansara | Active | Available | 15 | 11 |
| 16 | Dr Hani | `drhani` | `drhani@gmail.com` | `hani123` | `PJ004` | Dermatology | Klinik Damansara | Active | Available | 15 | 11 |
| 17 | Dr Steven | `drsteven` | `drsteven@gmail.com` | `steven123` | `PJ005` | Cardiology | Sunway Medical Point | Active | Available | 20 | 12 |
| 18 | Dr Priya | `drpriya` | `drpriya@gmail.com` | `priya123` | `PJ006` | Neurology | Sunway Medical Point | Active | Available | 20 | 12 |
| 19 | Dr Haziq | `drhaziq` | `drhaziq@gmail.com` | `haziq123` | `SH001` | General Medicine | Shah Alam Medical | Active | Available | 15 | 13 |
| 20 | Dr Aina | `draina` | `draina@gmail.com` | `aina123` | `SH002` | Dermatology | Shah Alam Medical | Active | Available | 15 | 13 |
| 21 | Dr Roslan | `drroslan` | `drroslan@gmail.com` | `roslan123` | `SH003` | Family Medicine | Klinik i-City | Active | Available | 15 | 14 |
| 22 | Dr Lee | `drlee` | `drlee@gmail.com` | `lee123` | `SH004` | Orthopedic | Klinik i-City | Active | Available | 15 | 14 |
| 23 | Dr Sofia | `drsofia` | `drsofia@gmail.com` | `sofia123` | `SH005` | Emergency Medicine | Central Shah Alam | Active | Available | 15 | 15 |
| 24 | Dr Daniel | `drdaniel` | `drdaniel@gmail.com` | `daniel123` | `SH006` | Internal Medicine | Central Shah Alam | Active | Available | 15 | 15 |
| 26 | Dr. Liya | `liya25` | `liya12345@gmail.com` | `liya25` | `BG007` | General Medicine | Bangi Healthcare | Active | Available | 15 | 6 |
| 27 | Dr Shreya | `Shreya25` | `shreya@gmail.com` | `SHREYA25` | `PMC001` | Family Medicine | KL Prime Medical Centre | Active | Available | 15 | 16 |

## Security Note

This README contains demonstration account credentials intended for local development, testing, and academic demonstration only. Keep the repository private and do not publish active credentials, database passwords, or patient information.

The current development version may use plaintext demonstration passwords. Before any production deployment, passwords must be securely hashed and appropriate application-security controls must be implemented.
