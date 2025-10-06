from supabase import create_client, Client
import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def log_receipt(claim_id: str, participant_id: str, file_path: str):
    payload = {"claim_id": claim_id, "participant_id": participant_id, "file_path": file_path}
    supabase.table("claim_receipts").insert(payload).execute()
