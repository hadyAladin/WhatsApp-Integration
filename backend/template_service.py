# Whatsapp/template_service.py
import os
import requests

from dotenv import load_dotenv, find_dotenv

# Load environment variables from .env
load_dotenv(find_dotenv())

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

if not ACCESS_TOKEN:
    raise ValueError("ACCESS_TOKEN not found. Check your .env file.")

def send_visit_reminder(to: str, patient_name: str, visit_code: str, date_str: str, checklist: str):
    """
    Send WhatsApp visit reminder template.
    to          = recipient phone number (without +)
    patient_name = e.g. "Hady Aladdin"
    visit_code   = e.g. "Visit 1"
    date_str     = e.g. "Mon 7 Oct 2025, 10:00"
    checklist    = e.g. "ID, receipts, meds"
    """

    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    body = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": "visit_reminder_v1",   # must match exactly
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": patient_name},
                        {"type": "text", "text": visit_code},
                        {"type": "text", "text": date_str},
                        {"type": "text", "text": checklist}
                    ]
                }
            ]
        }
    }

    resp = requests.post(url, headers=headers, json=body)
    print("Template send response:", resp.status_code, resp.text)
    return resp.json()
