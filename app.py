import email

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_file
from flask_cors import CORS
from config import get_db_connection
from datetime import datetime, timedelta
import urllib.parse
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

app = Flask(__name__)
CORS(app)
app.secret_key = "mediai_secret_key"

# =========================
# BACKGROUND SCHEDULER
# =========================
# APScheduler instance for automatic appointment status updates
# Runs every 1 minute to update appointment statuses without user interaction
scheduler = BackgroundScheduler()
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())


# =========================
# APPOINTMENT STATUS UPDATE FUNCTIONS
# =========================

def get_effective_status(appointment):
    """
    Calculate the effective status of an appointment based on current time.
    This ensures status changes happen EXACTLY at the appointment time,
    not just when the scheduler happens to run.
    
    Status transitions:
    - Booked → Waiting: Exactly at appointment time
    - Booked → Missed: 15 minutes after appointment time
    - Waiting → Missed: 45 minutes after appointment time (no-show)
    - In-Consultation, Completed, Cancelled, Missed: Preserved as-is
    
    Args:
        appointment (dict): Appointment record from database
        
    Returns:
        str: The effective status (may differ from DB status if time-based transition is due)
    """
    db_status = appointment['status']
    
    # Final states and manually controlled states are never overridden
    if db_status in ['Completed', 'Cancelled', 'Missed', 'In-Consultation']:
        return db_status
    
    current_datetime = datetime.now()
    appointment_datetime = datetime.strptime(
        f"{appointment['date']} {appointment['time']}",
        "%Y-%m-%d %H:%M"
    )
    
    if db_status == 'Booked':
        missed_time = appointment_datetime + timedelta(minutes=15)
        if current_datetime > missed_time:
            return 'Missed'
        elif current_datetime >= appointment_datetime:
            return 'Waiting'
    
    elif db_status == 'Waiting':
        no_show_time = appointment_datetime + timedelta(minutes=45)
        if current_datetime > no_show_time:
            return 'Missed'
    
    return db_status


def update_single_appointment_status(appointment_id):
    """
    Update the status of a single appointment based on current time.
    
    This function implements AUTOMATIC status transitions:
    - Booked → Waiting: When current time reaches appointment time
    - Booked → Missed: If patient doesn't arrive within 15-minute grace period
    - Waiting → Missed: If patient doesn't arrive within 45-minute no-show window
      (15min grace + 30min extra waiting time)
    
    MANUAL transitions (handled by doctor actions):
    - Waiting → In-Consultation: Doctor clicks "Start Consultation"
    - In-Consultation → Completed: Doctor clicks "Complete Consultation"
    
    Args:
        appointment_id (int): The ID of the appointment to update
        
    Returns:
        str: The new status of the appointment, or None if update failed
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get appointment details
        cursor.execute("""
            SELECT * FROM appointments WHERE id=%s
        """, (appointment_id,))
        
        appointment = cursor.fetchone()
        
        if not appointment:
            conn.close()
            return None
        
        # Calculate effective status based on current time
        new_status = get_effective_status(appointment)
        
        # Update database if status changed
        if new_status != appointment['status']:
            cursor.execute("""
                UPDATE appointments SET status=%s WHERE id=%s
            """, (new_status, appointment_id))
            conn.commit()
        
        conn.close()
        return new_status
        
    except Exception as e:
        print(f"Error updating appointment {appointment_id}: {str(e)}")
        return None


def update_all_appointment_statuses():
    """
    Background job that updates all active appointment statuses.
    
    This function is called by APScheduler every 1 minute.
    It processes all appointments that are not in a final state
    (Completed, Cancelled, or Missed) and updates their status
    based on the current time.
    
    The function includes error handling to prevent one failed
    appointment from stopping the entire batch update.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get all active appointments (not in final state)
        cursor.execute("""
            SELECT id FROM appointments 
            WHERE status NOT IN ('Completed', 'Cancelled', 'Missed')
            AND date >= CURDATE()
        """)
        
        appointments = cursor.fetchall()
        conn.close()
        
        # Update each appointment
        updated_count = 0
        failed_count = 0
        
        for apt in appointments:
            result = update_single_appointment_status(apt['id'])
            if result:
                updated_count += 1
            else:
                failed_count += 1
        
        if updated_count > 0 or failed_count > 0:
            print(f"[Scheduler] Appointment status update: {updated_count} updated, {failed_count} failed")
            
    except Exception as e:
        print(f"[Scheduler] Error in batch update: {str(e)}")


# Add the scheduler job - runs every 15 seconds
scheduler.add_job(
    func=update_all_appointment_statuses,
    trigger=IntervalTrigger(seconds=15),
    id='update_appointment_statuses',
    name='Update appointment statuses every 15 seconds',
    replace_existing=True
)

print("[Scheduler] Background job scheduled: update_appointment_statuses every 15 seconds")


# =========================
# SPECIALIST DESCRIPTIONS
# =========================
SPECIALTY_DESCRIPTIONS = {

    "General Medicine": "Fever, Cough, Flu & Common Illnesses",

    "Family Medicine": "Health Check-ups, Common Illnesses & Family Care",

    "Internal Medicine": "Adult Health Conditions & Chronic Diseases",

    "Pediatrics": "Children & Babies",

    "Emergency Medicine": "Medical Emergencies & Urgent Care",

    "Dermatology": "Skin Problems",

    "Cardiology": "Heart Problems",

    "Orthopedics": "Bone, Joint & Muscle Problems",

    "ENT": "Ear, Nose & Throat Problems",

    "Ophthalmology": "Eye Problems",

    "Obstetrics & Gynaecology": "Pregnancy & Women's Health Care",

    "Psychiatry": "Mental Health",

    "Neurology": "Brain & Nervous System Problems",

    "Dental": "Teeth & Oral Care",

    "Physiotherapy": "Rehabilitation & Physical Therapy"

}
# =========================
# GENERATE TIME SLOTS
# =========================
def generate_time_slots(opening_time, closing_time):

    slots = []

    # Convert MySQL TIME (timedelta) to HH:MM
    open_minutes = int(opening_time.total_seconds() // 60)
    close_minutes = int(closing_time.total_seconds() // 60)

    # Last appointment starts 30 minutes before closing
    current = open_minutes

    while current < close_minutes:

        hour = current // 60
        minute = current % 60

        slots.append(f"{hour:02}:{minute:02}")

        current += 30

    # Remove slot that starts exactly at closing
    if slots:

        last = slots[-1]

        if last == f"{close_minutes//60:02}:{close_minutes%60:02}":

            slots.pop()

    return slots

# =========================
# GET AVAILABLE TIME SLOTS
# =========================
def get_available_time_slots(
    doctor_id,
    selected_date,
    appointments,
    opening_time,
    closing_time
):

    all_slots = generate_time_slots(
    opening_time,
    closing_time
)

    available_slots = []

    today = datetime.now().strftime("%Y-%m-%d")

    current_time = datetime.now().strftime("%H:%M")

    for slot in all_slots:

        # -------------------------
        # Skip past slots if booking today
        # -------------------------
        if selected_date == today:

            if slot <= current_time:

                continue

        booked = False

        for apt in appointments:

            appointment_date = apt["date"]

            if hasattr(appointment_date, "strftime"):
                appointment_date = appointment_date.strftime("%Y-%m-%d")

            if (
                str(apt["doctor_id"]) == str(doctor_id)
                and appointment_date == selected_date
                and apt["time"] == slot
                and apt["status"] in (
                    "Booked",
                    "Waiting",
                    "In-Consultation"
                )
            ):

                booked = True
                break

        if not booked:

            available_slots.append(slot)

    return available_slots


# =========================
# AJAX AVAILABLE SLOT API
# =========================
@app.route('/get_available_slots')
def get_available_slots():

    doctor_id = request.args.get('doctor_id')
    selected_date = request.args.get('date')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get appointments
    cursor.execute("""
        SELECT *
        FROM appointments
        WHERE date=%s
    """, (selected_date,))
    appointments = cursor.fetchall()

    # Get doctor's clinic operating hours
    cursor.execute("""
        SELECT c.opening_time, c.closing_time
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        WHERE d.id=%s
    """, (doctor_id,))
    clinic = cursor.fetchone()

    available_slots = get_available_time_slots(
        doctor_id,
        selected_date,
        appointments,
        clinic['opening_time'],
        clinic['closing_time']
    )

    conn.close()

    return {
        "available_slots": available_slots
    }


# =========================
# AJAX QUEUE INFO API
# =========================
@app.route('/get_queue_info')
def get_queue_info():

    doctor_name = request.args.get(
        'doctor_name'
    )

    selected_date = request.args.get(
        'date'
    )

    clinic = request.args.get(
        'clinic'
    )

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM appointments

        WHERE clinic_id=%s
        AND date=%s
        AND doctor_name=%s
        AND status IN
        ('Booked', 'Waiting', 'In-Consultation')

    """, (

        clinic,
        selected_date,
        doctor_name

    ))

    result = cursor.fetchone()

    conn.close()

    return {

        "current_queue": result['total']

    }


# =========================
# HOME PAGE
# =========================
@app.route('/')
def home():

    return render_template('index.html')


# =========================
# PATIENT REGISTRATION
# =========================
@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        full_name = request.form['full_name']
        age = request.form['age']
        gender = request.form['gender']
        contact_number = request.form['contact_number']
        email = request.form['email']
        address = request.form['address']
        emergency_contact = request.form['emergency_contact']
        allergies = request.form['allergies']
        medical_history = request.form['medical_history']
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash("Passwords do not match!", "danger")
            return render_template('patient_register.html')

        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute(

            "SELECT * FROM patients WHERE username=%s OR email=%s",

            (username, email)

        )

        existing_user = cursor.fetchone()

        if existing_user:

            conn.close()

            flash("Username or Email already exists!", "danger")
            return render_template('patient_register.html')

        cursor.execute("""

            INSERT INTO patients
            (
                full_name,
                age,
                gender,
                contact_number,
                email,
                address,
                emergency_contact,
                allergies,
                medical_history,
                username,
                password
            )

            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)

        """, (

            full_name,
            age,
            gender,
            contact_number,
            email,
            address,
            emergency_contact,
            allergies,
            medical_history,
            username,
            password

        ))

        conn.commit()

        conn.close()

        return redirect(url_for('patient_login'))

    return render_template('patient_register.html')


# =========================
# PATIENT LOGIN
# =========================
@app.route('/patient_login', methods=['GET', 'POST'])
def patient_login():

    if request.method == 'POST':

        username = request.form['username']

        password = request.form['password']

        conn = get_db_connection()

        cursor = conn.cursor(dictionary=True)

        cursor.execute(

            "SELECT * FROM patients WHERE username=%s AND password=%s",

            (username, password)

        )

        patient = cursor.fetchone()

        conn.close()

        if patient:

            session['patient_id'] = patient['id']

            session['patient_name'] = patient['full_name']

            return redirect(url_for('patient_dashboard'))

        else:

            return render_template(

                'patient_login.html',

                error="Invalid Username or Password"

            )

    return render_template('patient_login.html')


# =========================
# PATIENT DASHBOARD
# =========================
@app.route('/patient_dashboard')
def patient_dashboard():

    if 'patient_id' not in session:

        return redirect(url_for('patient_login'))

    patient_id = session['patient_id']

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # =========================
    # GET PATIENT INFO
    # =========================
    cursor.execute(

        "SELECT * FROM patients WHERE id=%s",

        (patient_id,)

    )

    patient = cursor.fetchone()

    # =========================
    # UPCOMING APPOINTMENTS
    # =========================
    cursor.execute("""

        SELECT *

        FROM appointments

        WHERE patient_id=%s

        AND status='Booked'

        AND
        (
            date > CURDATE()

            OR

            (
                date = CURDATE()

                AND time >= CURTIME()
            )
        )

        ORDER BY date ASC,
                time ASC

    """, (

        patient_id,

    ))

    upcoming_appointments = cursor.fetchall()


    # =========================
    # OTHER APPOINTMENTS
    # =========================
    cursor.execute("""

        SELECT *

        FROM appointments

        WHERE patient_id=%s

        AND status IN
        (
            'Waiting',
            'In-Consultation',
            'Completed',
            'Missed'
        )

        ORDER BY date DESC,
                time DESC

    """, (

        patient_id,

    ))

    appointments = cursor.fetchall()
    
    # Apply time-based status override
    for apt in appointments:
        if apt['status'] not in ['Completed', 'Cancelled', 'Missed', 'In-Consultation']:
            apt['status'] = get_effective_status(apt)

    # =========================
    # ACTIVE APPOINTMENT
    # =========================

    active_appointment = None

    # First priority:
    # Waiting or In-Consultation
    for appointment in appointments:

        if appointment["status"] in (
            "Waiting",
            "In-Consultation"
        ):

            active_appointment = appointment
            break

    # Second priority:
    # Next upcoming booked appointment
    if (
        active_appointment is None
        and upcoming_appointments
    ):

        active_appointment = upcoming_appointments[0]



    # =========================
    # GET NOTIFICATIONS
    # =========================
    cursor.execute("""

        SELECT *

        FROM notifications

        WHERE patient_id=%s

        ORDER BY id DESC

    """, (

        patient_id,

    ))

    notifications = cursor.fetchall()

    # =========================
    # RECENT CONSULTATION (MOST RECENT ONLY)
    # =========================
    cursor.execute("""

        SELECT
            c.id AS consultation_id,
            c.diagnosis,
            c.remarks,
            a.date,
            a.time,
            d.name AS doctor_name,
            d.clinic_name,
            d.specialist
        FROM consultations c
        JOIN appointments a ON c.appointment_id = a.id
        LEFT JOIN doctors d ON a.doctor_id = d.id
        WHERE a.patient_id=%s
          AND a.status='Completed'
          AND c.id = (
              SELECT MAX(c2.id)
              FROM consultations c2
              WHERE c2.appointment_id = a.id
          )
        ORDER BY a.date DESC, a.time DESC
        LIMIT 1

    """, (

        patient_id,

    ))

    recent_consultation = cursor.fetchone()
    
    # Get prescription summary for the most recent consultation
    prescription_summary = None
    if recent_consultation:
        cursor.execute("""

            SELECT 
                medicine_name,
                dosage,
                frequency,
                duration
            FROM prescriptions
            WHERE consultation_id=%s
            LIMIT 3

        """, (

            recent_consultation['consultation_id'],

        ))

        prescription_summary = cursor.fetchall()

    conn.close()

    return render_template(

        'patient_dashboard.html',

        patient=patient,

        appointments=appointments,

        upcoming_appointments=upcoming_appointments,

        active_appointment=active_appointment,

        notifications=notifications,

        recent_consultation=recent_consultation,

        prescription_summary=prescription_summary

    )


# =========================
# DOCTOR LOGIN
# =========================
@app.route('/doctor_login', methods=['GET', 'POST'])
def doctor_login():

    if request.method == 'POST':

        login = request.form['login']

        password = request.form['password']

        clinic_code = request.form['clinic_code']

        conn = get_db_connection()

        cursor = conn.cursor(dictionary=True)

        cursor.execute("""

            SELECT *

            FROM doctors

            WHERE (email=%s OR username=%s)

            AND password=%s

            AND clinic_code=%s

        """, (

            login,
            login,
            password,
            clinic_code

        ))

        doctor = cursor.fetchone()

        conn.close()

        if doctor:

            session['doctor_id'] = doctor['id']

            session['doctor_name'] = doctor['name']

            return redirect(url_for('doctor_dashboard'))

        else:

            return render_template(

                'doctor_login.html',

                error="Invalid Doctor Credentials"

            )

    return render_template('doctor_login.html')


# =========================
# BOOKING PAGE
# =========================
@app.route('/booking')
def booking():

    if 'patient_id' not in session:

        return redirect(url_for('patient_login'))

    location = request.args.get('location')

    clinics = []

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    if location:

        cursor.execute(

            "SELECT * FROM clinics WHERE location=%s",

            (location,)

        )

        clinics = cursor.fetchall()


    for clinic in clinics:

            if clinic['opening_time']:
                total_seconds = int(clinic['opening_time'].total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                clinic['opening_time_str'] = f"{hours:02d}:{minutes:02d}"
            else:
                clinic['opening_time_str'] = ""

            if clinic['closing_time']:
                total_seconds = int(clinic['closing_time'].total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                clinic['closing_time_str'] = f"{hours:02d}:{minutes:02d}"
            else:
                clinic['closing_time_str'] = ""

    # =========================
    # CLINIC STATUS CALCULATION
    # =========================

    current_time = timedelta(

        hours=datetime.now().hour,
        minutes=datetime.now().minute,
        seconds=datetime.now().second

    )

    for clinic in clinics:

        # Manual Clinic Status
        if clinic['status'] == "Temporary Closed":

            clinic['display_status'] = "Temporary Closed"

        elif clinic['status'] == "Permanently Closed":

            clinic['display_status'] = "Permanently Closed"

        # Automatic Current Status
        elif (

            clinic['opening_time']
            <= current_time
            <= clinic['closing_time']

        ):

            clinic['display_status'] = "Open"

        else:

            clinic['display_status'] = "Closed"

        # =========================
        # LOAD ACTIVE DOCTORS
        # =========================

        cursor.execute("""
        SELECT
            id,
            name,
            specialist,
            status,
            availability

        FROM doctors

        WHERE clinic_id=%s
        AND status='Active'
        AND availability='Available'

        """, (

            clinic['id'],

        ))

        clinic['doctors'] = cursor.fetchall()

        # =========================
        # ADD SPECIALIST DESCRIPTION
        # =========================

        for doctor in clinic['doctors']:

            doctor['description'] = SPECIALTY_DESCRIPTIONS.get(

                doctor['specialist'],

                ""

            )

        # =========================
        # CLINIC WAITING TIME
        # =========================

        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND status IN
            (
                'Booked',
                'Waiting',
                'In-Consultation'
            )

        """, (

            clinic['id'],

        ))

        queue_result = cursor.fetchone()

        clinic['waiting_patients'] = queue_result['total']

        cursor.execute("""

            SELECT AVG(consultation_duration)
            AS avg_duration

            FROM doctors

            WHERE clinic_id=%s
            AND status='Active'
            AND availability='Available'

        """, (

            clinic['id'],

        ))

        duration_result = cursor.fetchone()

        avg_duration = (

            duration_result['avg_duration']

            if duration_result['avg_duration']

            else 15

        )

        clinic['dynamic_waiting_time'] = round(

            clinic['waiting_patients']
            *
            avg_duration

        )

    conn.close()

    return render_template(

        'booking.html',

        clinics=clinics,

        selected_location=location if location else ""

    )

