# app.py
import os
import json
import sqlite3
import threading
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, g
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Cho phép gọi từ file HTML nếu mở riêng (không qua Flask serve)

# ===== CẤU HÌNH EMAIL =====
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USERNAME = "phucrequiem@gmail.com"  
MAIL_PASSWORD = "kbsfwnylqvkdvjij"  
# ===========================

# ===== DATABASE =====
DATABASE = 'scheduler.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                scheduled_time TEXT NOT NULL,
                email_to TEXT NOT NULL,
                notify_before TEXT DEFAULT '[1, 12, 24]',
                notification_sent INTEGER DEFAULT 0,
                notification_failed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()

# ===== GỬI EMAIL =====
def send_email(recipient, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = MAIL_USERNAME
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

# ===== BACKGROUND THREAD KIỂM TRA NHẮC HẸN =====
def check_reminders(app):
    with app.app_context():
        from datetime import datetime, timedelta, timezone
        while True:
            now = datetime.now(timezone.utc)  # aware
            db = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row
            cur = db.execute("SELECT * FROM schedules WHERE notification_sent=0")
            schedules = cur.fetchall()
            print(f"[BG] Checking reminders at {now} – total pending: {len(schedules)}")
            
            for s in schedules:
                try:
                    notify_hours = json.loads(s['notify_before'])
                except:
                    notify_hours = [1, 12, 24]
                
                scheduled = datetime.fromisoformat(s['scheduled_time'])
                # Đảm bảo scheduled là aware UTC
                if scheduled.tzinfo is None:
                    scheduled = scheduled.replace(tzinfo=timezone.utc)
                else:
                    # Chuyển về UTC nếu nó có timezone khác (phòng trường hợp)
                    scheduled = scheduled.astimezone(timezone.utc)
                
                for hours in notify_hours:
                    remind = scheduled - timedelta(hours=hours)
                    # So sánh an toàn
                    if abs((now - remind).total_seconds()) < 60:
                        subject = f"⏰ Nhắc hẹn: {s['title']}"
                        body = f"<h2>{s['title']}</h2><p>Thời gian: {scheduled.strftime('%d/%m/%Y %H:%M')}</p><p>{s['description']}</p>"
                        if send_email(s['email_to'], subject, body):
                            db.execute("UPDATE schedules SET notification_sent=1 WHERE id=?", (s['id'],))
                        else:
                            db.execute("UPDATE schedules SET notification_failed=1 WHERE id=?", (s['id'],))
                        db.commit()
                        break
            db.close()
            time.sleep(30)

# ===== ROUTES =====

@app.route('/')
def index():
    # Trả về giao diện lịch
    return render_template('scheduler.html')

# API: lấy tất cả lịch (demo chưa có phân quyền user, sau này thêm user_id)
@app.route('/api/schedules')
def get_schedules():
    db = get_db()
    rows = db.execute("SELECT * FROM schedules ORDER BY scheduled_time ASC").fetchall()
    schedules = []
    for r in rows:
        try:
            notify = json.loads(r['notify_before'])
        except:
            notify = [1,12,24]
        schedules.append({
            'id': r['id'],
            'title': r['title'],
            'description': r['description'],
            'scheduled_time': r['scheduled_time'],
            'email_to': r['email_to'],
            'notify_before': notify,
            'notification_sent': bool(r['notification_sent']),
            'notification_failed': bool(r['notification_failed']),
            'created_at': r['created_at']
        })
    return jsonify({'schedules': schedules})

@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    data = request.json
    if not data.get('title') or not data.get('scheduled_time') or not data.get('email_to'):
        return jsonify({'error': 'Thiếu thông tin bắt buộc'}), 400
    notify = json.dumps(data.get('notify_before', [1,12,24]))
    db = get_db()
    db.execute(
        "INSERT INTO schedules (title, description, scheduled_time, email_to, notify_before) VALUES (?, ?, ?, ?, ?)",
        (data['title'], data.get('description', ''), data['scheduled_time'], data['email_to'], notify)
    )
    db.commit()
    return jsonify({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]}), 201

@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
def update_schedule(schedule_id):
    data = request.json
    db = get_db()
    existing = db.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
    if not existing:
        return jsonify({'error': 'Không tìm thấy'}), 404
    title = data.get('title', existing['title'])
    desc = data.get('description', existing['description'])
    sched_time = data.get('scheduled_time', existing['scheduled_time'])
    email_to = data.get('email_to', existing['email_to'])
    if 'notify_before' in data:
        notify = json.dumps(data['notify_before'])
    else:
        notify = existing['notify_before']
    # Reset trạng thái nếu thay đổi thời gian
    sent = existing['notification_sent']
    failed = existing['notification_failed']
    if 'scheduled_time' in data:
        sent = 0
        failed = 0
    db.execute(
        "UPDATE schedules SET title=?, description=?, scheduled_time=?, email_to=?, notify_before=?, notification_sent=?, notification_failed=? WHERE id=?",
        (title, desc, sched_time, email_to, notify, sent, failed, schedule_id)
    )
    db.commit()
    return jsonify({'message': 'Đã cập nhật'})

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    db = get_db()
    db.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
    db.commit()
    return jsonify({'message': 'Đã xóa'})

@app.route('/api/schedules/<int:schedule_id>/test-notify', methods=['POST'])
def test_notify(schedule_id):
    db = get_db()
    s = db.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
    if not s:
        return jsonify({'error': 'Không tìm thấy'}), 404
    subject = f"[TEST] Nhắc hẹn: {s['title']}"
    body = f"<h2>{s['title']}</h2><p>Thời gian: {s['scheduled_time']}</p>"
    if send_email(s['email_to'], subject, body):
        return jsonify({'message': 'Đã gửi test email'})
    return jsonify({'error': 'Gửi thất bại'}), 500

# ===== KHỞI ĐỘNG =====
if __name__ == '__main__':
    init_db()
    # Khởi chạy thread kiểm tra nhắc nhở
    threading.Thread(target=check_reminders, args=(app,), daemon=True).start()
    app.run(debug=True, port=5000)