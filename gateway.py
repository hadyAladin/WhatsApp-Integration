import io
import logging
import os
from typing import Any, Dict, Optional

import requests
from flask import Flask, request
from dotenv import load_dotenv

# ==========================================================
#                  ENV + CONFIG
# ==========================================================
load_dotenv()

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
PARTICIPANT_ID = os.getenv("PARTICIPANT_ID", "57d611ee-39c5-4495-883e-9f4db257bc83")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

TRIAL_ID_CACHE: Dict[str, Optional[str]] = {"value": None}
pending_receipts: Dict[str, Dict[str, Any]] = {}

# ==========================================================
#                  LOGGING
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
logger = logging.getLogger("gateway")

app = Flask(__name__)

# ==========================================================
#                  WHATSAPP HELPERS
# ==========================================================
def send_whatsapp_message(to: str, text: str) -> None:
    """Send WhatsApp text message."""
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
        "text": {"body": text.strip()},
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        logger.info(f"[WhatsApp] Sent to {to} | {r.status_code} | {r.text[:200]}")
    except Exception as e:
        logger.error(f"[WhatsApp] Send failed: {e}", exc_info=True)


def get_media_url(media_id: str) -> Optional[str]:
    """Retrieve the direct media URL."""
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
    """Download media bytes."""
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
#                  BACKEND HELPERS
# ==========================================================
def fetch_trial_id() -> Optional[str]:
    """Fetch participant trial_id (cached)."""
    if TRIAL_ID_CACHE["value"]:
        return TRIAL_ID_CACHE["value"]

    url = f"{BACKEND_BASE_URL}/api/participants/{PARTICIPANT_ID}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        trial_id = r.json().get("trial_id")
        TRIAL_ID_CACHE["value"] = trial_id
        logger.info(f"[Backend] trial_id={trial_id}")
        return trial_id
    except Exception as e:
        logger.error(f"[Backend] Trial fetch failed: {e}", exc_info=True)
        return None


def call_rag_endpoint(question: str) -> str:
    """Send text query to backend RAG endpoint."""
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
        r = requests.post(f"{BACKEND_BASE_URL}/api/rag/ask", json=payload, timeout=60)
        r.raise_for_status()
        return r.json().get("answer", "I couldn't find an answer for that.")
    except Exception as e:
        logger.error(f"[Backend] RAG call failed: {e}", exc_info=True)
        return "There was a problem reaching the assistant."


def get_participant_visits() -> list:
    """Fetch participant visit schedule."""
    try:
        url = f"{BACKEND_BASE_URL}/api/participants/{PARTICIPANT_ID}/visits"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"[Backend] Visit fetch failed: {e}", exc_info=True)
        return []


def upload_receipt_with_visit(sender: str, visit_id: str) -> str:
    """Upload stored receipt once visit is chosen."""
    receipt = pending_receipts.pop(sender, None)
    if not receipt:
        return "No pending receipt found."

    url = f"{BACKEND_BASE_URL}/api/receipts/upload"
    files = {
        "file": (receipt["filename"], io.BytesIO(receipt["file_bytes"]), receipt["mime_type"])
    }
    data = {
        "participant_id": PARTICIPANT_ID,
        "visit_id": visit_id,
        "source_channel": "whatsapp",
    }

    try:
        r = requests.post(url, data=data, files=files, timeout=120)
        logger.info(f"[Backend] Upload status={r.status_code}, body={r.text[:200]}")
        r.raise_for_status()
        return "Receipt uploaded successfully."
    except Exception as e:
        logger.error(f"[Backend] Upload failed: {e}", exc_info=True)
        return "Failed to upload receipt. Please try again later."


# ==========================================================
#                  WEBHOOK
# ==========================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    """Main webhook."""
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
        logger.info(f"[Webhook] From {sender} type={msg_type}")

        # --- TEXT MESSAGE ---
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "").strip()
            if not text:
                send_whatsapp_message(sender, "Please send a valid message.")
                return "", 200

            # If pending receipt, treat as visit selection
            if sender in pending_receipts:
                visits = get_participant_visits()
                try:
                    index = int(text) - 1
                    visit_id = visits[index]["id"]
                    msg_out = upload_receipt_with_visit(sender, visit_id)
                    send_whatsapp_message(sender, msg_out)
                except Exception:
                    send_whatsapp_message(sender, "Invalid selection. Please try again.")
                return "", 200

            # Otherwise treat as normal chat
            reply = call_rag_endpoint(text)
            send_whatsapp_message(sender, reply)
            return "", 200

        # --- MEDIA MESSAGE (RECEIPT) ---
        if msg_type in {"image", "document"}:
            media_info = msg.get(msg_type, {})
            media_id = media_info.get("id")
            mime_type = media_info.get("mime_type", "application/octet-stream")
            filename = media_info.get("filename") or f"receipt.{mime_type.split('/')[-1]}"

            if not media_id:
                send_whatsapp_message(sender, "Missing media ID.")
                return "", 200

            media_url = get_media_url(media_id)
            if not media_url:
                send_whatsapp_message(sender, "Could not retrieve media URL.")
                return "", 200

            file_bytes = download_media_file(media_url)
            if not file_bytes:
                send_whatsapp_message(sender, "Failed to download receipt file.")
                return "", 200

            pending_receipts[sender] = {
                "file_bytes": file_bytes,
                "filename": filename,
                "mime_type": mime_type,
            }

            visits = get_participant_visits()
            if not visits:
                send_whatsapp_message(sender, "No scheduled visits found.")
                return "", 200

            options = "\n".join(
                [f"{i+1}. {v['name']} ({v.get('scheduled_date','')})" for i, v in enumerate(visits)]
            )
            send_whatsapp_message(
                sender,
                "Select the visit this receipt belongs to:\n" + options,
            )
            return "", 200

        # --- OTHER TYPES ---
        send_whatsapp_message(sender, "I can only process text messages or receipts.")
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
#                  ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
