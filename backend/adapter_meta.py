import os, requests

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

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


def download_media(media_id: str) -> bytes:
    """
    Download media from WhatsApp using the media_id.
    Returns raw bytes.
    """
    url = f"{GRAPH_API_BASE}/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    media_url = resp.json().get("url")

    # second request to fetch actual file
    resp = requests.get(media_url, headers=headers)
    resp.raise_for_status()
    return resp.content