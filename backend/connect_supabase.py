import os
from supabase import create_client
from dotenv import load_dotenv, find_dotenv

# load .env
load_dotenv(find_dotenv(), override=True)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(url, key)
