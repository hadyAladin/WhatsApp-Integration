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
def detect_pdf_intent(text: str):
    """
    Classify PDF content into visit_schedule / receipt_upload / other.
    """
    prompt = f"""
    You are a document intent classifier.
    Read the following text and answer strictly in JSON:
    {{
      "intent": "visit_schedule" or "receipt_upload" or "other",
      "visit_date": "YYYY-MM-DD HH:MM" or null
    }}
    Text:
    {text[:4000]}
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": prompt}]
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {"intent": "receipt_upload", "visit_date": None}


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
