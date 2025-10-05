import json
import os
import uuid
import magic
import fitz
import logging
from .adapter_meta import download_media
from backend.connect_supabase import supabase, log_receipt  # <<< هيدا هو
from openai import OpenAI
from datetime import datetime, timezone
logger = logging.getLogger("media_service")
logger.setLevel(logging.INFO)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

BUCKET = "receipts"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY_PROJECT"))


def detect_pdf_intent(text: str):
    prompt = f"""
    You are a document intent classifier.
    Read the following text and answer in JSON strictly like this:
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
    """
    Download any WhatsApp media and save it locally.
    Returns the local file path.
    """
    data = download_media(media_id)

    if not filename:
        filename = f"{media_id}.bin"

    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(data)

    return path

def validate_file(data: bytes, expected_types=("application/pdf", "image/jpeg", "image/png")):
    """
    Validate MIME type of uploaded file.
    """
    mime = magic.from_buffer(data, mime=True)
    if mime not in expected_types:
        raise ValueError(f"Invalid file type: {mime}")
    return mime


def store_to_supabase(data: bytes, ext: str) -> str:
    """
    Upload to Supabase storage and return signed URL.
    """
    filename = f"{uuid.uuid4()}.{ext}"
    path = f"receipts/{filename}"

    # Upload
    supabase.storage.from_(BUCKET).upload(path, data)

    # Generate signed URL valid for 1 hour
    signed_url = supabase.storage.from_(BUCKET).create_signed_url(path, 3600)
    return signed_url["signedURL"]


def save_pdf(media_id: str, filename: str = None) -> str:
    """
    Save a PDF locally from WhatsApp media.
    """
    data = download_media(media_id)
    if not filename:
        filename = f"{media_id}.pdf"

    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path


def extract_pdf_text(path: str) -> str:
    """
    Extract text from a PDF file using PyMuPDF.
    """
    doc = fitz.open(path)
    text = "".join([page.get_text() for page in doc])
    doc.close()
    return text


def handle_receipt(media_id: str, claim_id: str, participant_id: str) -> str:
    data = download_media(media_id)

    # 1. Validate
    mime = validate_file(data)
    ext = "pdf" if mime == "application/pdf" else "jpg"

    # 2. Upload
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = f"receipts/{filename}"
    supabase.storage.from_(BUCKET).upload(file_path, data)

    # 3. Save in DB
    log_receipt(claim_id, participant_id, file_path)

    # 4. Signed link for preview
    signed_url = supabase.storage.from_(BUCKET).create_signed_url(file_path, 3600)

    # 5. Extract preview if PDF
    preview = ""
    if ext == "pdf":
        tmp_path = save_pdf(media_id)
        text = extract_pdf_text(tmp_path)

        # Step: analyze PDF intent
        intent_data = detect_pdf_intent(text)

        if intent_data["intent"] == "visit_schedule" and intent_data["visit_date"]:
            from backend.reminder_service import schedule_reminder
            from datetime import datetime

            visit_dt = datetime.fromisoformat(intent_data["visit_date"])

            # update participant’s next visit
            supabase.table("participants").update({
                "next_visit_at": visit_dt.isoformat()
            }).eq("id", participant_id).execute()

            # Schedule 3 distinct reminders
            schedule_reminder(
                participant_id,
                f"🗓️ Visit scheduled on {visit_dt:%d %b %H:%M}",
                delay_minutes=0,
                template_type="visit_created",
                immediate=True  # new flag
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

    return f"✅ Receipt saved. Signed link: {signed_url['signedURL']}\n📄 Preview: {preview}"

