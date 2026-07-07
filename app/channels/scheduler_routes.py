# app/channels/scheduler_routes.py
"""
Scheduler API Routes — FastAPI endpoints cho quản lý lịch nhắc hẹn.
Tích hợp SQLite-based scheduler từ scheduler_module vào hệ thống chính.
"""
import asyncio
import json
import logging
import smtplib
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

# ============================================================
# DATABASE
# ============================================================

DB_PATH = Path(__file__).parent.parent.parent / "scheduler_module" / "scheduler.db"


def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_scheduler_db():
    """Khởi tạo bảng schedules nếu chưa có."""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = get_db_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                scheduled_time TEXT NOT NULL,
                email_to TEXT NOT NULL,
                notify_before TEXT DEFAULT '[1, 12, 24]',
                notification_sent INTEGER DEFAULT 0,
                notification_failed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        logger.info("✅ Scheduler DB initialized")
    except Exception as e:
        logger.error(f"Scheduler DB init error: {e}")


# ============================================================
# EMAIL
# ============================================================

def send_reminder_email(recipient: str, subject: str, body: str) -> bool:
    """Gửi email nhắc hẹn qua SMTP."""
    try:
        mail_server = getattr(settings, "mail_server", "smtp.gmail.com")
        mail_port = getattr(settings, "mail_port", 587)
        mail_username = getattr(settings, "mail_username", "")
        mail_password = getattr(settings, "mail_password", "")

        if not mail_username or not mail_password:
            logger.warning("Mail credentials not configured — skipping email")
            return False

        msg = MIMEMultipart()
        msg["From"] = mail_username
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(mail_server, mail_port) as server:
            server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False


# ============================================================
# BACKGROUND REMINDER CHECKER
# ============================================================

_reminder_thread: Optional[threading.Thread] = None
_reminder_running = False


def _check_reminders_loop():
    """Vòng lặp background kiểm tra và gửi nhắc hẹn."""
    global _reminder_running
    logger.info("⏰ Scheduler reminder thread started")
    while _reminder_running:
        try:
            now = datetime.now(timezone.utc)
            conn = get_db_connection()
            rows = conn.execute(
                "SELECT * FROM schedules WHERE notification_sent=0 AND notification_failed=0"
            ).fetchall()

            for row in rows:
                try:
                    notify_hours = json.loads(row["notify_before"])
                except Exception:
                    notify_hours = [1, 12, 24]

                scheduled = datetime.fromisoformat(row["scheduled_time"])
                if scheduled.tzinfo is None:
                    scheduled = scheduled.replace(tzinfo=timezone.utc)
                else:
                    scheduled = scheduled.astimezone(timezone.utc)

                for hours in notify_hours:
                    remind_at = scheduled - timedelta(hours=hours)
                    if abs((now - remind_at).total_seconds()) < 60:
                        subject = f"⏰ Nhắc hẹn: {row['title']}"
                        body = (
                            f"<h2>{row['title']}</h2>"
                            f"<p><strong>Thời gian:</strong> {scheduled.strftime('%d/%m/%Y %H:%M UTC')}</p>"
                            f"<p>{row['description'] or ''}</p>"
                            + (f"<p><em>📝 {row['notes']}</em></p>" if row.get("notes") else "")
                        )
                        success = send_reminder_email(row["email_to"], subject, body)
                        if success:
                            conn.execute(
                                "UPDATE schedules SET notification_sent=1 WHERE id=?", (row["id"],)
                            )
                        else:
                            conn.execute(
                                "UPDATE schedules SET notification_failed=1 WHERE id=?", (row["id"],)
                            )
                        conn.commit()
                        break

            conn.close()
        except Exception as e:
            logger.error(f"Reminder check error: {e}")

        time.sleep(30)

    logger.info("⏰ Scheduler reminder thread stopped")


def start_reminder_thread():
    """Khởi động background thread nhắc hẹn."""
    global _reminder_thread, _reminder_running
    if _reminder_thread and _reminder_thread.is_alive():
        return
    _reminder_running = True
    _reminder_thread = threading.Thread(
        target=_check_reminders_loop, daemon=True, name="scheduler-reminders"
    )
    _reminder_thread.start()


def stop_reminder_thread():
    """Dừng background thread nhắc hẹn."""
    global _reminder_running
    _reminder_running = False


# ============================================================
# PYDANTIC MODELS
# ============================================================

class ScheduleCreate(BaseModel):
    title: str
    description: str = ""
    notes: str = ""
    scheduled_time: str
    email_to: str
    notify_before: List[int] = [1, 12, 24]


class ScheduleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    scheduled_time: Optional[str] = None
    email_to: Optional[str] = None
    notify_before: Optional[List[int]] = None


# ============================================================
# HELPER
# ============================================================

def _row_to_dict(row) -> dict:
    try:
        notify = json.loads(row["notify_before"])
    except Exception:
        notify = [1, 12, 24]
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"] or "",
        "notes": row["notes"] if "notes" in row.keys() else "",
        "scheduled_time": row["scheduled_time"],
        "email_to": row["email_to"],
        "notify_before": notify,
        "notification_sent": bool(row["notification_sent"]),
        "notification_failed": bool(row["notification_failed"]),
        "created_at": row["created_at"],
    }


# ============================================================
# ROUTES
# ============================================================

@router.get("/schedules")
async def get_schedules():
    """Lấy tất cả lịch, sắp xếp theo thời gian."""
    try:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM schedules ORDER BY scheduled_time ASC"
        ).fetchall()
        conn.close()
        return {"schedules": [_row_to_dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"Get schedules error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedules", status_code=201)
async def create_schedule(data: ScheduleCreate):
    """Tạo lịch nhắc hẹn mới."""
    if not data.title.strip():
        raise HTTPException(status_code=400, detail="Tiêu đề không được để trống")
    if not data.scheduled_time:
        raise HTTPException(status_code=400, detail="Thời gian không được để trống")
    if not data.email_to.strip():
        raise HTTPException(status_code=400, detail="Email không được để trống")

    try:
        conn = get_db_connection()
        cursor = conn.execute(
            """INSERT INTO schedules
               (title, description, notes, scheduled_time, email_to, notify_before)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data.title,
                data.description,
                data.notes,
                data.scheduled_time,
                data.email_to,
                json.dumps(data.notify_before),
            ),
        )
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"id": new_id, "message": "Đã tạo lịch thành công"}
    except Exception as e:
        logger.error(f"Create schedule error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, data: ScheduleUpdate):
    """Cập nhật lịch nhắc hẹn."""
    try:
        conn = get_db_connection()
        existing = conn.execute(
            "SELECT * FROM schedules WHERE id=?", (schedule_id,)
        ).fetchone()
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="Không tìm thấy lịch")

        title = data.title if data.title is not None else existing["title"]
        description = data.description if data.description is not None else existing["description"]
        notes = data.notes if data.notes is not None else (existing["notes"] if "notes" in existing.keys() else "")
        scheduled_time = data.scheduled_time if data.scheduled_time is not None else existing["scheduled_time"]
        email_to = data.email_to if data.email_to is not None else existing["email_to"]
        notify_before = (
            json.dumps(data.notify_before) if data.notify_before is not None else existing["notify_before"]
        )

        # Reset trạng thái nếu đổi thời gian
        sent = existing["notification_sent"]
        failed = existing["notification_failed"]
        if data.scheduled_time is not None:
            sent = 0
            failed = 0

        conn.execute(
            """UPDATE schedules
               SET title=?, description=?, notes=?, scheduled_time=?,
                   email_to=?, notify_before=?, notification_sent=?, notification_failed=?
               WHERE id=?""",
            (title, description, notes, scheduled_time, email_to, notify_before, sent, failed, schedule_id),
        )
        conn.commit()
        conn.close()
        return {"message": "Đã cập nhật lịch thành công"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update schedule error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    """Xóa lịch nhắc hẹn."""
    try:
        conn = get_db_connection()
        existing = conn.execute(
            "SELECT id FROM schedules WHERE id=?", (schedule_id,)
        ).fetchone()
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="Không tìm thấy lịch")
        conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
        conn.commit()
        conn.close()
        return {"message": "Đã xóa lịch thành công"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete schedule error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedules/{schedule_id}/test-notify")
async def test_notify(schedule_id: int):
    """Gửi email test cho lịch nhắc hẹn."""
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT * FROM schedules WHERE id=?", (schedule_id,)
        ).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Không tìm thấy lịch")

        subject = f"[TEST] Nhắc hẹn: {row['title']}"
        body = (
            f"<h2>📧 Email test từ AuraFactory Scheduler</h2>"
            f"<h3>{row['title']}</h3>"
            f"<p><strong>Thời gian:</strong> {row['scheduled_time']}</p>"
            f"<p>{row['description'] or ''}</p>"
        )

        # Chạy gửi email trong thread pool để không block event loop
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            None, send_reminder_email, row["email_to"], subject, body
        )

        if success:
            return {"message": f"Đã gửi email test tới {row['email_to']}"}
        raise HTTPException(status_code=500, detail="Gửi email thất bại — kiểm tra cấu hình SMTP")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test notify error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
