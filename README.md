# MediAI

MediAI is a Flask web application for managing clinic appointments, patient triage, live queues, consultations, prescriptions, clinic announcements, and clinic/doctor administration.

## Features

- Patient registration, login, appointment booking, and appointment history
- Symptom triage and priority-based appointment queues
- Live queue and appointment monitoring
- Doctor consultation workflow, prescriptions, and consultation history
- Clinic administration, operating hours, availability, and announcements
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
   mysql -u root -p mediai < database.sql
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

`database.sql` contains the MediAI schema only. It intentionally excludes local data such as patient profiles, login records, appointments, medical details, prescriptions, and notifications.

## Security note

Do not commit real database passwords, patient data, or production credentials. Configure database access with the environment variables above.
