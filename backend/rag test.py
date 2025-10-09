import os
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

RAG_BASE_URL = os.getenv("RAG_BASE_URL", "http://localhost:8000")

def test_rag(question="what is my next visit?", trial_id="default", participant_id=None):
    url = f"{RAG_BASE_URL}/api/rag/ask"
    body = {
        "trial_id": trial_id,
        "question": question,
        "participant_id": participant_id,
        "channel": "whatsapp",
    }

    print(f"→ Sending to: {url}")
    print(f"→ Payload: {body}")

    try:
        resp = requests.post(url, json=body)
        print(f"← Status: {resp.status_code}")
        print(f"← Response: {resp.text}")
    except Exception as e:
        print(f"RAG service error: {e}")

if __name__ == "__main__":
    test_rag()
