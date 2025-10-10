import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, request

# Basic logging configuration
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")
PARTICIPANT_ID = "57d611ee-39c5-4495-883e-9f4db257bc83"
TRIAL_ID_CACHE: Dict[str, Optional[str]] = {"value": None}

# In-memory per-user states
user_states: Dict[str, Dict[str, Any]] = {}


class GatewayError(Exception):
    """Custom exception for gateway errors."""


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
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to fetch trial ID: %s", exc, exc_info=True)
        return None


def call_rag_endpoint(question: str) -> Tuple[bool, str]:
    """Send text to the RAG endpoint and return a tuple of (success, response)."""
    trial_id = fetch_trial_id()
    if not trial_id:
        return False, "Unable to determine trial ID at the moment. Please try again later."

    payload = {
        "trial_id": trial_id,
        "participant_id": PARTICIPANT_ID,
        "question": question,
        "channel": "whatsapp",
    }

    url = f"{BACKEND_BASE_URL}/api/rag/ask"
    logger.info("Routing text message to %s", url)

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        answer = data.get("answer", "I couldn't find an answer for that.")
        return True, answer
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Error calling RAG endpoint: %s", exc, exc_info=True)
        return False, "Sorry, there was a problem reaching the assistant. Please try again later."


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
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Error fetching visits: %s", exc, exc_info=True)
        return False, [], "We couldn't retrieve the visit list right now. Please try again later."


def download_media(message: Dict[str, Any]) -> Tuple[bool, Optional[bytes], str, str]:
    """Download media from the WhatsApp payload."""
    media_type = message.get("type")
    media_info = message.get(media_type, {}) if isinstance(message.get(media_type), dict) else {}
    media_url = media_info.get("link") or media_info.get("url") or message.get("media_url")
    filename = media_info.get("filename") or f"upload.{media_info.get('mime_type', 'bin').split('/')[-1]}"
    mime_type = media_info.get("mime_type", "application/octet-stream")

    if not media_url:
        logger.error("Media URL missing in message: %s", message)
        return False, None, "", "Media URL not provided in the message."

    logger.info("Downloading media from %s", media_url)
    try:
        response = requests.get(media_url, timeout=20)
        response.raise_for_status()
        return True, response.content, filename, mime_type
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to download media: %s", exc, exc_info=True)
        return False, None, "", "Unable to download the provided media."


def upload_receipt(visit_id: str, file_bytes: bytes, filename: str, mime_type: str) -> Tuple[bool, str]:
    """Upload the receipt file to the backend."""
    url = f"{BACKEND_BASE_URL}/api/receipts/upload"
    files = {
        "file": (filename, io.BytesIO(file_bytes), mime_type),
    }
    data = {
        "participant_id": PARTICIPANT_ID,
        "visit_id": visit_id,
    }

    logger.info("Uploading receipt to %s", url)
    try:
        response = requests.post(url, data=data, files=files, timeout=60)
        response.raise_for_status()
        result = response.json()
        return True, result if isinstance(result, str) else result.get("message") or str(result)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Error uploading receipt: %s", exc, exc_info=True)
        return False, "There was a problem uploading your receipt. Please try again later."


def reset_user_state(sender: str) -> None:
    if sender in user_states:
        user_states.pop(sender, None)


def build_whatsapp_response(text: str) -> Any:
    """Construct a WhatsApp-compatible response payload."""
    return {"messages": [{"type": "text", "text": {"body": text}}]}


