import os
import requests
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

# Base URL of your brother's RAG backend
RAG_BASE_URL = os.getenv("RAG_BASE_URL", "http://localhost:8000")

def rag_answer(question: str, trial_id="default", participant_id=None):
    url = f"{RAG_BASE_URL}/api/rag/ask"
    body = {
        "trial_id": trial_id,
        "question": question,
        "participant_id": participant_id,
        "channel": "whatsapp"
    }

    try:
        resp = requests.post(url, json=body)
        resp.raise_for_status()
        return resp.json().get("answer", "No answer found.")
    except Exception as e:
        return f"RAG service error: {e}"