# =========================
# TRIAGE PAGE
# =========================
@app.route('/triage')
def triage():

    clinic = request.args.get('clinic')

    if 'patient_id' not in session:

        return redirect(url_for('patient_login'))

    patient_id = session['patient_id']

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute(

        "SELECT * FROM patients WHERE id=%s",

        (patient_id,)

    )

    patient = cursor.fetchone()

    conn.close()

    return render_template(

        'ai_triage.html',

        clinic=clinic,

        patient=patient

    )



# =========================
# AJAX PRIORITY CALCULATION
# =========================
@app.route('/calculate_priority', methods=['POST'])
def calculate_priority():

    symptoms = request.form['symptoms'].lower()

    duration = request.form['duration']

    severity = request.form['severity']

    urgency = request.form['urgency']

    age = int(request.form['age'])

    score = 0

    # =========================
    # SEVERITY SCORE
    # =========================
    if severity == "Mild":

        score += 10

    elif severity == "Moderate":

        score += 25

    else:

        score += 40

    # =========================
    # DURATION SCORE
    # ========================= 
    if duration == "Less than 24 hours":

        score += 15

    elif duration == "1-3 days":

        score += 12

    elif duration == "4-7 days":

        score += 8

    elif duration == "1-2 weeks":

        score += 5

    else:

        score += 3

    # =========================
    # AGE SCORE
    # =========================
    if age >= 65:

        score += 20

    elif age < 18:

        score += 15

    else:

        score += 5

    # =========================
    # EMERGENCY KEYWORDS
    # =========================
    emergency_keywords = [

        "chest pain",
        "difficulty breathing",
        "heart attack",
        "stroke",
        "seizure",
        "cannot breathe"

    ]

    warning_keywords = [

        "fever",
        "vomit",
        "rash",
        "infection",
        "dizziness"

    ]

    emergency_detected = False

    for word in emergency_keywords:

        if word in symptoms:

            emergency_detected = True

            score += 15

            break

    if not emergency_detected:

        for word in warning_keywords:

            if word in symptoms:

                score += 7

                break

    # =========================
    # URGENCY SCORE
    # =========================
    if urgency == "urgent":

        score += 10

    else:

        score += 3

    # =========================
    # PRIORITY LEVEL
    # =========================
    if score >= 70:

        priority = "HIGH"

    elif score >= 40:

        priority = "MEDIUM"

    else:

        priority = "LOW"

    return jsonify({

        "priority": priority,

        "score": score

    })

