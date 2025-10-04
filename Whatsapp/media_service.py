import os
import uuid
import magic  # for MIME type detection
import fitz   # PyMuPDF for PDFs
from .adapter_meta import download_media
from backend.connect_supabase import supabase, log_receipt

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

BUCKET = "receipts"  # Supabase storage bucket

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
        preview = text[:200] if text.strip() else "No text extracted."

    return f"✅ Receipt saved. Signed link: {signed_url['signedURL']}\n📄 Preview: {preview}"

