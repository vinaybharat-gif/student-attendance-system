import os
import io
import csv
import sqlite3
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'attendance-hub-dev-secret-key')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'database.db')

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    schema_path = os.path.join(BASE_DIR, 'schema.sql')
    if not os.path.exists(schema_path):
        return
    conn = get_db()
    with open(schema_path, mode='r') as f:
        conn.executescript(f.read())

    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    if count == 0:
        sample_students = [
            ('21CSE02', 'Bhavana Rao', 'CSE', 'A', 'bhavana@example.com'),
            ('21ECE01', 'Chaitanya Redy', 'ECE', 'B', 'chaitanya@example.com'),
            ('21ECE02', 'Divya Sharma', 'ECE', 'A', 'divya@example.com'),
            ('21EEE01', 'Eswar Teja', 'EEE', 'A', 'eswar@example.com'),
            ('21MEC01', 'Farooq Ahmed', 'MECH', 'A', 'farooq@example.com')
        ]
        cursor.executemany(
            "INSERT INTO students (roll_no, name, department, section, email) VALUES (?, ?, ?, ?, ?)",
            sample_students
        )
        conn.commit()
    conn.close()

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('index.html', user=dict(session))

@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/register')
def register_page():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    role = data.get('role')
    roll_no = (data.get('roll_no') or '').strip()
    department = (data.get('department') or '').strip()

    if not all([username, email, password, role]):
        return jsonify({'error': 'All required fields must be filled!'}), 400

    if role not in ('Student', 'Teacher'):
        return jsonify({'error': 'Please select a valid role (Student or Teacher)!'}), 400

    if role == 'Student' and not roll_no:
        return jsonify({'error': 'Roll number is required for Student registration!'}), 400

    hashed_pw = generate_password_hash(password)
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (username, email, password, role, roll_no, department) VALUES (?, ?, ?, ?, ?, ?)",
            (username, email, hashed_pw, role, roll_no, department)
        )

        if role == 'Student' and roll_no:
            cursor.execute(
                "INSERT OR IGNORE INTO students (roll_no, name, department, section, email) VALUES (?, ?, ?, 'A', ?)",
                (roll_no, username, department or 'CSE', email)
            )

        conn.commit()
        conn.close()
        return jsonify({'message': 'Registration successful! Please login.'}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Username or Email already exists!'}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and Password are required!'}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        session['email'] = user['email']
        session['roll_no'] = user['roll_no']
        return jsonify({'message': 'Login successful!', 'role': user['role']})

    return jsonify({'error': 'Invalid Email or Password!'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})

@app.route('/api/students', methods=['GET', 'POST'])
def handle_students():
    conn = get_db()
    if request.method == 'POST':
        data = request.json or {}
        roll_no = data.get('roll_no')
        name = data.get('name')
        department = data.get('department')
        section = data.get('section', 'A')
        email = data.get('email')

        if not roll_no or not name or not department or not email:
            conn.close()
            return jsonify({'error': 'All fields are required'}), 400

        try:
            conn.execute(
                "INSERT INTO students (roll_no, name, department, section, email) VALUES (?, ?, ?, ?, ?)",
                (roll_no, name, department, section, email)
            )
            conn.commit()
            conn.close()
            return jsonify({'message': 'Student added successfully!'}), 201
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'error': 'Roll number already exists!'}), 400

    students = conn.execute("SELECT * FROM students ORDER BY roll_no").fetchall()
    conn.close()
    return jsonify([dict(s) for s in students])

@app.route('/api/attendance', methods=['POST'])
def save_attendance():
    data = request.json or {}
    date = data.get('date')
    subject = data.get('subject')
    records = data.get('records', [])

    if not date or not subject or not records:
        return jsonify({'error': 'Missing required fields'}), 400

    conn = get_db()
    for item in records:
        conn.execute(
            """
            INSERT INTO attendance (student_id, date, subject, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(student_id, date, subject) DO UPDATE SET status=excluded.status
            """,
            (item['student_id'], date, subject, item['status'])
        )
    conn.commit()
    conn.close()
    return jsonify({'message': 'Attendance saved successfully'})

@app.route('/api/reports', methods=['GET'])
def get_reports():
    conn = get_db()
    students = conn.execute("SELECT * FROM students").fetchall()

    reports = []
    for s in students:
        s_id = s['id']
        total = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?", (s_id,)).fetchone()[0]
        present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Present'", (s_id,)).fetchone()[0]

        pct = round((present / total) * 100, 1) if total > 0 else 100.0

        reports.append({
            'student_id': s['id'],
            'roll_no': s['roll_no'],
            'name': s['name'],
            'department': s['department'],
            'total_classes': total,
            'present_count': present,
            'percentage': pct,
            'shortage_alert': pct < 75.0
        })
    conn.close()
    return jsonify(reports)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    students = conn.execute("SELECT * FROM students").fetchall()
    total_students = len(students)

    total_pct_sum = 0
    low_count = 0

    for s in students:
        s_id = s['id']
        total = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?", (s_id,)).fetchone()[0]
        present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Present'", (s_id,)).fetchone()[0]
        pct = round((present / total) * 100, 1) if total > 0 else 100.0
        total_pct_sum += pct
        if pct < 75.0:
            low_count += 1

    avg_pct = round(total_pct_sum / total_students, 1) if total_students > 0 else 0
    conn.close()

    return jsonify({
        'total_students': total_students,
        'avg_percentage': avg_pct,
        'low_attendance_count': low_count
    })

@app.route('/api/reports/export', methods=['GET'])
def export_csv():
    conn = get_db()
    students = conn.execute("SELECT * FROM students").fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll Number', 'Student Name', 'Department', 'Total Classes', 'Present', 'Percentage', 'Status'])

    for s in students:
        s_id = s['id']
        total = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?", (s_id,)).fetchone()[0]
        present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Present'", (s_id,)).fetchone()[0]
        pct = round((present / total) * 100, 1) if total > 0 else 100.0
        status = 'Shortage' if pct < 75.0 else 'Eligible'
        writer.writerow([s['roll_no'], s['name'], s['department'], total, present, f"{pct}%", status])

    conn.close()
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=attendance_report.csv"}
    )

init_db()

if __name__ == '__main__':
    app.run(debug=True)