# =========================
# APPOINTMENT SLOT PAGE
# =========================
@app.route('/appointment_slot', methods=['GET', 'POST'])
def appointment_slot():




    if 'patient_id' not in session:

        return redirect(url_for('patient_login'))

    patient_id = session['patient_id']

    symptoms = request.form.get(
        'symptoms',
        ''
    ).strip().lower()

    # =========================
    # BACKEND SYMPTOM VALIDATION
    # =========================

    invalid_inputs = [

        "-",
        "test",
        "testing",
        "asdf",
        "abc",
        "hello",
        "hi",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "nothing",
        "n/a",
        "na",
        "none",
        "symptom",
        "symptoms"

    ]

    if len(symptoms) < 10:

        return """

        Please enter a more detailed
        symptom description.

        """

    if symptoms in invalid_inputs:

        return """

        Please describe your actual
        symptoms.

        """

    word_count = len(

        symptoms.split()

    )

    if word_count < 3:

        return """

        Please provide more information
        about your symptoms.

        """

    duration = request.form.get(
        'duration',
        ''
    )

    severity = request.form.get(
        'severity',
        ''
    )

    urgency = request.form.get(
        'urgency',
        'normal'
    )




    clinic = request.form.get(
        'clinic',
        ''
    )

    # =========================
    # CLINIC AVAILABILITY CHECK
    # =========================

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT *

        FROM clinics

        WHERE clinic_name=%s

    """, (

        clinic,

    ))

    clinic_info = cursor.fetchone()

    current_time = timedelta(

        hours=datetime.now().hour,
        minutes=datetime.now().minute,
        seconds=datetime.now().second

    )

    # Track whether clinic is currently outside operating hours
    clinic_is_closed = False

    if clinic_info:

        # =========================
        # MANUAL CLINIC STATUS
        # =========================
        if clinic_info['status'] == "Temporary Closed":

            conn.close()

            return """

            Booking unavailable.

            This clinic is temporarily closed.

            """

        if clinic_info['status'] == "Permanently Closed":

            conn.close()

            return """

            Booking unavailable.

            This clinic has been permanently closed.

            """

        # =========================
        # OPERATING HOURS CHECK
        # (Soft check — booking for future slots is still allowed)
        # =========================
        if not (

            clinic_info['opening_time']
            <= current_time
            <= clinic_info['closing_time']

        ):

            # Clinic is currently closed but we allow booking for next available slot
            clinic_is_closed = True

    # When clinic is closed, default to tomorrow so the AI finds future slots
    if clinic_is_closed:
        default_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        default_date = datetime.now().strftime('%Y-%m-%d')

    selected_date = request.form.get(

        'selected_date',

        default_date

    )

    # Keep recommendation date synchronized with the selected date
    recommended_date = selected_date

    selected_doctor_id = request.form.get(
        'doctor_id'
    )

    # =========================
    # DOCTOR AVAILABILITY CHECK
    # =========================

    if selected_doctor_id:

        cursor.execute("""

            SELECT
                availability,
                status

            FROM doctors

            WHERE id=%s

        """, (

            selected_doctor_id,

        ))

        selected_doctor = cursor.fetchone()

        if not selected_doctor:

            conn.close()

            return """

            Selected doctor not found.

            """

        if selected_doctor['status'] != "Active":

            conn.close()

            return """

            Selected doctor is no longer active.

            """

        if selected_doctor['availability'] != "Available":

            conn.close()

            return """

            Selected doctor is currently unavailable.

            Please select another doctor.

            """





    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute(

        "SELECT * FROM patients WHERE id=%s",

        (patient_id,)

    )

    patient = cursor.fetchone()

    age = int(patient['age'])

    # =========================
    # AI SCORE
    # =========================
    score = 0

    # SEVERITY
    if severity == "Mild":

        score += 10

    elif severity == "Moderate":

        score += 25

    else:

        score += 40

    # DURATION
    if duration == "Less than 24 hours":

        score += 15

    elif duration == "1-3 days":

        score += 12

    elif duration == "4-7 days":

        score += 8

    elif duration == "1-2 weeks":

        score += 5

    else:

        score += 3

    # AGE
    if age >= 65:

        score += 20

    elif age < 18:

        score += 15

    else:

        score += 5

    # =========================
    # EMERGENCY KEYWORDS
    # =========================
    emergency_keywords = [

        "chest pain",
        "difficulty breathing",
        "heart attack",
        "stroke",
        "seizure",
        "cannot breathe"

    ]

    warning_keywords = [

        "fever",
        "vomit",
        "rash",
        "infection",
        "dizziness"

    ]

    emergency_detected = False

    for word in emergency_keywords:

        if word in symptoms:

            emergency_detected = True

            score += 15

            break

    if not emergency_detected:

        for word in warning_keywords:

            if word in symptoms:

                score += 7

                break

    # =========================
    # URGENCY SCORE
    # =========================
    if urgency == "urgent":

        score += 10

    else:

        score += 3

    # =========================
    # PRIORITY LEVEL
    # =========================
    if score >= 70:

        priority = "HIGH"

    elif score >= 40:

        priority = "MEDIUM"

    else:

        priority = "LOW"

    # =========================
    # AI URGENCY OVERRIDE
    # =========================
    override_message = None

    # AUTO UPGRADE
    if (

        emergency_detected
        and urgency == "normal"

    ):

        urgency = "urgent"

        override_message = (

            "Emergency symptoms detected. "
            "Automatically upgraded "
            "to urgent priority."

        )

    # AUTO DOWNGRADE
    elif (

        priority == "LOW"
        and urgency == "urgent"

    ):

        urgency = "normal"

        override_message = (

            "Symptoms appear mild. "
            "Placed into normal queue."

        )

    # =========================
    # SPECIALIST DETECTION
    # =========================
    specialist = "Family Medicine"

    if (

        "chest pain" in symptoms
        or "heart" in symptoms
        or "palpitations" in symptoms

    ):

        specialist = "Cardiology"

    elif (

        "skin" in symptoms
        or "rash" in symptoms
        or "itch" in symptoms

    ):

        specialist = "Dermatology"

    elif (

        "bone" in symptoms
        or "joint" in symptoms
        or "knee" in symptoms

    ):

        specialist = "Orthopedic"

    elif (

        "headache" in symptoms
        or "migraine" in symptoms
        or "stroke" in symptoms

    ):

        specialist = "Neurology"

    elif (

        "stomach" in symptoms
        or "vomit" in symptoms
        or "gastric" in symptoms

    ):

        specialist = "Gastroenterology"

    elif (

        "breathing" in symptoms
        or "asthma" in symptoms
        or "lung" in symptoms

    ):

        specialist = "Respiratory Medicine"

    elif (

        "fever" in symptoms
        or "flu" in symptoms

    ):

        specialist = "General Medicine"

# =========================
# GET DOCTORS
# =========================
    cursor.execute("""
    SELECT *
    FROM doctors
    WHERE specialist=%s
    AND clinic_name=%s
    AND status='Active'
    AND availability='Available'
    """, (
        specialist,
        clinic
    ))

    doctors = cursor.fetchall()

    # ---------------------------------------
    # Fallback if no specialist doctor exists
    # ---------------------------------------
    if not doctors:

        cursor.execute("""
        SELECT *
        FROM doctors
        WHERE clinic_name=%s
        AND status='Active'
        AND availability='Available'
        """, (
            clinic,
        ))

        doctors = cursor.fetchall()

    # =========================
    # GET APPOINTMENTS
    # =========================
    cursor.execute("""
        SELECT *
        FROM appointments
        WHERE date=%s
        AND clinic_id=%s
    """, (
        selected_date,
        clinic_info["id"]
    ))

    appointments = cursor.fetchall()


    # =========================
    # NEXT AVAILABLE DATE
    # =========================

    recommended_date = selected_date

    today = datetime.now().date()

    selected_date_obj = datetime.strptime(
        selected_date,
        "%Y-%m-%d"
    ).date()

    recommended_doctor = None

    recommended_slot = None

    available_slots = []

    recommended_queue = 0

    next_available_found = False

    estimated_wait = 0

    recommendation_reason = ""

    # =========================
    # SMART AUTO RECOMMENDATION
    # =========================
    if not selected_doctor_id:

        best_score = 999999

        for doctor in doctors:

            slots = get_available_time_slots(
                doctor['id'],
                selected_date,
                appointments,
                clinic_info['opening_time'],
                clinic_info['closing_time']
            )

            doctor['available_slots'] = slots


            if not slots:

                # ---------------------------------
                # If booking today, search next day
                # ---------------------------------

                if selected_date_obj == today:

                    for i in range(1,8):

                        next_date = (
                            today +
                            timedelta(days=i)
                        ).strftime("%Y-%m-%d")

                        cursor.execute("""

                            SELECT *

                            FROM appointments

                            WHERE date=%s

                        """,(next_date,))

                        next_day_appointments = cursor.fetchall()

                        next_slots = get_available_time_slots(

                            doctor['id'],

                            next_date,

                            next_day_appointments,

                            clinic_info['opening_time'],

                            clinic_info['closing_time']

                        )

                        if next_slots:

                            recommended_date = next_date

                            slots = next_slots

                            next_available_found = True

                            break

                if not slots:

                    continue
          

            # =========================
            # AI RECOMMENDED SLOT
            # =========================

            recommended_slots = sorted(slots)

            earliest_slot = recommended_slots[0]

            # =========================
            # CURRENT QUEUE
            # =========================
            current_queue = 0

            for apt in appointments:

                if (

                    str(apt['doctor_id']) == str(doctor['id'])
                    and apt['status']
                    in ['Booked', 'Waiting', 'In-Consultation']

                ):

                    current_queue += 1

            # =========================
            # SLOT TIME SCORE
            # =========================
            hour = int(

                earliest_slot.split(":")[0]

            )

            minute = int(

                earliest_slot.split(":")[1]

            )

            slot_minutes = (

                hour * 60 +
                minute

            )

            # =========================
            # SMART PRIORITY LOGIC
            # =========================
            if priority == "HIGH":

                smart_score = (

                    slot_minutes +
                    (current_queue * 5)

                )

                recommendation_reason = (

                    "Earliest available slot "
                    "for urgent care"

                )

            elif priority == "MEDIUM":

                smart_score = (

                    slot_minutes +
                    (current_queue * 10)

                )

                recommendation_reason = (

                    "Balanced queue and slot time"

                )

            else:

                smart_score = (

                    slot_minutes +
                    (current_queue * 15)

                )

                recommendation_reason = (

                    "Shortest queue recommendation"

                )

            # =========================
            # BEST DOCTOR
            # =========================
            if smart_score < best_score:

                best_score = smart_score

                recommended_doctor = doctor

                recommended_slot = earliest_slot

                available_slots = slots

                recommended_queue = current_queue

    # =========================
    # MANUAL DOCTOR CHANGE
    # =========================
    else:

        selected_doctor = None

        for doctor in doctors:
            if str(doctor["id"]) == str(selected_doctor_id):
                selected_doctor = doctor
                break

        # If selected doctor no longer exists
        if selected_doctor is None:

            # Fallback to first available doctor
            if doctors:
                selected_doctor = doctors[0]
            else:
                conn.close()
                return "No available doctors found."

        # These lines MUST be outside the if-block
        recommended_doctor = selected_doctor
        recommended_date = selected_date



        # Reload appointments for the selected clinic and date
        cursor.execute("""
            SELECT *
            FROM appointments
            WHERE clinic_id=%s
            AND date=%s
        """, (
            clinic_info["id"],
            selected_date
        ))

        appointments = cursor.fetchall()

        available_slots = get_available_time_slots(
            recommended_doctor["id"],
            selected_date,
            appointments,
            clinic_info["opening_time"],
            clinic_info["closing_time"]
)
        recommended_doctor["available_slots"] = available_slots

        recommended_queue = sum(
            1 for apt in appointments
            if str(apt["doctor_id"]) == str(recommended_doctor["id"])
            and apt["status"] in (
                "Booked",
                "Waiting",
                "In-Consultation"
            )
        )

        recommended_slot = (
            sorted(available_slots)[0]
            if available_slots else None
        )

    # =========================
    # NO DOCTOR
    # =========================
    if recommended_doctor is None:

        conn.close()

        return """

        No doctors available
        for this specialist.

        """




    # =========================
    # SAVE TRIAGE RESULT
    # =========================
    if symptoms:

        cursor = conn.cursor()

        cursor.execute("""

            INSERT INTO triage_results
            (
                patient_id,
                clinic_name,
                symptoms,
                duration,
                severity,
                urgency,
                age,
                ai_score,
                priority_level,
                emergency_detected
            )

            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)

        """, (

            patient_id,
            clinic,
            symptoms,
            duration,
            severity,
            urgency,
            age,
            score,
            priority,
            str(emergency_detected)

        ))

        conn.commit()
        triage_id = cursor.lastrowid
        session['triage_id'] = triage_id

    # =========================
    # CURRENT QUEUE
    # =========================
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT COUNT(*) AS total
    FROM appointments
    WHERE clinic_id=%s
    AND date=%s
    AND doctor_id=%s
    AND status IN ('Booked','Waiting','In-Consultation')
    """, (

        clinic_info['id'],
        selected_date,
        recommended_doctor['id']

    ))

    queue_result = cursor.fetchone()

    current_queue = queue_result['total']

    # =========================
    # DOCTOR WAITING TIME
    # =========================

    consultation_duration = (

        recommended_doctor['consultation_duration']

        if recommended_doctor['consultation_duration']

        else 15

    )

    estimated_wait = (

        current_queue
        *
        consultation_duration

    )

    # =========================
    # RECALCULATE SLOTS FOR SELECTED_DATE
    # =========================
    # Ensure available_slots match the selected_date being displayed
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT *
        FROM appointments
        WHERE clinic_id=%s
        AND date=%s
    """, (
        clinic_info['id'],
        selected_date
    ))
    selected_date_appointments = cursor.fetchall()

    available_slots = get_available_time_slots(
        recommended_doctor['id'],
        selected_date,
        selected_date_appointments,
        clinic_info['opening_time'],
        clinic_info['closing_time']
    )

    conn.close()



    return render_template(
        'select_slot.html',
        patient=patient,
        clinic=clinic,
        symptoms=symptoms,
        severity=severity,
        duration=duration,
        urgency=urgency,
        priority=priority,
        specialist=specialist,
        doctors=doctors,
        doctor_name=recommended_doctor['name'],
        doctor_id=recommended_doctor['id'],
        suggested_time=recommended_slot,
        available_slots=available_slots,
        selected_date=selected_date,

        generate_time_slots=generate_time_slots(
            clinic_info['opening_time'],
            clinic_info['closing_time']
        ),

        override_message=override_message,
        current_queue=current_queue,
        recommended_queue=recommended_queue,
        estimated_wait=estimated_wait,
        consultation_duration=consultation_duration,
        recommendation_reason=recommendation_reason,
        recommended_date=recommended_date,
        today=datetime.now().strftime('%Y-%m-%d'),
        clinic_is_closed=clinic_is_closed
    )



# =========================
# CONFIRM BOOKING
# =========================
@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():

    if 'patient_id' not in session:

        return redirect(url_for('patient_login'))

    patient_id = session['patient_id']

    triage_id = session.get('triage_id')

    doctor_id = request.form['doctor_id']

    doctor_name = request.form['doctor_name']

    specialist = request.form['specialist']

    clinic = request.form['clinic']

    priority = request.form['priority']

    urgency = request.form['urgency']

    selected_date = request.form['selected_date']

    selected_time = request.form['selected_time']

    # =========================
    # VALIDATE APPOINTMENT TIME
    # =========================

    appointment_datetime = datetime.strptime(

        f"{selected_date} {selected_time}",

        "%Y-%m-%d %H:%M"

    )

    current_datetime = datetime.now()

    if appointment_datetime <= current_datetime:

        flash(

            "This appointment time has already passed. Please select another available slot.",

            "danger"

        )

        return redirect(url_for("booking"))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # =========================
    # GET CLINIC ID
    # =========================
    cursor.execute("""

        SELECT id

        FROM clinics

        WHERE clinic_name=%s

    """, (

        clinic,

    ))

    clinic_info = cursor.fetchone()

    if not clinic_info:

        conn.close()

        return "Clinic not found."

    clinic_id = clinic_info['id']

    # =========================
    # VALIDATE CLINIC STATUS
    # =========================

    cursor.execute("""

        SELECT
            status,
            opening_time,
            closing_time

        FROM clinics

        WHERE id=%s

    """, (

        clinic_id,

    ))

    clinic_status = cursor.fetchone()

    if not clinic_status:

        conn.close()

        flash(

            "Clinic not found.",

            "danger"

        )

        return redirect(url_for("booking"))

    # -------------------------
    # Manual clinic status
    # -------------------------

    if clinic_status["status"] == "Temporary Closed":

        conn.close()

        flash(

            "This clinic is temporarily closed. Please choose another clinic.",

            "warning"

        )

        return redirect(url_for("booking"))

    if clinic_status["status"] == "Permanently Closed":

        conn.close()

        flash(

            "This clinic is permanently closed. Please choose another clinic.",

            "danger"

        )

        return redirect(url_for("booking"))



    # =========================
    # VALIDATE DOCTOR STATUS
    # =========================

    cursor.execute("""

        SELECT
            status,
            availability

        FROM doctors

        WHERE id=%s

    """, (

        doctor_id,

    ))

    doctor_status = cursor.fetchone()

    if not doctor_status:

        conn.close()

        flash(

            "Doctor not found.",

            "danger"

        )

        return redirect(url_for("booking"))

    # Doctor must be Active
    if doctor_status['status'] != "Active":

        conn.close()

        flash(

            "This doctor is no longer active. Please choose another doctor.",

            "warning"

        )

        return redirect(url_for("booking"))

    # Doctor must be Available
    if doctor_status['availability'] != "Available":

        conn.close()

        flash(

            "This doctor is currently unavailable. Please choose another available doctor.",

            "warning"

        )

        return redirect(url_for("booking"))

    # =========================
    # SMART QUEUE POSITION
    # =========================
    # HIGH + URGENT GOES FIRST


    is_urgent_priority = (

        priority == 'HIGH'
        and urgency.lower()
        in ['urgent', 'very urgent']

    )

    # =========================
    # HIGH URGENT
    # =========================
    if is_urgent_priority:

        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND priority='HIGH'
            AND LOWER(urgency) IN
            ('urgent','very urgent')
            AND status IN
            ('Booked','Waiting','In-Consultation')

        """, (

            clinic_id,
            selected_date

        ))

        result = cursor.fetchone()

        patients_ahead = result['total']

    # =========================
    # NORMAL PATIENTS
    # =========================
    else:

        # HIGH URGENT FIRST
        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND priority='HIGH'
            AND LOWER(urgency) IN
            ('urgent','very urgent')
            AND status IN
            ('Booked','Waiting','In-Consultation')

        """, (

            clinic_id,
            selected_date

        ))

        urgent_result = cursor.fetchone()

        urgent_patients = urgent_result['total']

        # NORMAL TIME ORDER
        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND time < %s
            AND status IN
            ('Booked','Waiting','In-Consultation')

        """, (

            clinic_id,
            selected_date,
            selected_time

        ))

        normal_result = cursor.fetchone()

        normal_patients = normal_result['total']

        patients_ahead = (

            urgent_patients +
            normal_patients

        )

    # =========================
    # FINAL POSITION
    # =========================
    queue_number = patients_ahead + 1

    # =========================
    # GET DOCTOR DURATION
    # =========================
    cursor.execute("""

        SELECT consultation_duration

        FROM doctors

        WHERE id=%s

    """, (

        doctor_id,

    ))

    doctor_info = cursor.fetchone()

    consultation_duration = (

        doctor_info['consultation_duration']

        if doctor_info
        and doctor_info['consultation_duration']

        else 15

    )

    # =========================
    # WAIT TIME FORMULA
    # =========================
    if patients_ahead == 0:

        wait_time_minutes = 0

    else:

        if priority == "HIGH":

            multiplier = 0.7

        elif priority == "MEDIUM":

            multiplier = 1.0

        else:

            multiplier = 1.2

        wait_time_minutes = (

            patients_ahead
            *
            consultation_duration
            *
            multiplier

        )

    wait_time_minutes = round(
        wait_time_minutes
    )

    wait_time = f"{wait_time_minutes} minutes"


     # =========================
    # DOUBLE BOOKING CHECK
    # =========================

    cursor.execute("""

    SELECT COUNT(*) AS total

    FROM appointments

    WHERE doctor_id=%s
    AND date=%s
    AND time=%s
    AND status IN
    (
        'Booked',
        'Waiting',
        'In-Consultation'
    )

    """, (

        doctor_id,
        selected_date,
        selected_time

    ))

    existing_slot = cursor.fetchone()

    if existing_slot['total'] > 0:

        flash(

            "Sorry, this appointment slot has just been booked by another patient. Please choose another available slot.",

            "warning"

        )

        conn.close()

        return redirect(url_for("booking"))
    

    # =========================
    # RECALCULATE QUEUE
    # =========================

    if is_urgent_priority:

        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND priority='HIGH'
            AND LOWER(urgency) IN
            ('urgent','very urgent')
            AND status IN
            ('Booked','Waiting','In-Consultation')

        """, (

            clinic_id,
            selected_date

        ))

        result = cursor.fetchone()

        patients_ahead = result['total']

    else:

        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND priority='HIGH'
            AND LOWER(urgency) IN
            ('urgent','very urgent')
            AND status IN
            ('Booked','Waiting','In-Consultation')

        """, (

            clinic_id,
            selected_date

        ))

        urgent_result = cursor.fetchone()

        urgent_patients = urgent_result['total']

        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND time < %s
            AND status IN
            ('Booked','Waiting','In-Consultation')

        """, (

            clinic_id,
            selected_date,
            selected_time

        ))

        normal_result = cursor.fetchone()

        normal_patients = normal_result['total']

        patients_ahead = urgent_patients + normal_patients


    # =========================
    # UPDATED QUEUE NUMBER
    # =========================

    queue_number = patients_ahead + 1

    # =========================
    # RECALCULATE WAITING TIME
    # =========================

    if patients_ahead == 0:

        wait_time_minutes = 0

    else:

        if priority == "HIGH":

            multiplier = 0.7

        elif priority == "MEDIUM":

            multiplier = 1.0

        else:

            multiplier = 1.2

        wait_time_minutes = round(

            patients_ahead *
            consultation_duration *
            multiplier

        )

    wait_time = f"{wait_time_minutes} minutes"


    # =========================
    # INSERT APPOINTMENT
    # =========================
    

    cursor.execute("""

    INSERT INTO appointments
    (
        patient_id,
        doctor_id,
        doctor_name,
        specialist,
        clinic,
        clinic_id,
        date,
        time,
        queue_number,
        priority,
        urgency,
        wait_time,
        status,
        triage_id
    )
    VALUES
    (
        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
    )

    """, (

        patient_id,
        doctor_id,
        doctor_name,
        specialist,
        clinic,
        clinic_id,          # <-- ADD THIS
        selected_date,
        selected_time,
        queue_number,
        priority,
        urgency,
        wait_time,
        "Booked",
        triage_id

    ))

    conn.commit()
    appointment_id = cursor.lastrowid

    # =========================
    # CREATE NOTIFICATION
    # =========================
    cursor.execute("""

        INSERT INTO notifications
        (
            patient_id,
            title,
            message
        )

        VALUES (%s,%s,%s)

    """, (

        patient_id,

        "Appointment Confirmed",

        f"""
        Your appointment with
        {doctor_name}
        on {selected_date}
        at {selected_time}
        has been confirmed.

        Queue Number: #{queue_number}

        Estimated Wait Time:
        {wait_time}
        """

    ))

    conn.commit()

    conn.close()

    return render_template(

        'appointment_confirmed.html',

        appointment_id=appointment_id,

        doctor_name=doctor_name,

        specialist=specialist,

        clinic=clinic,

        selected_date=selected_date,

        selected_time=selected_time,

        priority=priority,

        urgency=urgency,

        queue_number=queue_number,

        wait_time=wait_time

    )


# =========================
# CANCEL APPOINTMENT
# =========================
@app.route('/cancel_appointment/<int:appointment_id>')
def cancel_appointment(appointment_id):

    if 'patient_id' not in session:

        return redirect(url_for('patient_login'))

    patient_id = session['patient_id']

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # =========================
    # GET APPOINTMENT
    # =========================
    cursor.execute("""

        SELECT *

        FROM appointments

        WHERE id=%s
        AND patient_id=%s

    """, (

        appointment_id,
        patient_id

    ))

    appointment = cursor.fetchone()

    if not appointment:

        conn.close()

        return redirect(url_for('patient_dashboard'))

    # =========================
    # CANCEL APPOINTMENT
    # =========================
    cursor.execute("""

        UPDATE appointments

        SET status='Cancelled'

        WHERE id=%s

    """, (

        appointment_id,

    ))

    # =========================
    # CREATE NOTIFICATION
    # =========================
    cursor.execute("""

        INSERT INTO notifications
        (
            patient_id,
            title,
            message
        )

        VALUES (%s,%s,%s)

    """, (

        patient_id,

        "Appointment Cancelled",

        f"""
        Your appointment with
        {appointment['doctor_name']}
        on {appointment['date']}
        at {appointment['time']}
        has been cancelled successfully.

        The slot is now available
        for other patients.
        """

    ))

    conn.commit()

    conn.close()

    # =========================
    # SHOW RESCHEDULE POPUP
    # =========================
    return redirect(

        url_for(

            'patient_dashboard',

            cancelled='true'

        )

    )



# =========================
# LIVE QUEUE API
# =========================
@app.route('/live_queue/<int:appointment_id>')
def live_queue(appointment_id):

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # =========================
    # GET CURRENT APPOINTMENT
    # =========================
    # Status is calculated dynamically based on current time
    # so it changes EXACTLY at appointment time, not just when scheduler runs
    cursor.execute("""

        SELECT *

        FROM appointments

        WHERE id=%s

    """, (

        appointment_id,

    ))

    appointment = cursor.fetchone()
    
    # Calculate effective status based on current time
    if appointment:
        effective_status = get_effective_status(appointment)
        appointment['status'] = effective_status

    if not appointment:

        conn.close()

        return jsonify({

            "error": "Appointment not found"

        })

    # =========================
    # CHECK HIGH + URGENT
    # =========================
    is_urgent_priority = (

        appointment['priority'] == 'HIGH'
        and appointment['urgency'].lower()
        in ['urgent', 'very urgent']

    )

    # =========================
    # HIGH URGENT GOES FIRST
    # =========================
    if is_urgent_priority:

        patients_ahead = 0

    # =========================
    # NORMAL PATIENTS
    # =========================
    else:

        # COUNT HIGH URGENT PATIENTS
        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND priority='HIGH'
            AND LOWER(urgency) IN
            ('urgent','very urgent')
            AND status IN
            ('Booked','Waiting','In-Consultation')

        """, (

           appointment['clinic_id'],
            appointment['date']

        ))

        urgent_result = cursor.fetchone()

        urgent_patients = urgent_result['total']

        # =========================
        # NORMAL PATIENTS AHEAD
        # BASED ON APPOINTMENT TIME
        # =========================
        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic_id=%s
            AND date=%s
            AND status IN
            ('Booked','Waiting','In-Consultation')
            AND time < %s
            AND id != %s

        """, (

            appointment['clinic_id'],
            appointment['date'],
            appointment['time'],
            appointment['id']

        ))

        ahead_result = cursor.fetchone()

        normal_ahead = ahead_result['total']

        # =========================
        # FINAL
        # =========================
        patients_ahead = (

            normal_ahead +
            urgent_patients

        )

    # =========================
    # TOTAL QUEUE
    # =========================
    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM appointments

       WHERE clinic_id=%s
        AND date=%s
        AND status IN
        ('Booked','Waiting','In-Consultation')

    """, (

        appointment['clinic_id'],
        appointment['date']

    ))

    total_result = cursor.fetchone()

    total_queue = total_result['total']

    # =========================
    # CURRENT QUEUE POSITION
    # =========================

    queue_position = patients_ahead + 1

    # Safety check
    if total_queue == 0:

        queue_position = 0

    elif queue_position > total_queue:

        queue_position = total_queue


    # =========================
    # CURRENT POSITION
    # =========================
    current_position = patients_ahead + 1

    # =========================
    # PEOPLE WAITING
    # =========================
    people_waiting = (

        total_queue -
        current_position

    )

    if people_waiting < 0:

        people_waiting = 0

    # =========================
    # WAIT TIME
    # =========================

    cursor.execute("""

        SELECT consultation_duration

        FROM doctors

        WHERE id=%s

    """, (

        appointment['doctor_id'],

    ))

    doctor_info = cursor.fetchone()

    consultation_duration = (

        doctor_info['consultation_duration']

        if doctor_info
        and doctor_info['consultation_duration']

        else 15

    )

    priority = appointment['priority']

    if priority == "HIGH":

        multiplier = 0.7

    elif priority == "MEDIUM":

        multiplier = 1.0

    else:

        multiplier = 1.2

    wait_minutes = round(

        patients_ahead
        *
        consultation_duration
        *
        multiplier

    )

    wait_time = f"{wait_minutes} minutes"

    # =========================
    # PROGRESS %
    # =========================
    completed = total_queue - patients_ahead

    progress = round(

        (completed / total_queue) * 100

    ) if total_queue > 0 else 100

    # =========================
    # GET SYMPTOMS
    # =========================
    cursor.execute("""

        SELECT symptoms

        FROM triage_results

        WHERE id=%s

        

    """, (

        appointment['triage_id'],

    ))

    triage = cursor.fetchone()

    symptoms = ""

    if triage:

        symptoms = triage['symptoms']

    # =========================
    # NOW SERVING
    # =========================

    cursor.execute("""

        SELECT MIN(queue_number) AS now_serving

        FROM appointments

        WHERE clinic_id=%s
        AND date=%s
        AND status IN
        ('Booked','Waiting','In-Consultation')

    """, (

        appointment['clinic_id'],
        appointment['date']

    ))

    now_serving_result = cursor.fetchone()

    now_serving = now_serving_result['now_serving']

    if not now_serving:

        now_serving = 1

    conn.close()

    return jsonify({

        "doctor_name": appointment['doctor_name'],

        "clinic": appointment['clinic'],

        "priority": appointment['priority'],

        "urgency": appointment['urgency'],

        "queue_number": appointment['queue_number'],

        "now_serving": now_serving,

        "current_position": current_position,

        "patients_ahead": patients_ahead,

        "people_waiting": people_waiting,

        "wait_time": wait_time,

        "progress": progress,

        "total_queue": total_queue,

        "time": appointment['time'],

        "status": appointment['status'],

        "symptoms": symptoms,

        "queue_position": queue_position,

    })

