from flask import Blueprint, request
from queue import Queue
from .config import VERIFY_TOKEN, ALLOWED_SENDERS, logger
from .security import verify_signature, is_duplicate
from .whatsapp_service import send_message

bp = Blueprint("webhook", __name__)
tasks = Queue(maxsize=5000)


@bp.route("/webhook", methods=["GET"])
def verify():
    """Meta webhook verification."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


@bp.route("/webhook", methods=["POST"])
def handle():
    """Fast webhook acknowledgment + async queue."""
    raw_body = request.get_data()
    if not verify_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        logger.warning("Invalid signature.")
        return "Forbidden", 403

    data = request.get_json(force=True, silent=True) or {}
    msg = (
        ((data.get("entry") or [{}])[0].get("changes") or [{}])[0]
        .get("value", {})
        .get("messages", [{}])[0]
    )

    if not msg:
        return "", 200

    sender = msg.get("from")
    if not sender:
        return "", 200

    if ALLOWED_SENDERS and sender not in ALLOWED_SENDERS:
        logger.warning(f"[Webhook] Unauthorized sender {sender}")
        send_message(sender, "Your number is not registered.")
        return "", 200

    if is_duplicate(msg.get("id")):
        logger.info(f"[Webhook] Duplicate message ignored: {msg.get('id')}")
        return "", 200

    # Enqueue message and return immediately
    try:
        tasks.put_nowait(msg)
    except Exception:
        logger.warning("[Webhook] Queue full — dropping message")

    return "", 200
