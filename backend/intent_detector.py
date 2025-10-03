import os, json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY_PROJECT"))

KEYMAP = [
    ("begin", ["start", "begin", "new claim"]),
    ("upload", ["upload", "receipt", "invoice", "bill", "pdf", "image", "photo"]),
    ("confirm", ["confirm", "yes i confirm", "ok confirm"]),
    ("reset", ["reset", "cancel", "restart"]),
    ("visit_status", ["next visit", "visit status", "when is my visit", "visit date"]),
    ("participant_status", ["participation status", "am i active", "my status", "trial status"]),
]

def detect_intents(text: str) -> list[str]:
    """
    Very simple intent detector. Only match clear keywords.
    Returns [] if nothing matches → AI fallback will handle it.
    """
    text_lower = text.lower().strip()
    intents = []

    if text_lower in ("start claim", "begin claim", "start"):
        intents.append("begin")
    elif text_lower in ("upload", "uploaded", "i uploaded"):
        intents.append("upload")
    elif text_lower in ("done", "finish", "validate ok", "validated"):
        intents.append("validate_ok")
    elif text_lower in ("confirm visit", "confirm"):
        intents.append("confirm")
    elif text_lower in ("provide id", "id"):
        intents.append("provide_id")

    return intents
