import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .config import BACKEND_BASE_URL, BACKEND_SERVICE_TOKEN, PARTICIPANT_ID, logger

# persistent session for connection pooling
_session = requests.Session()
# Avoid picking up system proxy settings (which can block localhost calls under systemd)
_session.trust_env = False
_retry = Retry(total=3, backoff_factor=0.2, status_forcelist=[429, 500, 502, 503, 504])
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=100, max_retries=_retry)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def headers():
    return {
        "Authorization": f"Bearer {BACKEND_SERVICE_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_trial_id() -> str | None:
    try:
        r = _session.get(f"{BACKEND_BASE_URL}/api/participants/{PARTICIPANT_ID}", headers=headers(), timeout=10)
        r.raise_for_status()
        trial_id = r.json().get("trial_id")
        logger.info(f"[Backend] trial_id={trial_id}")
        return trial_id
    except Exception as e:
        logger.error(f"[Backend] trial fetch failed: {e}", exc_info=True)
        return None


def send_chat(question: str) -> str:
    payload = {
        "participant_id": PARTICIPANT_ID,
        "question": question,
        "visit_type_code": "",
        "channel": "whatsapp",
    }
    url = f"{BACKEND_BASE_URL}/participants/chat/send"
    try:
        logger.info(f"[Backend] → POST {url}")
        r = _session.post(url, json=payload, headers=headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("answer") or "No answer returned."
    except Exception as e:
        logger.error(f"[Backend] chat failed: {e}", exc_info=True)
        return "Assistant unavailable."
