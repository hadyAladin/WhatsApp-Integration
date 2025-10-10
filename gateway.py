import io
import logging
import os
from typing import Any, Dict, Optional
import requests
from flask import Flask, request
from dotenv import load_dotenv

# -------------------- Load environment --------------------
load_dotenv()

# -------------------- Logging setup --------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
logger = logging.getLogger("gateway")

app = Flask(__name__)

# -------------------- Config --------------------
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
PARTICIPANT_ID = os.getenv(
    "PARTICIPANT_ID", "57d611ee-39c5-4495-883e-9f4db257bc83"
)
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

TRIAL_ID_CACHE: Dict[str, Optional[str]] = {"value": None}


# ==========================================================
#                    WHATSAPP HELPERS
# ==========================================================
def send_whatsapp_message(to: str, text: str) -> None:
    """Send text message back to WhatsApp user (one clean reply)."""
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
        "text": {"body": text.strip()},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        logger.info(
            f"[WhatsApp] Sent to {to} | {resp.status_code} | {resp.text[:200]}"
        )
    except Exception as e:
        logger.error(f"[WhatsApp] Send failed: {e}", exc_info=True)


def get_media_url(media_id: str) -> Optional[str]:
    """Get a downloadable URL for a WhatsApp media ID."""
    try:
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        media_url = r.json().get("url")
        logger.info(f"[Media] Got media URL for {media_id}: {media_url}")
        return media_url
    except Exception as e:
        logger.error(f"[Media] Failed to get media URL: {e}", exc_info=True)
        return None


def download_media_file(media_url: str) -> Optional[bytes]:
    """Download file bytes from the WhatsApp media URL."""
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        r = requests.get(media_url, headers=headers, timeout=30)
        r.raise_for_status()
        logger.info(f"[Media] Downloaded file: {len(r.content)} bytes")
        return r.content
    except Exception as e:
        logger.error(f"[Media] Download failed: {e}", exc_info=True)
        return None


# ==========================================================
#                    BACKEND HELPERS
# ==========================================================
def fetch_trial_id() -> Optional[str]:
    """Fetch and cache participant trial_id."""
    if TRIAL_ID_CACHE["value"]:
        return TRIAL_ID_CACHE["value"]

    url = f"{BACKEND_BASE_URL}/api/participants/{PARTICIPANT_ID}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        trial_id = data.get("trial_id")
        TRIAL_ID_CACHE["value"] = trial_id
        logger.info(f"[Backend] Fetched trial_id: {trial_id}")
        return trial_id
    except Exception as e:
        logger.error(f"[Backend] Failed to fetch trial ID: {e}", exc_info=True)
        return None


def call_rag_endpoint(question: str) -> str:
    """Send text message to /api/rag/ask."""
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
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        answer = data.get("answer", "I couldn't find an answer for that.")
        return answer
    except Exception as e:
        logger.error(f"[Backend] RAG call failed: {e}", exc_info=True)
        return "There was a problem reaching the assistant."


def upload_receipt(file_bytes: bytes, filename: str, mime_type: str) -> str:
    """Upload receipt to backend (single clean request)."""
    url = f"{BACKEND_BASE_URL}/api/receipts/upload"
    files = {"file": (filename, io.BytesIO(file_bytes), mime_type)}
    data = {
        "participant_id": PARTICIPANT_ID,
        "source_channel": "whatsapp",
    }

    try:
        r = requests.post(url, data=data, files=files, timeout=120)
        logger.info(
            f"[Backend] Upload status={r.status_code}, body={r.text[:200]}"
        )
        r.raise_for_status()
        j = r.json()
        msg = j if isinstance(j, str) else j.get("message", str(j))
        return f"Receipt uploaded successfully. {msg}"
    except Exception as e:
        logger.error(f"[Backend] Upload failed: {e}", exc_info=True)
        return "Failed to upload receipt. Please try again later."


# ==========================================================
#                    FLASK WEBHOOK
# ==========================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    """Main webhook: routes WhatsApp messages -> backend."""
    try:
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

        logger.info(f"[Webhook] From {sender} type={msg_type}")

        # -------- Text message --------
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "").strip()
            if not text:
                send_whatsapp_message(sender, "Please send a valid message.")
                return "", 200

            reply = call_rag_endpoint(text)
            send_whatsapp_message(sender, reply)
            return "", 200

        # -------- Media upload (receipt) --------
        if msg_type in {"image", "document"}:
            media_info = msg.get(msg_type, {})
            media_id = media_info.get("id")
            mime_type = media_info.get("mime_type", "application/octet-stream")
            filename = media_info.get("filename") or f"receipt.{mime_type.split('/')[-1]}"

            if not media_id:
                send_whatsapp_message(sender, "Missing media ID.")
                return "", 200

            # Step 1: get direct URL
            media_url = get_media_url(media_id)
            if not media_url:
                send_whatsapp_message(sender, "Could not retrieve media URL.")
                return "", 200

            # Step 2: download
            file_bytes = download_media_file(media_url)
            if not file_bytes:
                send_whatsapp_message(sender, "Failed to download receipt file.")
                return "", 200

            # Step 3: upload to backend
            result = upload_receipt(file_bytes, filename, mime_type)
            send_whatsapp_message(sender, result)
            return "", 200

        # -------- Unsupported --------
        send_whatsapp_message(
            sender, "I can only process text messages or receipt uploads."
        )
        return "", 200

    except Exception as e:
        logger.error(f"[Webhook] Exception: {e}", exc_info=True)
        return "", 500


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Meta webhook verification."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return {"status": "ok"}, 200


# ==========================================================
#                    ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
