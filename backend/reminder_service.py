import logging
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
try:
    from utils import send_text
except ImportError:
    from backend.utils import send_text
try:
    from connect_supabase import supabase, log_receipt
except ModuleNotFoundError:
    from backend.connect_supabase import supabase, log_receipt


# ---------------- Logging ----------------
LOG_FILE = "reminder_service.log"
handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[handler, logging.StreamHandler()]
)
logger = logging.getLogger("reminder_service")

# ---------------- Helpers ----------------
def get_phone(participant_id: str):
    resp = supabase.table("participants").select("phone_number").eq("id", participant_id).execute()
    return resp.data[0]["phone_number"] if resp.data else None


def schedule_reminder(
    participant_id: str,
    message: str,
    delay_minutes: int = 60,
    template_type: str = "generic",
    visit_date: datetime | None = None,
    immediate: bool = False
):
    now = datetime.now(timezone.utc)
    scheduled_time = now if immediate else now + timedelta(minutes=delay_minutes)
    visit_date_val = visit_date or scheduled_time

    existing = (
        supabase.table("notifications")
        .select("id")
        .eq("participant_id", participant_id)
        .eq("template_type", template_type)
        .eq("visit_date", visit_date_val.isoformat())
        .execute()
    )
    if existing.data:
        logger.info(f"Duplicate reminder skipped: participant={participant_id}, type={template_type}")
        return

    supabase.table("notifications").insert({
        "participant_id": participant_id,
        "message": message,
        "scheduled_at": scheduled_time.isoformat(),
        "template_type": template_type,
        "status": "pending",
        "retry_count": 0,
        "visit_date": visit_date_val.isoformat(),
    }).execute()

    logger.info(f"Scheduled reminder for {participant_id} at {scheduled_time} UTC")


def fetch_due_reminders(limit=5):
    now = datetime.now(timezone.utc).isoformat()
    resp = (
        supabase.table("notifications")
        .select("*")
        .lte("scheduled_at", now)
        .eq("status", "pending")
        .order("scheduled_at", desc=False)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def mark_as(reminder_id, status, retry_count=None):
    payload = {"status": status, "last_attempt": datetime.now(timezone.utc).isoformat()}
    if retry_count is not None:
        payload["retry_count"] = retry_count
    supabase.table("notifications").update(payload).eq("id", reminder_id).execute()


# ---------------- Core Sending ----------------
def process_reminder(r):
    try:
        phone = get_phone(r["participant_id"])
        if not phone:
            logger.error(f"No phone for participant {r['participant_id']}")
            mark_as(r["id"], "failed")
            return

        send_text(phone, r["message"])
        mark_as(r["id"], "sent")
        logger.info(f"✅ Sent reminder {r['id']} to {phone}")

    except Exception as e:
        count = r.get("retry_count", 0) + 1
        if count <= 3:
            delay = 2 ** count  # exponential backoff minutes
            retry_time = datetime.now(timezone.utc) + timedelta(minutes=delay)
            supabase.table("notifications").update({
                "retry_count": count,
                "status": "pending",
                "scheduled_at": retry_time.isoformat(),
            }).eq("id", r["id"]).execute()
            logger.warning(f"⚠️ Retry {count}/3 scheduled for reminder {r['id']} after {delay} min ({e})")
        else:
            mark_as(r["id"], "failed")
            logger.error(f"❌ Failed reminder {r['id']} after 3 retries: {e}")


def send_due_reminders():
    reminders = fetch_due_reminders(limit=5)
    if not reminders:
        return
    logger.info(f"Processing {len(reminders)} due reminders...")
    for r in reminders:
        process_reminder(r)


# ---------------- Loop Runner ----------------
if __name__ == "__main__":
    logger.info("Reminder service started (runs locally or on VPS)...")
    while True:
        try:
            send_due_reminders()
        except Exception as e:
            logger.exception(f"Loop error: {e}")
        time.sleep(60)
