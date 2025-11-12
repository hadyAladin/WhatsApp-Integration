import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .config import (
    WHATSAPP_TOKEN,
    PHONE_NUMBER_ID,
    ALLOWED_MIMES,
    MAX_MEDIA_SIZE,
    logger,
)

# Persistent session for WhatsApp
_session = requests.Session()
_retry = Retry(total=3, backoff_factor=0.2, status_forcelist=[429, 500, 502, 503, 504])
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=100, max_retries=_retry)
_session.mount("https://", _adapter)


def send_message(to: str, text: str):
    """Send WhatsApp text quickly via pooled connection."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing WhatsApp credentials")
        return
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text.strip()},
    }
    try:
        r = _session.post(url, headers=headers, json=payload, timeout=8)
        logger.info(f"[WhatsApp] → {to} ({r.status_code}) {r.text[:150]}")
    except Exception as e:
        logger.error(f"[WhatsApp] send failed: {e}", exc_info=True)


def get_media_url(media_id: str) -> str | None:
    try:
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        r = _session.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get("url")
    except Exception as e:
        logger.error(f"[Media] Failed URL fetch: {e}", exc_info=True)
        return None


def download_media(url: str) -> bytes | None:
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        with _session.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            mime = r.headers.get("Content-Type", "").split(";")[0]
            if mime not in ALLOWED_MIMES:
                logger.warning(f"[Media] Blocked type {mime}")
                return None
            data = b"".join(r.iter_content(8192))
            if len(data) > MAX_MEDIA_SIZE:
                logger.warning("[Media] File too large")
                return None
            logger.info(f"[Media] Downloaded {len(data)} bytes ({mime})")
            return data
    except Exception as e:
        logger.error(f"[Media] Download failed: {e}", exc_info=True)
        return None
