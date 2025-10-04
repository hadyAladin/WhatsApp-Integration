import os
from supabase import create_client
from dotenv import load_dotenv, find_dotenv

# load .env
load_dotenv(find_dotenv(), override=True)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(url, key)

from backend.connect_supabase import supabase

def log_receipt(claim_id: str, participant_id: str, file_path: str):
    """
    Save uploaded receipt reference into claim_receipts.
    Only stores file_path (not signed URL).
    """
    payload = {
        "claim_id": claim_id,
        "participant_id": participant_id,
        "file_path": file_path,
    }
    resp = supabase.table("claim_receipts").insert(payload).execute()
    return resp.data
