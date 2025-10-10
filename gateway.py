import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# ------------------- Load environment -------------------
load_dotenv()

# ------------------- Logging setup -------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ------------------- Core config -------------------
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
PARTICIPANT_ID = os.getenv("PARTICIPANT_ID", "57d611ee-39c5-4495-883e-9f4db257bc83")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

TRIAL_ID_CACHE: Dict[str, Optional[str]] = {"value": None}
user_states: Dict[str, Dict[str, Any]] = {}

# ------------------- Exceptions -------------------
class GatewayError(Exception):
    """Custom exception for gateway errors."""


# ------------------- WhatsApp Send Helper -------------------
def send_whatsapp_message(to: str, text: str) -> None:
    """Send outbound WhatsApp message through Meta Graph API."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing WhatsApp credentials in environment.")
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
        logger.info(f"Sent WhatsApp message to {to}, status={resp.status_code}, body={resp.text}")
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}", exc_info=True)


# ------------------- Backend Helpers -------------------
def fetch_trial_id() -> Optional[str]:
    """Fetch and cache the participant's trial ID from the backend."""
    if TRIAL_ID_CACHE["value"]:
        return TRIAL_ID_CACHE["value"]

    url = f"{BACKEND_BASE_URL}/api/participants/{PARTICIPANT_ID}"
    logger.info("Fetching trial ID from %s", url)
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        trial_id = data.get("trial_id")
        if not trial_id:
            raise GatewayError("Trial ID missing in participant data.")
        TRIAL_ID_CACHE["value"] = trial_id
        return trial_id
    except Exception as exc:
        logger.error("Failed to fetch trial ID: %s", exc, exc_info=True)
        return None


def call_rag_endpoint(question: str) -> Tuple[bool, str]:
    """Send text to RAG endpoint."""
    trial_id = fetch_trial_id()
    if not trial_id:
        return False, "Could not determine your trial ID. Please try later."

    payload = {
        "trial_id": trial_id,
        "participant_id": PARTICIPANT_ID,
        "question": question,
        "channel": "whatsapp",
    }

    url = f"{BACKEND_BASE_URL}/api/rag/ask"
    logger.info("Routing text message to %s", url)

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        answer = data.get("answer", "I couldn't find an answer for that.")
        return True, answer
    except Exception as exc:
        logger.error("Error calling RAG endpoint: %s", exc, exc_info=True)
        return False, "There was a problem reaching the assistant. Please try again."


def fetch_visits() -> Tuple[bool, List[Dict[str, Any]], str]:
    """Fetch visit list for the participant."""
    params = {"participant_id": PARTICIPANT_ID}
    url = f"{BACKEND_BASE_URL}/api/visits"
    logger.info("Fetching visits from %s", url)

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        visits = response.json()
        if not isinstance(visits, list) or not visits:
            return False, [], "No visits found for this participant."
        return True, visits, ""
    except Exception as exc:
        logger.error("Error fetching visits: %s", exc, exc_info=True)
        return False, [], "Couldn't retrieve visits right now."


def download_media(message: Dict[str, Any]) -> Tuple[bool, Optional[bytes], str, str]:
    """Download media from WhatsApp message payload."""
    media_type = message.get("type")
    media_info = message.get(media_type, {}) if isinstance(message.get(media_type), dict) else {}
    media_url = media_info.get("link") or media_info.get("url")
    filename = media_info.get("filename") or f"upload.{media_info.get('mime_type', 'bin').split('/')[-1]}"
    mime_type = media_info.get("mime_type", "application/octet-stream")

    if not media_url:
        logger.error("Media URL missing in message: %s", message)
        return False, None, "", "No media URL provided."

    logger.info("Downloading media from %s", media_url)
    try:
        response = requests.get(media_url, timeout=20)
        response.raise_for_status()
        return True, response.content, filename, mime_type
    except Exception as exc:
        logger.error("Failed to download media: %s", exc, exc_info=True)
        return False, None, "", "Unable to download the file."


