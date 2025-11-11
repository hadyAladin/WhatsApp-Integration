import io
import logging
import os
import time
import hmac
import hashlib
from typing import Any, Dict, Optional

import requests
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL")
PARTICIPANT_ID = os.getenv("PARTICIPANT_ID", "418fb3c2-f745-4976-aeea-48624b5ea1f3")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
BACKEND_SERVICE_TOKEN = os.getenv("BACKEND_SERVICE_TOKEN")

MAX_MEDIA_SIZE = int(os.getenv("MAX_MEDIA_SIZE", 5 * 1024 * 1024))
ALLOWED_MIMES = {m.strip() for m in os.getenv("ALLOWED_MIMES", "application/pdf,image/jpeg,image/png").split(",")}
ALLOWED_SENDERS = {s.strip() for s in os.getenv("ALLOWED_SENDERS", "").split(",") if s.strip()}
DEDUP_TTL = int(os.getenv("DEDUP_TTL", 60))

TRIAL_ID_CACHE: Dict[str, Optional[str]] = {"value": None}
pending_receipts: Dict[str, Dict[str, Any]] = {}
seen_messages: Dict[str, float] = {}

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
logger = logging.getLogger("gateway")

if not VERIFY_TOKEN or VERIFY_TOKEN == "12345":
    logger.error("Weak or missing VERIFY_TOKEN")
if not BACKEND_BASE_URL.lower().startswith("https://"):
    logger.warning("BACKEND_BASE_URL is not HTTPS")

app = Flask(__name__)

def safe_log_response(prefix: str, r: requests.Response) -> None:
    text = (r.text or "")[:200]
    for k in ("WHATSAPP_TOKEN", "BACKEND_SERVICE_TOKEN"):
        v = os.getenv(k)
        if v and v in text:
            text = text.replace(v, "[REDACTED]")
    logger.info(f"{prefix} status={r.status_code} body={text}")

def backend_headers() -> Dict[str, str]:
    h: Dict[str, str] = {}
    if BACKEND_SERVICE_TOKEN:
        h["Authorization"] = f"Bearer {BACKEND_SERVICE_TOKEN}"
    return h

def verify_signature(raw_body: bytes, header_signature: Optional[str]) -> bool:
    if not WHATSAPP_APP_SECRET:
        logger.warning("WHATSAPP_APP_SECRET missing; signature verification disabled")
        return True
    if not header_signature or "sha256=" not in header_signature:
        return False
    expected = hmac.new(WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = header_signature.split("sha256=")[1]
    return hmac.compare_digest(expected, provided)

def is_duplicate(message_id: Optional[str]) -> bool:
    if not message_id:
        return False
    now = time.time()
    for k, ts in list(seen_messages.items()):
        if now - ts > DEDUP_TTL:
            seen_messages.pop(k, None)
    if message_id in seen_messages:
        return True
    seen_messages[message_id] = now
    return False

def send_whatsapp_message(to: str, text: str) -> None:
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing WhatsApp credentials")
        return
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text.strip()}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        safe_log_response(f"[WhatsApp] Sent to {to}", r)
    except Exception as e:
        logger.error(f"[WhatsApp] Send failed: {e}", exc_info=True)

def get_media_url(media_id: str) -> Optional[str]:
    try:
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get("url")
    except Exception as e:
        logger.error(f"[Media] Failed to get media URL: {e}", exc_info=True)
        return None

def download_media_file(media_url: str) -> Optional[bytes]:
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        with requests.get(media_url, headers=headers, timeout=30, stream=True) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "").split(";")[0]
            if content_type not in ALLOWED_MIMES:
                logger.warning(f"[Media] Disallowed mime {content_type}")
                return None
            length = r.headers.get("Content-Length")
            if length and int(length) > MAX_MEDIA_SIZE:
                logger.warning(f"[Media] Remote file too large: {length}")
                return None
            chunks = []
            size = 0
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_MEDIA_SIZE:
                    logger.warning("[Media] Download exceeds max size")
                    return None
                chunks.append(chunk)
            data = b"".join(chunks)
            logger.info(f"[Media] Downloaded {len(data)} bytes, mime={content_type}")
            return data
    except Exception as e:
        logger.error(f"[Media] Download failed: {e}", exc_info=True)
        return None

def fetch_trial_id() -> Optional[str]:
    if TRIAL_ID_CACHE["value"]:
        return TRIAL_ID_CACHE["value"]
    url = f"{BACKEND_BASE_URL}/api/participants/{PARTICIPANT_ID}"
    try:
        r = requests.get(url, headers=backend_headers(), timeout=10)
        r.raise_for_status()
        trial_id = r.json().get("trial_id")
        TRIAL_ID_CACHE["value"] = trial_id
        logger.info(f"[Backend] trial_id={trial_id}")
        return trial_id
    except Exception as e:
        logger.error(f"[Backend] Trial fetch failed: {e}", exc_info=True)
        return None

