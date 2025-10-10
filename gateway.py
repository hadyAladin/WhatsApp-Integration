import io
import logging
import os
from typing import Any, Dict, Optional, Tuple
import requests
from flask import Flask, request
from dotenv import load_dotenv

# ---------- Load environment ----------
load_dotenv()

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
logger = logging.getLogger("gateway")

app = Flask(__name__)

# ---------- Config ----------
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
PARTICIPANT_ID = os.getenv("PARTICIPANT_ID", "57d611ee-39c5-4495-883e-9f4db257bc83")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

TRIAL_ID_CACHE: Dict[str, Optional[str]] = {"value": None}

# ---------- WhatsApp send ----------
def send_whatsapp_message(to: str, text: str) -> None:
    """Send outbound WhatsApp message through Meta Graph API."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing WhatsApp credentials.")
        return

    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        logger.info(f"Sent to {to} -> {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send message: {e}", exc_info=True)


# ---------- Backend calls ----------
def fetch_trial_id() -> Optional[str]:
    if TRIAL_ID_CACHE["value"]:
        return TRIAL_ID_CACHE["value"]
    url = f"{BACKEND_BASE_URL}/api/participants/{PARTICIPANT_ID}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        trial_id = data.get("trial_id")
        TRIAL_ID_CACHE["value"] = trial_id
        return trial_id
    except Exception as e:
        logger.error(f"Trial ID fetch error: {e}")
        return None


def call_rag_endpoint(question: str) -> str:
    """Send text message to RAG endpoint."""
    trial_id = fetch_trial_id()
    if not trial_id:
        return "Could not determine your trial ID."

    payload = {
        "trial_id": trial_id,
        "participant_id": PARTICIPANT_ID,
        "question": question,
        "channel": "whatsapp",
    }
    try:
        url = f"{BACKEND_BASE_URL}/api/rag/ask"
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        return r.json().get("answer", "No answer found.")
    except Exception as e:
        logger.error(f"RAG call failed: {e}", exc_info=True)
        return "There was a problem reaching the assistant."


def upload_receipt(file_bytes: bytes, filename: str, mime_type: str) -> str:
    """Upload receipt directly to backend."""
    url = f"{BACKEND_BASE_URL}/api/receipts/upload"
    files = {"file": (filename, io.BytesIO(file_bytes), mime_type)}
    data = {"participant_id": PARTICIPANT_ID, "visit_id": "auto"}
    try:
        r = requests.post(url, data=data, files=files, timeout=60)
        r.raise_for_status()
        result = r.json()
        return result if isinstance(result, str) else result.get("message", str(result))
    except Exception as e:
        logger.error(f"Receipt upload failed: {e}", exc_info=True)
        return "Upload failed, please try again later."


# ---------- Flask routes ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    """Main WhatsApp webhook handler."""
    data = request.get_json(force=True, silent=True) or {}
    entry = (data.get("entry") or [{}])[0]
    changes = (entry.get("changes") or [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return "", 200

    msg = messages[0]
    sender = msg.get("from")
    msg_type = msg.get("type")

    if not sender:
        return "", 200

    logger.info(f"Incoming from {sender}: {msg_type}")

    # --- Handle text messages ---
    if msg_type == "text":
        text = msg.get("text", {}).get("body", "").strip()
        if not text:
            send_whatsapp_message(sender, "Please send a message.")
            return "", 200

        reply = call_rag_endpoint(text)
        send_whatsapp_message(sender, reply)
        return "", 200

    # --- Handle file uploads ---
    if msg_type in {"image", "document"}:
        m = msg.get(msg_type, {})
        media_url = m.get("link") or m.get("url")
        mime_type = m.get("mime_type", "application/octet-stream")
        filename = m.get("filename", f"upload.{mime_type.split('/')[-1]}")

        if not media_url:
            send_whatsapp_message(sender, "Missing media URL.")
            return "", 200

        try:
            resp = requests.get(media_url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Media download failed: {e}")
            send_whatsapp_message(sender, "Could not download file.")
            return "", 200

        result = upload_receipt(resp.content, filename, mime_type)
        send_whatsapp_message(sender, f"Receipt upload result: {result}")
        return "", 200

    send_whatsapp_message(sender, "Only text and receipt uploads are supported.")
    return "", 200


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
