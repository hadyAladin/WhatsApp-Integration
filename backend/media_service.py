import json
import os
import uuid
import magic
import fitz
import logging
from datetime import datetime
from openai import OpenAI
from typing import Any

from supabase import Client, create_client
from dotenv import load_dotenv, find_dotenv

# ---------------- Safe imports (local + Docker) ----------------
try:
    from reminder_service import schedule_reminder
    from adapter_meta import download_media
except ModuleNotFoundError:
    from backend.reminder_service import schedule_reminder
    from backend.adapter_meta import download_media
    from backend.connect_supabase import log_receipt


# ---------------- Logging setup ----------------
logger = logging.getLogger("media_service")
logger.setLevel(logging.INFO)

# ---------------- Directory setup ----------------
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
BUCKET = "receipts"

# ---------------- OpenAI client ----------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY_PROJECT"))

# --------------- Supabase Client --------------

load_dotenv(find_dotenv())

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

sb: Client = create_client(supabase_url, supabase_key)

# ---------------- Utility functions ----------------

import re
from datetime import datetime

def extract_visit_datetime(text: str) -> str | None:
    """
    Parse date and time strings into a single ISO 'YYYY-MM-DD HH:MM' value.
    Handles formats like:
    2025-10-10, 10/10/2025, 10 Oct 2025, 10:00 AM, 14:30, etc.
    """
    date_pat = re.search(r"(20\d{2}-\d{2}-\d{2})|(\d{1,2}[/-]\d{1,2}[/-]20\d{2})|(\d{1,2}\s+\w+\s+20\d{2})", text)
    time_pat = re.search(r"(\d{1,2}:\d{2}\s?(AM|PM)?)", text, re.IGNORECASE)

    if not date_pat:
        return None
    raw_date = next(g for g in date_pat.groups() if g)
    raw_time = time_pat.group(1).replace(" ", "") if time_pat else "00:00"

    # normalize to ISO
    for fmt in ("%Y-%m-%d%I:%M%p", "%Y-%m-%d%H:%M", "%d/%m/%Y%I:%M%p", "%d/%m/%Y%H:%M",
                "%d-%m-%Y%I:%M%p", "%d-%m-%Y%H:%M", "%d %b %Y%I:%M%p", "%d %b %Y%H:%M"):
        try:
            return datetime.strptime(raw_date + raw_time, fmt).strftime("%Y-%m-%d %H:%M")
        except Exception:
            continue
    return None



def detect_pdf_intent(text: str):
    """
    Safe classifier: LLM decides the intent, regex ensures exact date-time.
    """
    visit_dt = extract_visit_datetime(text)

    # Fast keyword override
    if "visit" in text.lower() and "schedule" in text.lower():
        return {"intent": "visit_schedule", "visit_date": visit_dt}

    # Ask LLM only for type
    prompt = (
        "Classify this text. Return JSON only: "
        '{"intent":"visit_schedule"|"receipt_upload"|"other"}.\n'
        "Consider it visit_schedule if it lists a participant ID, trial ID, or visit date/time.\n"
        f"Text:\n{text[:1000]}"
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini-fast",
            messages=[{"role": "user", "content": prompt}],
            timeout=5
        )
        intent = json.loads(resp.choices[0].message.content)["intent"]
        return {"intent": intent, "visit_date": visit_dt}
    except Exception as e:
        logger.warning(f"AI classification error: {e}")
        return {"intent": "receipt_upload", "visit_date": visit_dt}



def save_file(media_id: str, filename: str = None) -> str:
    """Download any WhatsApp media and save locally."""
    data = download_media(media_id)
    if not filename:
        filename = f"{media_id}.bin"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path


def validate_file(data: bytes, expected_types=("application/pdf", "image/jpeg", "image/png")):
    """Validate MIME type of uploaded file."""
    mime = magic.from_buffer(data, mime=True)
    if mime not in expected_types:
        raise ValueError(f"Invalid file type: {mime}")
    return mime


def store_to_supabase(data: bytes, ext: str) -> str:
    """Upload to Supabase storage and return signed URL."""
    filename = f"{uuid.uuid4()}.{ext}"
    path = f"{BUCKET}/{filename}"
    sb.storage.from_(BUCKET).upload(path, data)
    signed_url = sb.storage.from_(BUCKET).create_signed_url(path, 3600)
    return signed_url["signedURL"]


def save_pdf(media_id: str, filename: str = None) -> str:
    """Save a PDF locally from WhatsApp media."""
    data = download_media(media_id)
    if not filename:
        filename = f"{media_id}.pdf"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path


def extract_pdf_text(path: str) -> str:
    """Extract text from a PDF file using PyMuPDF."""
    doc = fitz.open(path)
    text = "".join([page.get_text() for page in doc])
    doc.close()
    return text


# ---------------- Main handler ----------------
def handle_receipt(media_id: str, claim_id: str, participant_id: str) -> str:
    """Process receipt or visit-schedule PDF."""
    data = download_media(media_id)

    # 1. Validate file type
    mime = validate_file(data)
    ext = "pdf" if mime == "application/pdf" else "jpg"

    # 2. Upload to Supabase
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = f"{BUCKET}/{filename}"
    sb.storage.from_(BUCKET).upload(file_path, data)

    # 3. Log in DB
    log_receipt(claim_id, participant_id, file_path)

    # 4. Signed URL
    signed_url = sb.storage.from_(BUCKET).create_signed_url(file_path, 3600)["signedURL"]

    # 5. If PDF, analyze and maybe schedule reminders
    preview = ""
    if ext == "pdf":
        tmp_path = save_pdf(media_id)
        text = extract_pdf_text(tmp_path)
        intent_data = detect_pdf_intent(text)

        if intent_data["intent"] == "visit_schedule" and intent_data["visit_date"]:
            visit_dt = datetime.fromisoformat(intent_data["visit_date"])

            sb.table("participants").update({
                "next_visit_at": visit_dt.isoformat()
            }).eq("id", participant_id).execute()

            # Schedule 3 notifications
            schedule_reminder(
                participant_id,
                f"🗓️ Visit scheduled on {visit_dt:%d %b %H:%M}",
                delay_minutes=0,
                template_type="visit_created",
                immediate=True
            )
            schedule_reminder(
                participant_id,
                "⏰ Reminder: your visit is in 2 days.",
                delay_minutes=(2 * 24 * 60),
                template_type="visit_2days"
            )
            schedule_reminder(
                participant_id,
                "⏰ Reminder: your visit is in 2 hours.",
                delay_minutes=(2 * 60),
                template_type="visit_2hours"
            )

            return f"✅ Visit scheduled for {visit_dt:%d %b %H:%M}. Reminders set."

        else:
            logger.info("Regular receipt detected – no visit reminders scheduled.")
            preview = text[:200] if text.strip() else "No text extracted."

    return f"✅ Receipt saved. Signed link: {signed_url}\n📄 Preview: {preview}"
