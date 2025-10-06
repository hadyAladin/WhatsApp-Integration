import hmac, hashlib, os
from flask import request, abort
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

APP_SECRET = os.getenv("APP_SECRET")
processed_messages = set()

def verify_signature(req):
    """Verify X-Hub-Signature-256 header from Meta."""
    signature = req.headers.get("X-Hub-Signature-256")
    if not signature:
        abort(403)

    payload = req.get_data()
    expected = hmac.new(
        APP_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest("sha256=" + expected, signature):
        abort(403)

def is_duplicate(message_id: str) -> bool:
    """Prevent duplicate message processing (idempotency)."""
    if message_id in processed_messages:
        return True
    processed_messages.add(message_id)
    return False