# =========================
# LIVE QUEUE PAGE
# =========================
@app.route('/live_queue_page')
def live_queue_page():

    appointment_id = request.args.get(
        'appointment_id'
    )

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # =========================
    # GET APPOINTMENT
    # =========================
    cursor.execute("""

        SELECT *

        FROM appointments

        WHERE id=%s

    """, (

        appointment_id,

    ))

    appointment = cursor.fetchone()

    conn.close()

    if not appointment:

        return redirect(

            url_for('patient_dashboard')

        )

    # =========================
    # CHECK APPOINTMENT DATE
    # =========================
    today = datetime.now().date()

    appointment_date = appointment['date']

    is_today = (

        str(today) ==
        str(appointment_date)

    )

    return render_template(

        'live_queue.html',

        appointment_id=appointment_id,

        appointment=appointment,

        is_today=is_today

    )

# =========================
# DOCTOR DASHBOARD
# =========================
@app.route('/doctor_dashboard')
def doctor_dashboard():

    if 'doctor_id' not in session:
        return redirect(url_for('doctor_login'))

    doctor_id = session['doctor_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # =========================
    # DOCTOR INFO
    # =========================
    cursor.execute(
        "SELECT * FROM doctors WHERE id=%s",
        (doctor_id,)
    )

    doctor = cursor.fetchone()

    # =========================
    # NOW SERVING
    # =========================
    cursor.execute("""

        SELECT
            a.*,
            p.full_name

        FROM appointments a

        LEFT JOIN patients p
        ON a.patient_id = p.id

        WHERE a.doctor_id=%s
        AND a.status='In-Consultation'

        LIMIT 1

    """, (doctor_id,))

    now_serving = cursor.fetchone()

    # =========================
    # APPOINTMENTS
    # =========================
    cursor.execute("""

    SELECT
        a.*,
        p.full_name,
        t.symptoms

    FROM appointments a

    LEFT JOIN patients p
    ON a.patient_id = p.id

    LEFT JOIN triage_results t
    ON a.triage_id = t.id

    WHERE a.doctor_id=%s
    AND a.status != 'Cancelled'

    ORDER BY

    CASE

        WHEN a.priority='HIGH'
        AND LOWER(a.urgency)='very urgent'
        THEN 1

        WHEN a.priority='HIGH'
        AND LOWER(a.urgency)='urgent'
        THEN 2

        ELSE 3

    END,

    a.time ASC

""", (doctor_id,))

    appointments = cursor.fetchall()

    # Apply the effective status for time-based transitions before splitting
    # the appointments into tabs and counting statistics.
    for appt in appointments:
        appt['status'] = get_effective_status(appt)

    # =========================
    # SPLIT INTO TABS
    # =========================
    today = []
    upcoming = []
    completed = []
    missed = []

    current_date = datetime.now().strftime("%Y-%m-%d")

    for appt in appointments:

        appt_date = str(appt['date'])

        if appt['status'] == 'Completed' and appt_date == current_date:

            completed.append(appt)

        elif appt['status'] == 'Missed':

            missed.append(appt)

        elif appt_date > current_date:

            upcoming.append(appt)

        elif appt_date == current_date:

            today.append(appt)

    # =========================
    # STATISTICS
    # =========================
    today_count = len(today)

    queue_count = len([
        a for a in today
        if a['status'] in
        ['Booked', 'Waiting', 'In-Consultation']
    ])

    completed_count = len(completed)

    upcoming_count = len(upcoming)

    conn.close()

    return render_template(

        'doctor_dashboard.html',

        doctor=doctor,
        now_serving=now_serving,

        today=today,
        upcoming=upcoming,
        completed=completed,
        missed=missed,

        today_count=today_count,
        queue_count=queue_count,
        completed_count=completed_count,
        upcoming_count=upcoming_count

    )

# =========================
# DOCTOR DASHBOARD API (AJAX)
# =========================
@app.route('/api/doctor_dashboard_data')
def api_doctor_dashboard_data():

    if 'doctor_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    doctor_id = session['doctor_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Doctor info
    cursor.execute(
        "SELECT * FROM doctors WHERE id=%s",
        (doctor_id,)
    )
    doctor = cursor.fetchone()

    # Now serving
    cursor.execute("""
        SELECT a.*, p.full_name, t.symptoms
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        LEFT JOIN triage_results t ON a.triage_id = t.id
        WHERE a.doctor_id=%s AND a.status='In-Consultation'
        LIMIT 1
    """, (doctor_id,))
    now_serving = cursor.fetchone()

    # Appointments
    cursor.execute("""
        SELECT a.*, p.full_name, t.symptoms
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        LEFT JOIN triage_results t ON a.triage_id = t.id
        WHERE a.doctor_id=%s AND a.status != 'Cancelled'
        ORDER BY
            CASE
                WHEN a.priority='HIGH' AND LOWER(a.urgency)='very urgent' THEN 1
                WHEN a.priority='HIGH' AND LOWER(a.urgency)='urgent' THEN 2
                ELSE 3
            END,
            a.time ASC
    """, (doctor_id,))
    appointments = cursor.fetchall()

    # Calculate the current status on every poll so the UI does not have to
    # wait for the background scheduler's next run.
    for appt in appointments:
        appt['status'] = get_effective_status(appt)

    # Split into tabs
    today_list = []
    upcoming_list = []
    completed_list = []
    missed_list = []
    current_date = datetime.now().strftime("%Y-%m-%d")

    for appt in appointments:
        appt_date = str(appt['date'])
        if appt['status'] == 'Completed' and appt_date == current_date:
            completed_list.append(appt)
        elif appt['status'] == 'Missed':
            missed_list.append(appt)
        elif appt_date > current_date:
            upcoming_list.append(appt)
        elif appt_date == current_date:
            today_list.append(appt)

    # Statistics
    today_count = len(today_list)
    queue_count = len([a for a in today_list if a['status'] in ['Booked', 'Waiting', 'In-Consultation']])
    completed_count = len(completed_list)
    upcoming_count = len(upcoming_list)

    conn.close()

    # Serialize appointments
    def serialize_appointment(appt):
        return {
            'id': appt['id'],
            'patient_name': appt['full_name'],
            'queue_number': appt['queue_number'],
            'time': str(appt['time']),
            'date': str(appt['date']),
            'status': appt['status'],
            'priority': appt['priority'],
            'urgency': appt['urgency'],
            'symptoms': appt['symptoms'] or ''
        }

    return jsonify({
        'doctor': {
            'name': doctor['name'],
            'specialist': doctor['specialist'],
            'clinic_name': doctor['clinic_name']
        },
        'now_serving': serialize_appointment(now_serving) if now_serving else None,
        'today': [serialize_appointment(a) for a in today_list],
        'upcoming': [serialize_appointment(a) for a in upcoming_list],
        'completed': [serialize_appointment(a) for a in completed_list],
        'missed': [serialize_appointment(a) for a in missed_list],
        'stats': {
            'today_count': today_count,
            'queue_count': queue_count,
            'completed_count': completed_count,
            'upcoming_count': upcoming_count
        }
    })


# =========================
# DOCTOR CONSULTATION HISTORY
# =========================
@app.route('/doctor_consultation_history')
def doctor_consultation_history():

    if 'doctor_id' not in session:
        return redirect(url_for('doctor_login'))

    doctor_id = session['doctor_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get all completed consultations for this doctor (no date filter - shows all history)
    cursor.execute("""

        SELECT
            c.id AS consultation_id,
            c.diagnosis,
            c.remarks,
            a.date,
            a.time,
            p.full_name AS patient_name,
            p.contact_number AS patient_contact,
            p.email AS patient_email,
            t.symptoms,
            t.severity,
            t.duration,
            t.urgency,
            t.ai_score,
            t.priority_level

        FROM consultations c

        JOIN appointments a
        ON c.appointment_id = a.id

        JOIN patients p
        ON a.patient_id = p.id

        LEFT JOIN triage_results t
        ON a.triage_id = t.id

        WHERE a.doctor_id=%s
          AND a.status='Completed'
          AND c.id = (
              SELECT MAX(c2.id)
              FROM consultations c2
              WHERE c2.appointment_id = a.id
          )

        ORDER BY a.date DESC,
                 a.time DESC

    """, (doctor_id,))

    histories = cursor.fetchall()

    # Get prescriptions for each consultation
    for history in histories:

        cursor.execute("""

            SELECT
                medicine_name,
                dosage,
                frequency,
                duration

            FROM prescriptions

            WHERE consultation_id=%s

        """, (

            history['consultation_id'],

        ))

        history['prescriptions'] = cursor.fetchall()

    conn.close()

    return render_template(

        'doctor_consultation_history.html',

        histories=histories

    )

# =========================
# DOCTOR CONSULTATION
# =========================
@app.route('/doctor_consultation/<int:appointment_id>')
def doctor_consultation(appointment_id):

    if 'doctor_id' not in session:
        return redirect(url_for('doctor_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Appointment
    cursor.execute("""

        SELECT *
        FROM appointments
        WHERE id=%s

    """, (appointment_id,))

    appointment = cursor.fetchone()

    if not appointment:

        conn.close()

        return redirect(
            url_for('doctor_dashboard')
        )

    # Auto update status
    cursor.execute("""

        UPDATE appointments
        SET status='In-Consultation'
        WHERE id=%s
        AND status!='Completed'

    """, (appointment_id,))

    conn.commit()

    # Patient
    cursor.execute("""

        SELECT *
        FROM patients
        WHERE id=%s

    """, (

        appointment['patient_id'],

    ))

    patient = cursor.fetchone()

    # Latest triage
    cursor.execute("""

        SELECT *
        FROM triage_results
        WHERE id=%s
        

    """, (

         appointment['triage_id'],

    ))

    triage = cursor.fetchone()

    conn.close()

    return render_template(

        'consultation.html',

        appointment=appointment,
        patient=patient,
        triage=triage

    )


# =========================
# COMPLETE CONSULTATION
# =========================
@app.route(
    '/complete_consultation',
    methods=['POST']
)
def complete_consultation():

    appointment_id = request.form[
        'appointment_id'
    ]

    diagnosis = request.form[
        'diagnosis'
    ]

    remarks = request.form.get(
        'remarks',
        ''
    )

    if diagnosis.strip() == '':

        return "Diagnosis is required"

    conn = get_db_connection()
    cursor = conn.cursor()

    # =========================
    # SAVE CONSULTATION
    # =========================
    cursor.execute("""

        INSERT INTO consultations
        (
            appointment_id,
            diagnosis,
            remarks
        )

        VALUES (%s,%s,%s)

    """, (

        appointment_id,
        diagnosis,
        remarks

    ))

    consultation_id = cursor.lastrowid

    # =========================
    # SAVE PRESCRIPTIONS
    # =========================
    medicines = request.form.getlist(
        'medicine[]'
    )

    dosages = request.form.getlist(
        'dosage[]'
    )

    frequencies = request.form.getlist(
        'frequency[]'
    )

    durations = request.form.getlist(
        'duration[]'
    )

    for med, dose, freq, dur in zip(

        medicines,
        dosages,
        frequencies,
        durations

    ):

        # Ignore empty rows
        if (

            med.strip()
            and dose.strip()
            and freq.strip()
            and dur.strip()

        ):

            cursor.execute("""

                INSERT INTO prescriptions
                (
                    consultation_id,
                    medicine_name,
                    dosage,
                    frequency,
                    duration
                )

                VALUES (%s,%s,%s,%s,%s)

            """, (

                consultation_id,
                med,
                dose,
                freq,
                dur

            ))

    # =========================
    # UPDATE APPOINTMENT
    # =========================
    cursor.execute("""

        UPDATE appointments

        SET status='Completed'

        WHERE id=%s

    """, (

        appointment_id,

    ))

    conn.commit()

    conn.close()

    return render_template(
        'consultation_success.html'
    )

# =========================
# CONSULTATION HISTORY
# =========================
@app.route('/consultation_history')
def consultation_history():

    if 'patient_id' not in session:
        return redirect(url_for('patient_login'))

    patient_id = session['patient_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

    SELECT

        c.id AS consultation_id,
        c.diagnosis,
        c.remarks,

        a.date,
        a.time,

        d.name AS doctor_name,
        d.clinic_name,

        t.symptoms,
        t.severity,
        t.duration,
        t.urgency,
        t.ai_score

        FROM consultations c

        JOIN appointments a
        ON c.appointment_id = a.id

        JOIN doctors d
        ON a.doctor_id = d.id

        LEFT JOIN triage_results t
        ON a.triage_id = t.id

        WHERE a.patient_id=%s
          AND a.status='Completed'
          AND c.id = (
              SELECT MAX(c2.id)
              FROM consultations c2
              WHERE c2.appointment_id = a.id
          )

        ORDER BY a.date DESC,
                 a.time DESC

    """, (patient_id,))

    histories = cursor.fetchall()

    for history in histories:

        cursor.execute("""

            SELECT *

            FROM prescriptions

            WHERE consultation_id=%s

        """, (

            history['consultation_id'],

        ))

        history['prescriptions'] = cursor.fetchall()

    conn.close()

    return render_template(

        'consultation_history.html',

        histories=histories

    )

# =========================
# DOWNLOAD CONSULTATION PDF
# =========================
@app.route('/download_consultation_pdf/<int:consultation_id>')
def download_consultation_pdf(consultation_id):

    if 'patient_id' not in session:
        return redirect(url_for('patient_login'))

    patient_id = session['patient_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # =========================
    # FETCH CONSULTATION DATA
    # =========================
    cursor.execute("""

        SELECT
            c.id AS consultation_id,
            c.diagnosis,
            c.remarks,
            a.date,
            a.time,
            a.doctor_id,
            d.name AS doctor_name,
            d.specialist,
            d.clinic_name,
            d.clinic_id,
            p.full_name AS patient_full_name,
            p.age,
            p.gender,
            p.contact_number,
            p.email,
            p.address,
            t.symptoms,
            t.severity,
            t.duration AS symptom_duration,
            t.urgency,
            t.ai_score,
            t.priority_level

        FROM consultations c

        JOIN appointments a
        ON c.appointment_id = a.id

        JOIN doctors d
        ON a.doctor_id = d.id

        JOIN patients p
        ON a.patient_id = p.id

        LEFT JOIN triage_results t
        ON a.triage_id = t.id

        WHERE c.id=%s
          AND a.patient_id=%s
          AND a.status='Completed'

    """, (consultation_id, patient_id))

    consultation = cursor.fetchone()

    if not consultation:
        conn.close()
        return "Consultation not found or access denied.", 403

    # =========================
    # FETCH CLINIC INFO
    # =========================
    cursor.execute("""

        SELECT address, contact_number
        FROM clinics
        WHERE id=%s

    """, (consultation['clinic_id'],))

    clinic_info = cursor.fetchone()

    # =========================
    # FETCH PRESCRIPTIONS
    # =========================
    cursor.execute("""

        SELECT medicine_name, dosage, frequency, duration
        FROM prescriptions
        WHERE consultation_id=%s

    """, (consultation_id,))

    prescriptions = cursor.fetchall()

    conn.close()

    # =========================
    # HELPER: Safe value
    # =========================
    def safe(val):
        if val is None or str(val).strip() == '':
            return 'Not Available'
        return str(val)

    def safe_na(val):
        if val is None or str(val).strip() == '':
            return 'Not Available'
        return str(val)

    # =========================
    # BUILD PDF - IMPROVED LAYOUT
    # =========================
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm
    )

    styles = getSampleStyleSheet()

    # -- MedicaI colour palette --
    DARK_BLUE = colors.HexColor('#1a3a5c')
    MED_BLUE  = colors.HexColor('#2563eb')
    LIGHT_BG  = colors.HexColor('#f0f4f8')
    LGRAY     = colors.HexColor('#6b7280')
    DARK_TEXT  = colors.HexColor('#111827')
    BORDER_C   = colors.HexColor('#d1d5db')
    WHITE      = colors.white

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=22, leading=26, spaceAfter=1*mm,
        textColor=DARK_BLUE, alignment=TA_CENTER
    )

    tagline_style = ParagraphStyle(
        'Tagline', parent=styles['Normal'],
        fontSize=9, leading=12, spaceAfter=3*mm,
        textColor=LGRAY, alignment=TA_CENTER
    )

    report_title_style = ParagraphStyle(
        'ReportTitle', parent=styles['Heading1'],
        fontSize=16, leading=20, spaceAfter=2.5*mm,
        textColor=MED_BLUE, alignment=TA_CENTER
    )

    gen_info_style = ParagraphStyle(
        'GenInfo', parent=styles['Normal'],
        fontSize=8.5, leading=11, spaceAfter=1*mm,
        textColor=LGRAY, alignment=TA_CENTER
    )

    section_style = ParagraphStyle(
        'SectionHeader', parent=styles['Heading2'],
        fontSize=12.5, leading=15, spaceBefore=5*mm, spaceAfter=2.5*mm,
        textColor=DARK_BLUE, borderWidth=0, borderPadding=0
    )

    label_style = ParagraphStyle(
        'Label', parent=styles['Normal'],
        fontSize=8.5, leading=11, textColor=LGRAY,
        spaceBefore=1*mm, spaceAfter=0.5*mm
    )

    value_style = ParagraphStyle(
        'Value', parent=styles['Normal'],
        fontSize=10, leading=13.5, textColor=DARK_TEXT,
        spaceBefore=0, spaceAfter=1.5*mm
    )

    box_text_style = ParagraphStyle(
        'BoxText', parent=styles['Normal'],
        fontSize=10, leading=14, textColor=DARK_TEXT,
        spaceBefore=1*mm, spaceAfter=1*mm,
        leftIndent=3*mm, rightIndent=3*mm
    )

    na_style = ParagraphStyle(
        'NA', parent=styles['Normal'],
        fontSize=10, leading=13, textColor=colors.HexColor('#9ca3af'),
        spaceBefore=0, spaceAfter=2*mm
    )

    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontSize=8, leading=10, textColor=LGRAY,
        alignment=TA_CENTER, spaceBefore=8*mm
    )

    story = []

    # =========================
    # HEADER
    # =========================
    story.append(Paragraph("MEDiAI", title_style))
    story.append(Paragraph(
        "AI-Powered Healthcare Appointment & Queue Management System",
        tagline_style
    ))
    story.append(Paragraph("Consultation Summary", report_title_style))

    # Consultation & appointment reference
    story.append(Paragraph(
        f"Consultation ID: {consultation_id}",
        gen_info_style
    ))

    gen_datetime = datetime.now().strftime("%d %B %Y at %I:%M %p")
    story.append(Paragraph(
        f"Report generated: {gen_datetime}",
        gen_info_style
    ))

    story.append(HRFlowable(
        width="100%", thickness=1.2, color=MED_BLUE,
        spaceBefore=3*mm, spaceAfter=5*mm
    ))

    # =========================
    # PATIENT INFORMATION
    # =========================
    story.append(Paragraph("PATIENT INFORMATION", section_style))

    patient_data = [
        [Paragraph("<b>Full Name</b>", label_style),
         Paragraph(safe(consultation['patient_full_name']), value_style)],
        [Paragraph("<b>Age</b>", label_style),
         Paragraph(safe(consultation['age']), value_style)],
        [Paragraph("<b>Gender</b>", label_style),
         Paragraph(safe(consultation['gender']), value_style)],
        [Paragraph("<b>Contact Number</b>", label_style),
         Paragraph(safe(consultation['contact_number']), value_style)],
        [Paragraph("<b>Email</b>", label_style),
         Paragraph(safe(consultation['email']), value_style)],
        [Paragraph("<b>Address</b>", label_style),
         Paragraph(safe(consultation['address']), value_style)],
    ]

    patient_table = Table(patient_data, colWidths=[42*mm, 122*mm])
    patient_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 0.8*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0.8*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('LINEBELOW', (0,0), (-1,0), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,1), (-1,1), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,2), (-1,2), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,3), (-1,3), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,4), (-1,4), 0.5, LIGHT_BG),
    ]))
    story.append(patient_table)

    # =========================
    # CLINIC & DOCTOR INFORMATION
    # =========================
    story.append(Paragraph("CLINIC & DOCTOR INFORMATION", section_style))

    clinic_addr = safe_na(clinic_info['address']) if clinic_info else 'Not Available'
    clinic_contact = safe_na(clinic_info['contact_number']) if clinic_info else 'Not Available'

    clinic_doctor_data = [
        [Paragraph("<b>Clinic Name</b>", label_style),
         Paragraph(safe(consultation['clinic_name']), value_style)],
        [Paragraph("<b>Clinic Address</b>", label_style),
         Paragraph(clinic_addr, value_style)],
        [Paragraph("<b>Clinic Contact</b>", label_style),
         Paragraph(clinic_contact, value_style)],
        [Paragraph("<b>Doctor Name</b>", label_style),
         Paragraph(safe(consultation['doctor_name']), value_style)],
        [Paragraph("<b>Specialty</b>", label_style),
         Paragraph(safe(consultation['specialist']), value_style)],
    ]

    clinic_table = Table(clinic_doctor_data, colWidths=[42*mm, 122*mm])
    clinic_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 0.8*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0.8*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('LINEBELOW', (0,0), (-1,0), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,1), (-1,1), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,2), (-1,2), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,3), (-1,3), 0.5, LIGHT_BG),
    ]))
    story.append(clinic_table)

    # =========================
    # APPOINTMENT DETAILS
    # =========================
    story.append(Paragraph("APPOINTMENT DETAILS", section_style))

    apt_date = consultation['date']
    if hasattr(apt_date, 'strftime'):
        apt_date = apt_date.strftime('%d %B %Y')
    apt_time = consultation['time']
    if hasattr(apt_time, 'strftime'):
        apt_time = apt_time.strftime('%I:%M %p')

    appointment_data = [
        [Paragraph("<b>Appointment Date</b>", label_style),
         Paragraph(str(apt_date), value_style)],
        [Paragraph("<b>Appointment Time</b>", label_style),
         Paragraph(str(apt_time), value_style)],
    ]

    apt_table = Table(appointment_data, colWidths=[42*mm, 122*mm])
    apt_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 0.8*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0.8*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('LINEBELOW', (0,0), (-1,0), 0.5, LIGHT_BG),
    ]))
    story.append(apt_table)

    # =========================
    # MEDICAL DETAILS
    # =========================
    story.append(Paragraph("MEDICAL DETAILS", section_style))

    # Symptoms
    story.append(Paragraph("<b>Symptoms Reported</b>", label_style))
    symptoms_val = safe_na(consultation['symptoms'])
    story.append(Paragraph(symptoms_val, box_text_style))
    story.append(Spacer(1, 2*mm))

    # Diagnosis in shaded box
    story.append(Paragraph("<b>Diagnosis</b>", label_style))
    diag_val = safe(consultation['diagnosis'])
    diag_box_data = [[Paragraph(diag_val, box_text_style)]]
    diag_table = Table(diag_box_data, colWidths=[164*mm])
    diag_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#eaf2ff')),
        ('BOX', (0,0), (-1,-1), 0.75, colors.HexColor('#cfe0ff')),
        ('TOPPADDING', (0,0), (-1,-1), 2*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('RIGHTPADDING',(0,0), (-1,-1), 2*mm),
    ]))
    story.append(diag_table)
    story.append(Spacer(1, 2*mm))

    # Doctor's Remarks in shaded box
    story.append(Paragraph("<b>Doctor's Remarks</b>", label_style))
    remarks_val = safe_na(consultation['remarks'])
    remarks_box_data = [[Paragraph(remarks_val, box_text_style)]]
    remarks_table = Table(remarks_box_data, colWidths=[164*mm])
    remarks_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 0.75, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0,0), (-1,-1), 2*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('RIGHTPADDING',(0,0), (-1,-1), 2*mm),
    ]))
    story.append(remarks_table)

    # =========================
    # PRESCRIPTIONS TABLE
    # =========================
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("PRESCRIPTIONS", section_style))

    if prescriptions and len(prescriptions) > 0:
        presc_header_style = ParagraphStyle(
            'PrescHeader', parent=label_style,
            textColor=WHITE, fontSize=9, leading=12
        )
        presc_val_style = ParagraphStyle(
            'PrescVal', parent=value_style,
            fontSize=9.5, leading=12.5
        )

        presc_data = [
            [Paragraph("<b>Medicine</b>", presc_header_style),
             Paragraph("<b>Dosage</b>", presc_header_style),
             Paragraph("<b>Frequency</b>", presc_header_style),
             Paragraph("<b>Duration</b>", presc_header_style)]
        ]
        for med in prescriptions:
            presc_data.append([
                Paragraph(safe(med['medicine_name']), presc_val_style),
                Paragraph(safe(med['dosage']), presc_val_style),
                Paragraph(safe(med['frequency']), presc_val_style),
                Paragraph(safe(med['duration']), presc_val_style),
            ])

        presc_table = Table(presc_data, colWidths=[45*mm, 40*mm, 40*mm, 39*mm])
        presc_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), DARK_BLUE),
            ('TEXTCOLOR', (0,0), (-1,0), WHITE),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_C),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 2*mm),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
            ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
            ('RIGHTPADDING',(0,0), (-1,-1), 2*mm),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, colors.HexColor('#f9fafb')]),
        ]))
        story.append(presc_table)
    else:
        story.append(Paragraph("Not Available", na_style))

    # =========================
    # AI TRIAGE INFORMATION
    # =========================
    story.append(Paragraph("AI TRIAGE INFORMATION", section_style))

    triage_data = [
        [Paragraph("<b>Priority Level</b>", label_style),
         Paragraph(safe_na(consultation.get('priority_level', 'Not Available')), value_style)],
        [Paragraph("<b>Urgency</b>", label_style),
         Paragraph(safe_na(consultation['urgency']), value_style)],
        [Paragraph("<b>Severity</b>", label_style),
         Paragraph(safe_na(consultation['severity']), value_style)],
        [Paragraph("<b>Symptom Duration</b>", label_style),
         Paragraph(safe_na(consultation['symptom_duration']), value_style)],
        [Paragraph("<b>AI Score</b>", label_style),
         Paragraph(safe_na(consultation['ai_score']), value_style)],
    ]

    triage_table = Table(triage_data, colWidths=[42*mm, 122*mm])
    triage_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 0.8*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0.8*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('LINEBELOW', (0,0), (-1,0), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,1), (-1,1), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,2), (-1,2), 0.5, LIGHT_BG),
        ('LINEBELOW', (0,3), (-1,3), 0.5, LIGHT_BG),
    ]))
    story.append(triage_table)

    # =========================
    # FOOTER
    # =========================
    story.append(HRFlowable(
        width="100%", thickness=0.5, color=BORDER_C,
        spaceBefore=6*mm, spaceAfter=2*mm
    ))
    story.append(Paragraph(
        "This consultation summary is generated by MediAI for future medical reference.",
        footer_style
    ))

    # =========================
    # BUILD & RETURN
    # =========================
    doc.build(story)
    pdf_data = buffer.getvalue()
    buffer.close()

    filename = f"Consultation_Summary_{consultation_id}.pdf"

    return send_file(
        BytesIO(pdf_data),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

# =========================
# CLINIC LOGIN
# =========================
@app.route('/clinic_login', methods=['GET', 'POST'])
def clinic_login():

    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""

            SELECT *

            FROM clinic_admin

            WHERE username=%s
            AND password=%s

        """, (

            username,
            password

        ))

        admin = cursor.fetchone()

        conn.close()

        if admin:

            session['clinic_admin_id'] = admin['id']

            return redirect(
                url_for('clinic_dashboard')
            )

        flash("Invalid username or password")

    return render_template(
        'clinic_login.html'
    )

# =========================
# CLINIC DASHBOARD
# =========================
@app.route('/clinic_dashboard')
def clinic_dashboard():

    if 'clinic_admin_id' not in session:

        return redirect(
            url_for('clinic_login')
        )

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # =========================
    # SUMMARY CARDS
    # =========================

    cursor.execute("""

        SELECT COUNT(*) AS total_clinics

        FROM clinics

    """)

    total_clinics = cursor.fetchone()['total_clinics']

    cursor.execute("""

        SELECT COUNT(*) AS total_doctors

        FROM doctors

        WHERE status='Active'

    """)

    total_doctors = cursor.fetchone()['total_doctors']

    cursor.execute("""

        SELECT COUNT(*) AS total_appointments

        FROM appointments

        WHERE date = CURDATE()

    """)

    total_appointments = cursor.fetchone()['total_appointments']

    cursor.execute("""

        SELECT COUNT(*) AS waiting_patients

        FROM appointments

        WHERE status IN
        (
            'Booked',
            'Waiting',
            'In-Consultation'
        )

    """)

    waiting_patients = cursor.fetchone()['waiting_patients']

 # =========================
    # CLINIC OPERATIONS
    # =========================

    cursor.execute("""

        SELECT *

        FROM clinics

        ORDER BY clinic_name

    """)

    clinics = cursor.fetchall()

    # Doctors, Appointments & Queue
    for clinic in clinics:

            # Doctors
        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM doctors

            WHERE clinic_id=%s
            AND status='Active'

        """, (

            clinic['id'],

        ))

        clinic['doctor_count'] = cursor.fetchone()['total']

        # Today's appointments
        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic=%s
            AND date=CURDATE()

        """, (

            clinic['clinic_name'],

        ))

        clinic['appointment_count'] = cursor.fetchone()['total']

        # Waiting patients
        cursor.execute("""

            SELECT COUNT(*) AS total

            FROM appointments

            WHERE clinic=%s
            AND status IN
            (
                'Booked',
                'Waiting',
                'In-Consultation'
            )

        """, (

            clinic['clinic_name'],

        ))

        clinic['queue_count'] = cursor.fetchone()['total']


    # =========================
    # CURRENT CLINIC STATUS
    # =========================

    current_time = timedelta(

        hours=datetime.now().hour,
        minutes=datetime.now().minute,
        seconds=datetime.now().second

    )

    currently_closed = 0

    for clinic in clinics:

        # Manual Clinic Status
        if clinic['status'] == "Temporary Closed":

            clinic['display_status'] = "Temporary Closed"

        elif clinic['status'] == "Permanently Closed":

            clinic['display_status'] = "Permanently Closed"

        # Operating Hours
        elif (

            clinic['opening_time']
            and clinic['closing_time']
            and clinic['opening_time'] <= current_time <= clinic['closing_time']

        ):

            clinic['display_status'] = "Open"

        else:

            clinic['display_status'] = "Closed"

            currently_closed += 1


    # =========================
    # CLINIC STATUS SUMMARY
    # =========================

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM clinics

        WHERE status='Open'

    """)

    open_clinics = cursor.fetchone()['total']

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM clinics

        WHERE status='Temporary Closed'

    """)

    temporary_closed = cursor.fetchone()['total']

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM clinics

        WHERE status='Permanently Closed'

    """)

    permanently_closed = cursor.fetchone()['total']

    # =========================
    # DOCTOR AVAILABILITY
    # =========================

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM doctors

        WHERE availability='Available'

    """)

    available_doctors = cursor.fetchone()['total']

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM doctors

        WHERE availability='On Leave'

    """)

    on_leave_doctors = cursor.fetchone()['total']

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM doctors

        WHERE availability='Unavailable'

    """)

    unavailable_doctors = cursor.fetchone()['total']

    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM doctors

        WHERE availability='Retired'

    """)

    retired_doctors = cursor.fetchone()['total']

    # =========================
    # QUEUE ALERTS
    # =========================

    queue_alerts = []

    for clinic in clinics:

        if clinic['queue_count'] > 0:

            queue_alerts.append(clinic)

    # =========================
    # APPOINTMENT LEADERBOARD
    # =========================

    leaderboard = sorted(

        clinics,

        key=lambda x: x['appointment_count'],

        reverse=True

    )[:3]

    conn.close()

    return render_template(

        'clinic_dashboard.html',

        total_clinics=total_clinics,
        total_doctors=total_doctors,
        total_appointments=total_appointments,
        waiting_patients=waiting_patients,

        clinics=clinics,

        open_clinics=open_clinics,
        temporary_closed=temporary_closed,
        permanently_closed=permanently_closed,
        currently_closed=currently_closed,

        available_doctors=available_doctors,
        on_leave_doctors=on_leave_doctors,
        unavailable_doctors=unavailable_doctors,
        retired_doctors=retired_doctors,

        queue_alerts=queue_alerts,

        leaderboard=leaderboard,

        last_updated=datetime.now().strftime(
            "%d %b %Y %I:%M %p"
        )

    )

# =========================
# CLINIC DETAILS
# =========================
@app.route('/clinic_details/<int:id>')
def clinic_details(id):

    if 'clinic_admin_id' not in session:

        return redirect(
            url_for('clinic_login')
        )

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # =========================
    # CLINIC INFO
    # =========================
    cursor.execute("""

        SELECT *

        FROM clinics

        WHERE id=%s

    """, (

        id,

    ))

    clinic = cursor.fetchone()

    if not clinic:

        conn.close()

        return redirect(
            url_for('clinic_dashboard')
        )

        # =========================
        # DOCTOR COUNT
        # =========================
        
    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM doctors

        WHERE clinic_id=%s
        AND status='Active'

    """, (

        clinic['id'],

    ))

    doctor_count = cursor.fetchone()['total']

    # =========================
    # TODAY APPOINTMENTS
    # =========================
    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM appointments

        WHERE clinic=%s
        AND date=CURDATE()

    """, (

        clinic['clinic_name'],

    ))

    appointment_count = cursor.fetchone()['total']

    # =========================
    # CURRENT QUEUE
    # =========================
    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM appointments

        WHERE clinic=%s
        AND status IN
        (
            'Booked',
            'Waiting',
            'In-Consultation'
        )

    """, (

        clinic['clinic_name'],

    ))

    queue_count = cursor.fetchone()['total']


    # =========================
    # CURRENT CLINIC STATUS
    # =========================

    current_time = timedelta(

        hours=datetime.now().hour,
        minutes=datetime.now().minute,
        seconds=datetime.now().second

    )

    # Manual Clinic Status
    if clinic['status'] == "Temporary Closed":

        clinic['display_status'] = "Temporary Closed"

    elif clinic['status'] == "Permanently Closed":

        clinic['display_status'] = "Permanently Closed"

    # Operating Hours
    elif (

        clinic['opening_time']
        and clinic['closing_time']
        and clinic['opening_time'] <= current_time <= clinic['closing_time']

    ):

        clinic['display_status'] = "Open"

    else:

        clinic['display_status'] = "Closed"




    conn.close()

    return render_template(

        'clinic_details.html',

        clinic=clinic,

        doctor_count=doctor_count,

        appointment_count=appointment_count,

        queue_count=queue_count

    )

