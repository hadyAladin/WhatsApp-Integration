import os, requests

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

def send_text(to, body):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    resp = requests.post(url, headers=headers, json=payload)
    print("WhatsApp reply status:", resp.status_code, resp.text)

def download_media(media_id):
    url = f"https://graph.facebook.com/v20.0/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    media_info = requests.get(url, headers=headers).json()
    media_url = media_info["url"]
    return requests.get(media_url, headers=headers).content
