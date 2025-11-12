import time
import hmac
import hashlib
import threading
from typing import Optional, Dict
from collections import OrderedDict
from .config import WHATSAPP_APP_SECRET, DEDUP_TTL, logger

_seen_messages: OrderedDict[str, float] = OrderedDict()
MAX_CACHE = 5000 
_lock = threading.Lock()

def is_duplicate(message_id: Optional[str]) -> bool:
    """Detect and ignore repeated message IDs within DEDUP_TTL seconds."""
    if not message_id:
        return False
    now = time.time()
    with _lock:
        
        for k in list(_seen_messages):
            if now - _seen_messages[k] > DEDUP_TTL:
                _seen_messages.pop(k, None)
       
        while len(_seen_messages) > MAX_CACHE:
            _seen_messages.popitem(last=False)
        if message_id in _seen_messages:
            logger.info(f"[Security] Duplicate message {message_id} ignored.")
            return True
        _seen_messages[message_id] = now
    return False

def verify_signature(raw_body: bytes, header_signature: Optional[str]) -> bool:
    """Verify X-Hub-Signature-256 from Meta webhook."""
    if not WHATSAPP_APP_SECRET:
        logger.warning("WHATSAPP_APP_SECRET missing — signature verification disabled.")
        return True  

    if not header_signature or not header_signature.startswith("sha256="):
        logger.warning("[Security] Missing or malformed signature header.")
        return False

    try:
        provided = header_signature.split("sha256=", 1)[1].strip()
        expected = hmac.new(
            WHATSAPP_APP_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, provided):
            logger.warning("[Security] Signature mismatch detected — request rejected.")
            return False

        return True
    except Exception as e:
        logger.error(f"[Security] Signature verification error: {e}", exc_info=True)
        return False