# =========================
# CLINIC INFORMATION
# =========================
@app.route('/clinic_information')
def clinic_information():

    if 'clinic_admin_id' not in session:

        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT *

        FROM clinics

        ORDER BY clinic_name

    """)

    clinics = cursor.fetchall()

    conn.close()

    # =========================
    # CURRENT CLINIC STATUS
    # =========================

    current_time = timedelta(

        hours=datetime.now().hour,
        minutes=datetime.now().minute,
        seconds=datetime.now().second

    )

    for clinic in clinics:

        # Manual Status
        if clinic['status'] == "Temporary Closed":

            clinic['display_status'] = "Temporary Closed"

        elif clinic['status'] == "Permanently Closed":

            clinic['display_status'] = "Permanently Closed"

        # Operating Hours
        elif (

            clinic['opening_time']
            and clinic['closing_time']
            and clinic['opening_time'] <= current_time <= clinic['closing_time']

        ):

            clinic['display_status'] = "Open"

        else:

            clinic['display_status'] = "Closed"

    return render_template(

        'clinic_information.html',

        clinics=clinics

    )

# =========================
# EDIT CLINIC INFORMATION
# =========================
@app.route('/edit_clinic/<int:id>', methods=['GET', 'POST'])
def edit_clinic(id):

    if 'clinic_admin_id' not in session:

        return redirect(
            url_for('clinic_login')
        )

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        clinic_name = request.form["clinic_name"]
        clinic_type = request.form["clinic_type"]
        address = request.form["address"]
        location = request.form["location"]
        contact_number = request.form["contact_number"]
        map_link = request.form["map_link"]
        opening_time = request.form["opening_time"]
        closing_time = request.form["closing_time"]
        status = request.form["status"]

        cursor.execute("""

            UPDATE clinics

            SET

                clinic_name=%s,
                clinic_type=%s,
                address=%s,
                location=%s,
                contact_number=%s,
                map_link=%s,
                opening_time=%s,
                closing_time=%s,
                status=%s

            WHERE id=%s

        """,(

            clinic_name,
            clinic_type,
            address,
            location,
            contact_number,
            map_link,
            opening_time,
            closing_time,
            status,
            id

        ))

        conn.commit()

        conn.close()

        flash("Clinic information updated successfully.")

        return redirect(
            url_for("clinic_information")
        )

    cursor.execute("""

        SELECT *

        FROM clinics

        WHERE id=%s

    """,(id,))

    clinic = cursor.fetchone()

    if clinic['opening_time']:
        total_seconds = int(clinic['opening_time'].total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        clinic['opening_time_str'] = f"{hours:02d}:{minutes:02d}"
    else:
        clinic['opening_time_str'] = ""

    if clinic['closing_time']:
        total_seconds = int(clinic['closing_time'].total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        clinic['closing_time_str'] = f"{hours:02d}:{minutes:02d}"
    else:
        clinic['closing_time_str'] = ""


    conn.close()

    return render_template(

        "edit_clinic.html",

        clinic=clinic

    )

# =========================
# ADD NEW CLINIC
# =========================
@app.route('/add_clinic', methods=['GET', 'POST'])
def add_clinic():

    if request.method == 'POST':

        clinic_name = request.form['clinic_name']
        clinic_type = request.form['clinic_type']
        address = request.form['address']
        location = request.form['location']
        distance = request.form['distance']

        # Automatically generate Google Maps embed link
        map_link = (
            "https://maps.google.com/maps?q="
            + urllib.parse.quote(address)
            + "&t=&z=15&ie=UTF8&iwloc=&output=embed"
        )

        contact_number = request.form['contact_number']
        opening_time = request.form['opening_time']
        closing_time = request.form['closing_time']
        status = request.form['status']

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check duplicate clinic
        cursor.execute("""

            SELECT id

            FROM clinics

            WHERE clinic_name=%s

        """, (

            clinic_name,

        ))

        if cursor.fetchone():

            conn.close()

            return "Clinic already exists."

        cursor.execute("""

            INSERT INTO clinics
            (
                clinic_name,
                clinic_type,
                address,
                location,
                distance,
                map_link,
                contact_number,
                opening_time,
                closing_time,
                status
            )

            VALUES
            (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )

        """, (

            clinic_name,
            clinic_type,
            address,
            location,
            distance,
            map_link,
            contact_number,
            opening_time,
            closing_time,
            status

        ))

        conn.commit()
        conn.close()

        return redirect(url_for('clinic_information'))

    return render_template('add_clinic.html')


# =========================
# OPERATING HOURS
# =========================
@app.route('/operating_hours')
def operating_hours():

    if 'clinic_admin_id' not in session:

        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT *

        FROM clinics

        ORDER BY clinic_name

    """)

    clinics = cursor.fetchall()

    conn.close()

    for clinic in clinics:

        if clinic['opening_time']:

            total_seconds = int(clinic['opening_time'].total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            clinic['opening_time_str'] = f"{hours:02d}:{minutes:02d}"

        else:

            clinic['opening_time_str'] = ""

        if clinic['closing_time']:

            total_seconds = int(clinic['closing_time'].total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            clinic['closing_time_str'] = f"{hours:02d}:{minutes:02d}"

        else:

            clinic['closing_time_str'] = ""

    return render_template(

        "operating_hours.html",

        clinics=clinics

    )

# =========================
# EDIT OPERATING HOURS
# =========================
@app.route('/edit_operating_hours/<int:id>', methods=['GET', 'POST'])
def edit_operating_hours(id):

    if 'clinic_admin_id' not in session:

        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        opening_time = request.form["opening_time"]
        closing_time = request.form["closing_time"]

        cursor.execute("""

            UPDATE clinics

            SET

                opening_time=%s,
                closing_time=%s

            WHERE id=%s

        """,(

            opening_time,
            closing_time,
            id

        ))

        conn.commit()

        conn.close()

        flash("Operating hours updated successfully.")

        return redirect(url_for("operating_hours"))

    cursor.execute("""

        SELECT *

        FROM clinics

        WHERE id=%s

    """,(id,))

    clinic = cursor.fetchone()

    if clinic['opening_time']:

        total_seconds = int(clinic['opening_time'].total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        clinic['opening_time_str'] = f"{hours:02d}:{minutes:02d}"

    else:

        clinic['opening_time_str'] = ""

    if clinic['closing_time']:

        total_seconds = int(clinic['closing_time'].total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        clinic['closing_time_str'] = f"{hours:02d}:{minutes:02d}"

    else:

        clinic['closing_time_str'] = ""

    conn.close()

    return render_template(

        "edit_operating_hours.html",

        clinic=clinic

    )

# =========================
# CLINIC STATUS MANAGEMENT
# =========================
@app.route('/clinic_status')
def clinic_status():

    if 'clinic_admin_id' not in session:
        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT *

        FROM clinics

        ORDER BY clinic_name

    """)

    clinics = cursor.fetchall()

    conn.close()

    return render_template(

        "clinic_status.html",

        clinics=clinics

    )



# =========================
# EDIT CLINIC STATUS
# =========================
@app.route('/edit_clinic_status/<int:id>', methods=['GET','POST'])
def edit_clinic_status(id):

    if 'clinic_admin_id' not in session:
        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        status = request.form["status"]

        cursor.execute("""

            UPDATE clinics

            SET status=%s

            WHERE id=%s

        """,(

            status,
            id

        ))

        conn.commit()

        conn.close()

        flash("Clinic status updated successfully.")

        return redirect(url_for("clinic_status"))

    cursor.execute("""

        SELECT *

        FROM clinics

        WHERE id=%s

    """,(id,))

    clinic = cursor.fetchone()

    conn.close()

    return render_template(

        "edit_clinic_status.html",

        clinic=clinic

    )

# =========================
# DOCTOR MANAGEMENT
# =========================
@app.route('/doctor_management')
def doctor_management():

    if 'clinic_admin_id' not in session:

        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT *

        FROM doctors

        ORDER BY clinic_name, name

    """)

    doctors = cursor.fetchall()

    conn.close()

    return render_template(

        "doctor_management.html",

        doctors=doctors

    )

# =========================
# DELETE DOCTOR
# =========================
@app.route('/delete_doctor/<int:id>')
def delete_doctor(id):

    if 'clinic_admin_id' not in session:
        return redirect(url_for('clinic_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get doctor name
    cursor.execute("""

        SELECT name

        FROM doctors

        WHERE id=%s

    """, (id,))

    doctor = cursor.fetchone()

    if not doctor:

        conn.close()

        flash("Doctor not found.")

        return redirect(url_for("doctor_management"))

# Check appointment history
    cursor.execute("""

        SELECT COUNT(*) AS total

        FROM appointments

        WHERE doctor_id=%s

    """, (

        id,

    ))

    appointment_count = cursor.fetchone()['total']

    if appointment_count > 0:

        conn.close()

        flash(
            "This doctor cannot be deleted because appointment records exist. "
            "Please change the doctor's status to Inactive or availability to Retired instead."
        )

        return redirect(url_for("doctor_management"))

    # Delete doctor
    cursor.execute("""

        DELETE FROM doctors

        WHERE id=%s

    """, (id,))

    conn.commit()

    conn.close()

    flash("Doctor deleted successfully.")

    return redirect(url_for("doctor_management"))


# =========================
# ADD DOCTOR
# =========================
@app.route('/add_doctor', methods=['GET', 'POST'])
def add_doctor():

    if 'clinic_admin_id' not in session:
        return redirect(url_for('clinic_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Load clinics for dropdown
    cursor.execute("""
        SELECT id, clinic_name
        FROM clinics
        WHERE status != 'Permanently Closed'
        ORDER BY clinic_name
    """)

    clinics = cursor.fetchall()

    if request.method == "POST":

        name = request.form["name"]
        username = request.form["username"]
        password = request.form["password"]
        email = request.form["email"]
        clinic_code = request.form["clinic_code"]
        specialist = request.form["specialist"]

        clinic_id = request.form["clinic_id"]
        

        status = request.form["status"]
        availability = request.form["availability"]
        consultation_duration = request.form["consultation_duration"]

        # Get selected clinic
        cursor.execute("""
            SELECT clinic_name
            FROM clinics
            WHERE id=%s
        """,(clinic_id,))

        clinic = cursor.fetchone()

        if not clinic:

            flash("Selected clinic does not exist.")

            conn.close()

            return render_template(
                "add_doctor.html",
                clinics=clinics
            )

        clinic_name = clinic["clinic_name"]

        # Duplicate Username
        cursor.execute("""
            SELECT id
            FROM doctors
            WHERE username=%s
        """,(username,))

        if cursor.fetchone():

            flash("Username already exists.")

            conn.close()

            return render_template(
                "add_doctor.html",
                clinics=clinics
            )

        # Duplicate Email
        cursor.execute("""
            SELECT id
            FROM doctors
            WHERE email=%s
        """,(email,))

        if cursor.fetchone():

            flash("Email already exists.")

            conn.close()

            return render_template(
                "add_doctor.html",
                clinics=clinics
            )

        # Duplicate Clinic Code
        cursor.execute("""
            SELECT id
            FROM doctors
            WHERE clinic_code=%s
        """,(clinic_code,))

        if cursor.fetchone():

            flash("Clinic code already exists.")

            conn.close()

            return render_template(
                "add_doctor.html",
                clinics=clinics
            )

        # Insert Doctor
        cursor.execute("""
            INSERT INTO doctors
            (
                name,
                email,
                password,
                clinic_code,
                username,
                specialist,
                clinic_name,
                clinic_id,
                status,
                availability,
                consultation_duration
            )

            VALUES
            (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
        """,(

            name,
            email,
            password,
            clinic_code,
            username,
            specialist,
            clinic_name,
            clinic_id,
            status,
            availability,
            consultation_duration

        ))

        conn.commit()

        conn.close()

        flash("Doctor added successfully.")

        return redirect(url_for("doctor_management"))

    conn.close()

    return render_template(
        "add_doctor.html",
        clinics=clinics
    )


# =========================
# EDIT DOCTOR
# =========================
@app.route('/edit_doctor/<int:id>', methods=['GET', 'POST'])
def edit_doctor(id):

    if 'clinic_admin_id' not in session:

        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    # Load clinics
    cursor.execute("""

        SELECT id, clinic_name

        FROM clinics

        WHERE status != 'Permanently Closed'

        ORDER BY clinic_name

    """)

    clinics = cursor.fetchall()


    if request.method == "POST":

        name = request.form["name"]
        username = request.form["username"]
        password = request.form["password"]
        email = request.form["email"]
        clinic_code = request.form["clinic_code"]
        specialist = request.form["specialist"]

        clinic_id = request.form["clinic_id"]

        status = request.form["status"]
        availability = request.form["availability"]
        consultation_duration = request.form["consultation_duration"]

        # Get clinic name
        cursor.execute("""

            SELECT clinic_name

            FROM clinics

            WHERE id=%s

        """,(clinic_id,))

        clinic = cursor.fetchone()


        if not clinic:

            flash("Selected clinic does not exist.")

            conn.close()

            return render_template(

                "edit_doctor.html",

                doctor=request.form,

                clinics=clinics

            )

        clinic_name = clinic["clinic_name"]


        # Duplicate username
        cursor.execute("""

            SELECT id

            FROM doctors

            WHERE username=%s
            AND id!=%s

        """,(username,id))

        if cursor.fetchone():

            flash("Username already exists.")

            conn.close()

            return render_template(
                "edit_doctor.html",
                doctor=request.form,
                clinics=clinics
            )

        # Duplicate email
        cursor.execute("""

            SELECT id

            FROM doctors

            WHERE email=%s
            AND id!=%s

        """,(email,id))

        if cursor.fetchone():

            flash("Email already exists.")

            conn.close()

            return render_template(
                "edit_doctor.html",
                doctor=request.form,
                clinics=clinics
            )

        # Duplicate clinic code
        cursor.execute("""

            SELECT id

            FROM doctors

            WHERE clinic_code=%s
            AND id!=%s

        """,(clinic_code,id))

        if cursor.fetchone():

            flash("Clinic code already exists.")

            conn.close()

            return render_template(
                "edit_doctor.html",
                doctor=request.form,
                clinics=clinics
            )

        # Update doctor
        cursor.execute("""

            UPDATE doctors

            SET

                name=%s,
                username=%s,
                password=%s,
                email=%s,
                clinic_code=%s,
                specialist=%s,
                clinic_id=%s,
                clinic_name=%s,
                status=%s,
                availability=%s,
                consultation_duration=%s

            WHERE id=%s

        """,(

            name,
            username,
            password,
            email,
            clinic_code,
            specialist,
            clinic_id,
            clinic_name,
            status,
            availability,
            consultation_duration,
            id

        ))

        conn.commit()

        conn.close()

        flash("Doctor updated successfully.")

        return redirect(url_for("doctor_management"))

    # Load selected doctor
    cursor.execute("""

        SELECT *

        FROM doctors

        WHERE id=%s

    """,(id,))

    doctor = cursor.fetchone()

    conn.close()

    return render_template(

        "edit_doctor.html",

        doctor=doctor,

        clinics=clinics

    )

# =========================
# DOCTOR AVAILABILITY
# =========================
@app.route('/doctor_availability')
def doctor_availability():

    if 'clinic_admin_id' not in session:

        return redirect(url_for('clinic_login'))

    conn = get_db_connection()

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT

            id,
            name,
            specialist,
            clinic_name,
            status,
            availability

        FROM doctors

        ORDER BY clinic_name, name

    """)

    doctors = cursor.fetchall()

    conn.close()

    return render_template(

        "doctor_availability.html",

        doctors=doctors

    )


# =========================
# UPDATE DOCTOR AVAILABILITY
# =========================
@app.route('/update_doctor_availability/<int:id>', methods=['GET', 'POST'])
def update_doctor_availability(id):

    if 'clinic_admin_id' not in session:
        return redirect(url_for('clinic_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # =========================
    # UPDATE
    # =========================
    if request.method == "POST":

        
        availability = request.form["availability"]

        # Automatically update doctor status
        if availability == "Retired":
            status = "Inactive"
        else:
            status = "Active"

        cursor.execute("""

            UPDATE doctors

            SET

                availability=%s,
                status=%s

            WHERE id=%s

        """, (

            availability,
            status,
            id

        ))


        conn.commit()

        conn.close()

        flash("Doctor availability updated successfully.")

        return redirect(url_for("doctor_availability"))

    # =========================
    # LOAD DOCTOR
    # =========================
    cursor.execute("""

        SELECT

            id,
            name,
            clinic_name,
            specialist,
            status,
            availability

        FROM doctors

        WHERE id=%s

    """, (

        id,

    ))

    doctor = cursor.fetchone()

    if not doctor:

        conn.close()

        flash("Doctor not found.")

        return redirect(url_for("doctor_availability"))

    conn.close()

    return render_template(

        "update_doctor_availability.html",

        doctor=doctor

    )

# =========================
# APPOINTMENT MONITORING
# =========================
@app.route('/appointment_monitoring')
def appointment_monitoring():

    if 'clinic_admin_id' not in session:
        return redirect(url_for('clinic_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get filter parameters
    filter_clinic = request.args.get('clinic', '')
    filter_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    filter_status = request.args.get('status', '')
    filter_doctor = request.args.get('doctor', '')

    # Get all clinics for filter dropdown
    cursor.execute("SELECT id, clinic_name FROM clinics ORDER BY clinic_name")
    clinics = cursor.fetchall()

    # Get all doctors for filter dropdown
    cursor.execute("SELECT id, name, clinic_name FROM doctors ORDER BY name")
    doctors = cursor.fetchall()

    # Build query
    query = """
        SELECT
            a.*,
            p.full_name AS patient_name,
            p.contact_number AS patient_contact,
            p.email AS patient_email,
            t.symptoms,
            t.severity,
            t.duration AS symptom_duration,
            t.urgency AS triage_urgency,
            t.ai_score,
            t.priority_level
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        LEFT JOIN triage_results t ON a.triage_id = t.id
        WHERE 1=1
    """
    params = []

    if filter_clinic:
        query += " AND a.clinic_id = %s"
        params.append(filter_clinic)

    if filter_date:
        query += " AND a.date = %s"
        params.append(filter_date)

    if filter_status:
        query += " AND a.status = %s"
        params.append(filter_status)

    if filter_doctor:
        query += " AND a.doctor_id = %s"
        params.append(filter_doctor)

    query += " ORDER BY a.date DESC, a.time ASC"

    cursor.execute(query, tuple(params))
    appointments = cursor.fetchall()
    
    # Apply time-based status override
    for apt in appointments:
        if apt['status'] not in ['Completed', 'Cancelled', 'Missed', 'In-Consultation']:
            apt['status'] = get_effective_status(apt)

    # Summary stats
    total_appointments = len(appointments)
    completed_count = sum(1 for a in appointments if a['status'] == 'Completed')
    waiting_count = sum(1 for a in appointments if a['status'] in ('Booked', 'Waiting'))
    missed_cancelled = sum(1 for a in appointments if a['status'] in ('Missed', 'Cancelled'))

    conn.close()

    return render_template(
        'appointment_monitoring.html',
        clinics=clinics,
        doctors=doctors,
        appointments=appointments,
        filter_clinic=filter_clinic,
        filter_date=filter_date,
        filter_status=filter_status,
        filter_doctor=filter_doctor,
        total_appointments=total_appointments,
        completed_count=completed_count,
        waiting_count=waiting_count,
        missed_cancelled=missed_cancelled,
        today=datetime.now().strftime('%Y-%m-%d'),
        last_updated=datetime.now().strftime("%d %b %Y %I:%M %p")
    )


# =========================
# QUEUE MONITORING (Clinic Side)
# =========================
@app.route('/queue_monitoring')
def queue_monitoring():

    if 'clinic_admin_id' not in session:
        return redirect(url_for('clinic_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # =========================
    # GET ALL CLINICS
    # =========================
    cursor.execute("""
        SELECT *
        FROM clinics
        ORDER BY clinic_name
    """)
    clinics = cursor.fetchall()

    # =========================
    # CURRENT TIME
    # =========================
    current_time = timedelta(
        hours=datetime.now().hour,
        minutes=datetime.now().minute,
        seconds=datetime.now().second
    )

    # =========================
    # GLOBAL STATS
    # =========================
    total_in_queue = 0
    total_waiting = 0
    total_in_consultation = 0
    total_booked = 0
    total_completed = 0
    total_doctors_active = 0
    doctor_queues = {}
    all_doctors = []

    for clinic in clinics:
        # Clinic display status
        if clinic['status'] == "Temporary Closed":
            clinic['display_status'] = "Temporary Closed"
        elif clinic['status'] == "Permanently Closed":
            clinic['display_status'] = "Permanently Closed"
        elif (
            clinic['opening_time']
            and clinic['closing_time']
            and clinic['opening_time'] <= current_time <= clinic['closing_time']
        ):
            clinic['display_status'] = "Open"
        else:
            clinic['display_status'] = "Closed"

        # =========================
        # GET DOCTORS FOR THIS CLINIC
        # =========================
        cursor.execute("""
            SELECT *
            FROM doctors
            WHERE clinic_id=%s
            AND status='Active'
            ORDER BY name
        """, (clinic['id'],))
        doctors = cursor.fetchall()
        clinic['doctors'] = doctors
        all_doctors.extend(doctors)

        for doctor in doctors:
            total_doctors_active += 1

            # =========================
            # GET TODAY'S ACTIVE APPOINTMENTS FOR THIS DOCTOR
            # In-Consultation spans across days (overnight), so include regardless of date
            # Booked and Waiting should only be today's appointments
            # =========================
            cursor.execute("""
                SELECT
                    a.*,
                    p.full_name AS patient_name,
                    p.contact_number AS patient_contact
                FROM appointments a
                LEFT JOIN patients p ON a.patient_id = p.id
                WHERE a.doctor_id=%s
                AND (
                    (a.date=CURDATE() AND a.status IN ('Booked', 'Waiting'))
                    OR
                    (a.status='In-Consultation')
                )
                ORDER BY
                    CASE
                        WHEN a.priority='HIGH' AND LOWER(a.urgency)='very urgent' THEN 1
                        WHEN a.priority='HIGH' AND LOWER(a.urgency)='urgent' THEN 2
                        ELSE 3
                    END,
                    a.time ASC
            """, (doctor['id'],))
            appointments = cursor.fetchall()

            if appointments:
                doctor_queues[doctor['id']] = appointments
                total_in_queue += len(appointments)

                for apt in appointments:
                    if apt['status'] == 'Waiting':
                        total_waiting += 1
                    elif apt['status'] == 'In-Consultation':
                        total_in_consultation += 1
                    elif apt['status'] == 'Booked':
                        total_booked += 1

        # =========================
        # COUNT TODAY'S COMPLETED APPOINTMENTS FOR THIS CLINIC
        # =========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
            WHERE clinic=%s
            AND date=CURDATE()
            AND status='Completed'
        """, (clinic['clinic_name'],))
        completed_count = cursor.fetchone()['total']
        total_completed += completed_count

    # =========================
    # CLINIC QUEUE SUMMARY
    # =========================
    clinic_queue_summary = []
    for clinic in clinics:
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
            WHERE clinic=%s
            AND date=CURDATE()
            AND status IN ('Booked', 'Waiting', 'In-Consultation')
        """, (clinic['clinic_name'],))
        queue_total = cursor.fetchone()['total']

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
            WHERE clinic=%s
            AND date=CURDATE()
            AND status='Waiting'
        """, (clinic['clinic_name'],))
        waiting_total = cursor.fetchone()['total']

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
            WHERE clinic=%s
            AND date=CURDATE()
            AND status='In-Consultation'
        """, (clinic['clinic_name'],))
        consultation_total = cursor.fetchone()['total']

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
            WHERE clinic=%s
            AND date=CURDATE()
            AND status='Completed'
        """, (clinic['clinic_name'],))
        completed_total = cursor.fetchone()['total']

        clinic_queue_summary.append({
            'id': clinic['id'],
            'clinic_name': clinic['clinic_name'],
            'display_status': clinic['display_status'],
            'queue_total': queue_total,
            'waiting_total': waiting_total,
            'consultation_total': consultation_total,
            'completed_total': completed_total,
            'doctor_count': len(clinic.get('doctors', []))
        })

    conn.close()

    return render_template(
        'queue_monitoring.html',
        clinics=clinics,
        all_doctors=all_doctors,
        doctor_queues=doctor_queues,
        clinic_queue_summary=clinic_queue_summary,
        total_in_queue=total_in_queue,
        total_waiting=total_waiting,
        total_in_consultation=total_in_consultation,
        total_booked=total_booked,
        total_completed=total_completed,
        total_doctors_active=total_doctors_active,
        last_updated=datetime.now().strftime("%d %b %Y %I:%M %p")
    )


# =========================
# LOGOUT
# =========================
@app.route('/logout')
def logout():

    session.clear()

    return redirect(url_for('home'))



# =========================
# RUN FLASK
# =========================
if __name__ == '__main__':

    app.run(debug=True)
