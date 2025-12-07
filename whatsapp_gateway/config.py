import os
import logging
from dotenv import load_dotenv, find_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
logger = logging.getLogger("gateway")

load_dotenv(find_dotenv(),override=True)

def get_secret(key: str) -> str | None:
    """Load a secret from environment or Docker secret file."""
    val = os.getenv(key)
    if not val:
        logger.error("Failed to retreive secrets from .env.")
    return val

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
PARTICIPANT_ID = os.getenv("PARTICIPANT_ID", "418fb3c2-f745-4976-aeea-48624b5ea1f3")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "12345")
WHATSAPP_TOKEN = get_secret("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = get_secret("WHATSAPP_APP_SECRET")
BACKEND_SERVICE_TOKEN = get_secret("BACKEND_SERVICE_TOKEN")

MAX_MEDIA_SIZE = int(os.getenv("MAX_MEDIA_SIZE", 5 * 1024 * 1024))  # 5 MB default
ALLOWED_MIMES = set(os.getenv("ALLOWED_MIMES", "application/pdf,image/jpeg,image/png").split(","))
ALLOWED_SENDERS = set(filter(None, os.getenv("ALLOWED_SENDERS", "").split(",")))
DEDUP_TTL = int(os.getenv("DEDUP_TTL", 60))  # seconds


if not VERIFY_TOKEN or VERIFY_TOKEN == "12345":
    logger.error("Weak or missing VERIFY_TOKEN detected — replace immediately.")
if not BACKEND_BASE_URL.lower().startswith("https://"):
    logger.warning("BACKEND_BASE_URL is not HTTPS — use HTTPS in production.")
