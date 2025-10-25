from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime
import os

# Load environment variables from .env
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = "model-bucket"

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ──────────────── Upload / Download Model ──────────────── #
def upload_to_supabase(file_path: str) -> bool:
    """Upload a model file to Supabase Storage. Returns True on success."""
    try:
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            supabase.storage.from_(BUCKET_NAME).upload(file_name, f, {"x-upsert": "true"})
        print(f"[✔] Model '{file_name}' uploaded to Supabase storage.")
        return True
    except Exception as e:
        print(f"[✖] Failed to upload to Supabase: {e}")
        return False

def download_model_from_supabase(file_path: str) -> bool:
    """Download a model from Supabase Storage to the given local path. Returns True on success."""
    try:
        file_name = os.path.basename(file_path)
        data = supabase.storage.from_(BUCKET_NAME).download(file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)
        print(f"[✔] Model '{file_name}' downloaded from Supabase storage.")
        return True
    except Exception as e:
        print(f"[✖] Failed to download from Supabase: {e}")
        return False

# ──────────────── Chat Logs (user ↔ bot) ──────────────── #
def save_chat_to_supabase(user_input: str, response_text: str, user_id: str | None = None) -> bool:
    """
    Save a chat entry to the 'chat_logs' table.
    user_id is optional; if not provided, it will be stored as NULL in the DB.
    Returns True on success.
    """
    try:
        data = {
            "user_id": user_id,
            "input": user_input,
            "output": response_text,
            "timestamp": datetime.utcnow().isoformat()
        }
        supabase.table("chat_logs").insert(data).execute()
        print("[✔] Chat saved to Supabase.")
        return True
    except Exception as e:
        print(f"[✖] Failed to save chat to Supabase: {e}")
        return False

def get_memory(user_id: str):
    """
    Retrieve chat history for a given user_id from the 'chat_logs' table.
    Returns a list of dicts: [{ "user": "...", "bot": "..." }, ...]
    """
    if not user_id:
        return []

    try:
        response = (
            supabase.table("chat_logs")
            .select("input, output")
            .eq("user_id", user_id)
            .order("timestamp", desc=False)
            .execute()
        )
        chat_data = response.data or []
        return [{"user": item.get("input"), "bot": item.get("output")} for item in chat_data]
    except Exception as e:
        print(f"[✖] Failed to fetch chat history from Supabase: {e}")
        return []

# Expose a named constant for other modules importing this file
SUPABASE = supabase
