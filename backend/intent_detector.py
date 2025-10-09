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

def detect_intents(text: str):
    text_low = text.lower()
    intents = []

    # existing logic...
    if "visit" in text_low and "date" in text_low:
        intents.append("visit_inquiry")

    # add your other existing detections here...
    if "upload" in text_low:
        intents.append("upload")

    return intents

