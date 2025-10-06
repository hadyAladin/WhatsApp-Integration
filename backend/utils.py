import os, requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"

def send_text(to: str, message: str):
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,"96178895407"
        "type": "text",
        "text": {"body": message[:4096]}  # WA limit safeguard
    }
    print("=== send_text ===")
    print("URL:", WHATSAPP_API_URL)
    print("To:", to)
    print("Payload:", payload)
    resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
    print("Send status:", resp.status_code, resp.text)