def call_rag_endpoint(question: str) -> str:
    """Send text query to backend chat endpoint."""
    payload = {
        "participant_id": PARTICIPANT_ID,
        "question": question,
        "visit_type_code": "",
        "channel": "whatsapp",
    }

    try:
        url = f"{BACKEND_BASE_URL}/participants/chat/send"
        headers = backend_headers()
        headers["Content-Type"] = "application/json"

        # 🔍 trace the request
        logger.info(f"[Backend] Sending POST to {url} with payload: {payload}")

        r = requests.post(url, json=payload, headers=headers, timeout=60)
        logger.info(f"[Backend] Chat response {r.status_code}: {r.text[:200]}")
        r.raise_for_status()

        data = r.json()
        return data.get("answer") or "I couldn't find an answer for that."
    except requests.exceptions.HTTPError as e:
        logger.error(f"[Backend] HTTP error {e.response.status_code}: {e.response.text}")
        return "The assistant could not process your message."
    except Exception as e:
        logger.error(f"[Backend] Chat call failed: {e}", exc_info=True)
        return "There was a problem reaching the assistant."



def get_participant_visits() -> list:
    try:
        url = f"{BACKEND_BASE_URL}/api/visits"
        params = {"participant_id": PARTICIPANT_ID}
        r = requests.get(url, params=params, headers=backend_headers(), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"[Backend] Visit fetch failed: {e}", exc_info=True)
        return []

def upload_receipt_with_visit(sender: str, visit_id: str) -> str:
    receipt = pending_receipts.pop(sender, None)
    if not receipt:
        return "No pending receipt found."
    url = f"{BACKEND_BASE_URL}/api/receipts/upload"
    files = {"file": (receipt["filename"], io.BytesIO(receipt["file_bytes"]), receipt["mime_type"])}
    data = {"participant_id": PARTICIPANT_ID, "visit_id": visit_id, "source_channel": "whatsapp"}
    try:
        r = requests.post(url, data=data, files=files, headers=backend_headers(), timeout=30)
        safe_log_response("[Backend] Upload", r)
        r.raise_for_status()
        return "Receipt uploaded successfully."
    except Exception as e:
        logger.error(f"[Backend] Upload failed: {e}", exc_info=True)
        return "Failed to upload receipt. Please try again later."

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        raw_body = request.get_data()
        sig = request.headers.get("X-Hub-Signature-256")
        if not verify_signature(raw_body, sig):
            logger.warning("[Webhook] Invalid signature")
            return "Forbidden", 403

        data = request.get_json(force=True, silent=True) or {}
        entry = (data.get("entry") or [{}])[0]
        changes = (entry.get("changes") or [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return "", 200

        msg = messages[0]
        sender = msg.get("from")
        if ALLOWED_SENDERS and sender not in ALLOWED_SENDERS:
            logger.warning(f"[Webhook] Sender not allowed: {sender}")
            send_whatsapp_message(sender, "Your number is not registered for this service.")
            return "", 200

        message_id = msg.get("id")
        if is_duplicate(message_id):
            logger.info(f"[Webhook] Duplicate message {message_id}")
            return "", 200

        msg_type = msg.get("type")
        logger.info(f"[Webhook] From {sender} type={msg_type}")

        if msg_type == "text":
            text = msg.get("text", {}).get("body", "").strip()
            if not text:
                send_whatsapp_message(sender, "Please send a valid message.")
                return "", 200
            if sender in pending_receipts:
                visits = get_participant_visits()
                try:
                    index = int(text) - 1
                    if index < 0 or index >= len(visits):
                        raise IndexError
                    visit_id = visits[index]["id"]
                    msg_out = upload_receipt_with_visit(sender, visit_id)
                    send_whatsapp_message(sender, msg_out)
                except Exception:
                    send_whatsapp_message(sender, "Invalid selection. Please try again.")
                return "", 200
            reply = call_rag_endpoint(text)
            send_whatsapp_message(sender, reply)
            return "", 200

        if msg_type in {"image", "document"}:
            media_info = msg.get(msg_type, {})
            media_id = media_info.get("id")
            mime_type = media_info.get("mime_type", "application/octet-stream").split(";")[0]
            filename = media_info.get("filename") or f"receipt.{mime_type.split('/')[-1]}"

            if not media_id:
                send_whatsapp_message(sender, "Missing media ID.")
                return "", 200
            if mime_type not in ALLOWED_MIMES:
                send_whatsapp_message(sender, "Unsupported file type.")
                return "", 200

            media_url = get_media_url(media_id)
            if not media_url:
                send_whatsapp_message(sender, "Could not retrieve media URL.")
                return "", 200

            file_bytes = download_media_file(media_url)
            if not file_bytes:
                send_whatsapp_message(sender, "Failed to download receipt file.")
                return "", 200

            pending_receipts[sender] = {"file_bytes": file_bytes, "filename": filename, "mime_type": mime_type}

            visits = get_participant_visits()
            if not visits:
                send_whatsapp_message(sender, "No scheduled visits found.")
                pending_receipts.pop(sender, None)
                return "", 200

            options = "\n".join([f"{i+1}. {v['name']} ({v.get('scheduled_date','')})" for i, v in enumerate(visits)])
            send_whatsapp_message(sender, "Select the visit this receipt belongs to:\n" + options)
            return "", 200

        send_whatsapp_message(sender, "I can only process text messages or receipts.")
        return "", 200

    except Exception:
        logger.exception("[Webhook] Unhandled exception")
        return "Internal Error", 500

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
