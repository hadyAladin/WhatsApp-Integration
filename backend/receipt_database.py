import os
from supabase import Client, create_client
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

sb: Client = create_client(supabase_url, supabase_key)

def get_or_create_participant(phone: str):
    """
    Look up participant by phone. If not found, create a new one.
    """


    resp = sb.table("participants").select("id").eq("phone_number", phone).execute()
    if resp.data:
        return resp.data[0]["id"]

    # Create new participant if not found
    payload = {"phone_number": phone, "status": "active"}
    new = sb.table("participants").insert(payload).execute()
    return new.data[0]["id"]

def get_or_create_claim(participant_id: str):
    """
    Get an open claim for the participant, or create a new one.
    """
    resp = (
        sb.table("claims")
        .select("id")
        .eq("participant_id", participant_id)
        .eq("status", "open")
        .execute()
    )
    if resp.data:
        return resp.data[0]["id"]

    # If no open claim, create a new one
    payload = {"participant_id": participant_id, "status": "open"}
    new = sb.table("claims").insert(payload).execute()
    return new.data[0]["id"]