@app.route("/webhook", methods=["POST"])
def webhook() -> Any:
    data = request.get_json(force=True, silent=True) or {}
    logger.debug("Received webhook payload: %s", data)

    entry = (data.get("entry") or [{}])[0]
    changes = (entry.get("changes") or [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        logger.info("No messages found in webhook payload.")
        return jsonify(build_whatsapp_response("")), 200

    message = messages[0]
    sender = message.get("from") or message.get("sender")

    if not sender:
        logger.error("Sender information missing from message: %s", message)
        return jsonify(build_whatsapp_response("Unable to identify the sender.")), 200

    logger.info("Processing message from %s", sender)

    # Check if we're awaiting a visit selection for this user
    state = user_states.get(sender)
    if state and state.get("awaiting_visit_selection"):
        return handle_visit_selection(sender, message)

    msg_type = message.get("type")
    if msg_type == "text":
        text = message.get("text", {}).get("body", "").strip()
        if not text:
            return jsonify(build_whatsapp_response("I didn't catch that. Could you please resend your message?")), 200
        success, response_text = call_rag_endpoint(text)
        return jsonify(build_whatsapp_response(response_text)), 200 if success else 500

    if msg_type in {"image", "video", "document", "audio", "sticker"}:
        return handle_media_message(sender, message)

    logger.warning("Unsupported message type: %s", msg_type)
    return jsonify(build_whatsapp_response("Sorry, I can only process text or receipt files/images right now.")), 200


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    VERIFY_TOKEN = "12345"  

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


def handle_media_message(sender: str, message: Dict[str, Any]):
    success, file_bytes, filename, mime_type_or_error = download_media(message)
    if not success or file_bytes is None:
        response_text = mime_type_or_error or "Unable to process the provided media."
        return jsonify(build_whatsapp_response(response_text)), 500

    visits_success, visits, error_text = fetch_visits()
    if not visits_success:
        return jsonify(build_whatsapp_response(error_text)), 500

    # Build the visit selection message
    visit_lines = ["Please choose the visit for this receipt by replying with the number:"]
    for idx, visit in enumerate(visits, start=1):
        visit_name = visit.get("name") or visit.get("title") or visit.get("id")
        visit_lines.append(f"{idx}. {visit_name} (ID: {visit.get('id')})")
    visit_lines.append("Reply 'cancel' to abort this upload.")

    # Save state
    user_states[sender] = {
        "awaiting_visit_selection": True,
        "file_bytes": file_bytes,
        "filename": filename,
        "mime_type": mime_type_or_error,
        "visits": visits,
    }

    logger.info("Awaiting visit selection from %s", sender)
    return jsonify(build_whatsapp_response("\n".join(visit_lines))), 200


def handle_visit_selection(sender: str, message: Dict[str, Any]):
    state = user_states.get(sender, {})
    text_body = message.get("text", {}).get("body", "").strip() if message.get("type") == "text" else ""

    if not text_body:
        return jsonify(build_whatsapp_response("Please reply with the number of the visit you'd like to use, or 'cancel' to abort.")), 200

    if text_body.lower() in {"cancel", "stop", "exit"}:
        reset_user_state(sender)
        return jsonify(build_whatsapp_response("Receipt upload cancelled.")), 200

    try:
        selection = int(text_body)
    except ValueError:
        return jsonify(build_whatsapp_response("That's not a valid number. Please reply with one of the visit numbers.")), 200

    visits = state.get("visits", [])
    if selection < 1 or selection > len(visits):
        return jsonify(build_whatsapp_response("That number doesn't match any visit. Please try again.")), 200

    visit = visits[selection - 1]
    visit_id = visit.get("id")
    if not visit_id:
        reset_user_state(sender)
        return jsonify(build_whatsapp_response("The selected visit is missing an ID. Please try uploading again.")), 500

    upload_success, upload_message = upload_receipt(
        visit_id,
        state.get("file_bytes", b""),
        state.get("filename", "receipt"),
        state.get("mime_type", "application/octet-stream"),
    )

    reset_user_state(sender)

    if upload_success:
        response_text = f"Receipt uploaded successfully for visit {visit_id}. Result: {upload_message}"
        return jsonify(build_whatsapp_response(response_text)), 200

    return jsonify(build_whatsapp_response(upload_message)), 500


@app.route("/health", methods=["GET"])
def health_check() -> Any:
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