def upload_receipt(visit_id: str, file_bytes: bytes, filename: str, mime_type: str) -> Tuple[bool, str]:
    """Upload receipt file to backend."""
    url = f"{BACKEND_BASE_URL}/api/receipts/upload"
    files = {"file": (filename, io.BytesIO(file_bytes), mime_type)}
    data = {"participant_id": PARTICIPANT_ID, "visit_id": visit_id}

    logger.info("Uploading receipt to %s", url)
    try:
        response = requests.post(url, data=data, files=files, timeout=60)
        response.raise_for_status()
        result = response.json()
        msg = result if isinstance(result, str) else result.get("message", str(result))
        return True, msg
    except Exception as exc:
        logger.error("Error uploading receipt: %s", exc, exc_info=True)
        return False, "Problem uploading receipt. Please try again later."


# ------------------- State helpers -------------------
def reset_user_state(sender: str) -> None:
    user_states.pop(sender, None)


# ------------------- Flask Routes -------------------
@app.route("/webhook", methods=["POST"])
def webhook() -> Any:
    data = request.get_json(force=True, silent=True) or {}
    entry = (data.get("entry") or [{}])[0]
    changes = (entry.get("changes") or [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        logger.info("No messages found in webhook payload.")
        return "", 200

    message = messages[0]
    sender = message.get("from") or message.get("sender")
    if not sender:
        return "", 200

    logger.info("Processing message from %s", sender)

    state = user_states.get(sender)
    if state and state.get("awaiting_visit_selection"):
        handle_visit_selection(sender, message)
        return "", 200

    msg_type = message.get("type")

    if msg_type == "text":
        text = message.get("text", {}).get("body", "").strip()
        if not text:
            send_whatsapp_message(sender, "Please resend your message.")
            return "", 200
        success, reply = call_rag_endpoint(text)
        send_whatsapp_message(sender, reply)
        return "", 200

    if msg_type in {"image", "video", "document"}:
        handle_media_message(sender, message)
        return "", 200

    send_whatsapp_message(sender, "I can only process text or receipt files/images right now.")
    return "", 200


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


# ------------------- Media handlers -------------------
def handle_media_message(sender: str, message: Dict[str, Any]):
    success, file_bytes, filename, mime_type = download_media(message)
    if not success or file_bytes is None:
        send_whatsapp_message(sender, "Media processing failed.")
        return

    visits_success, visits, err = fetch_visits()
    if not visits_success:
        send_whatsapp_message(sender, err)
        return

    visit_lines = ["Choose the visit for this receipt by replying with its number:"]
    for i, visit in enumerate(visits, 1):
        visit_name = visit.get("name") or visit.get("title") or visit.get("id")
        visit_lines.append(f"{i}. {visit_name} (ID: {visit.get('id')})")
    visit_lines.append("Reply 'cancel' to stop.")

    user_states[sender] = {
        "awaiting_visit_selection": True,
        "file_bytes": file_bytes,
        "filename": filename,
        "mime_type": mime_type,
        "visits": visits,
    }

    send_whatsapp_message(sender, "\n".join(visit_lines))


def handle_visit_selection(sender: str, message: Dict[str, Any]):
    state = user_states.get(sender, {})
    body = message.get("text", {}).get("body", "").strip().lower()

    if not body:
        send_whatsapp_message(sender, "Please reply with a number or 'cancel'.")
        return
    if body in {"cancel", "stop", "exit"}:
        reset_user_state(sender)
        send_whatsapp_message(sender, "Receipt upload cancelled.")
        return

    try:
        sel = int(body)
    except ValueError:
        send_whatsapp_message(sender, "That's not a number.")
        return

    visits = state.get("visits", [])
    if sel < 1 or sel > len(visits):
        send_whatsapp_message(sender, "Invalid selection.")
        return

    visit = visits[sel - 1]
    visit_id = visit.get("id")
    if not visit_id:
        reset_user_state(sender)
        send_whatsapp_message(sender, "Selected visit missing ID.")
        return

    ok, msg = upload_receipt(
        visit_id,
        state.get("file_bytes", b""),
        state.get("filename", "receipt"),
        state.get("mime_type", "application/octet-stream"),
    )

    reset_user_state(sender)
    if ok:
        send_whatsapp_message(sender, f"Receipt uploaded successfully for visit {visit_id}.\nResult: {msg}")
    else:
        send_whatsapp_message(sender, msg)


# ------------------- Health check -------------------
@app.route("/health", methods=["GET"])
def health_check() -> Any:
    return jsonify({"status": "ok"}), 200


# ------------------- Entry -------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
