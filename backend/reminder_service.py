import logging, time
from datetime import datetime, timedelta, timezone
from backend.connect_supabase import supabase
from Whatsapp.utils import send_text

logger = logging.getLogger("reminder_service")

# -------- Helper: get phone --------
def get_phone(participant_id: str):
    resp = supabase.table("participants").select("phone_number").eq("id", participant_id).execute()
    return resp.data[0]["phone_number"] if resp.data else None

def already_scheduled(participant_id: str, template_type: str, visit_date: datetime) -> bool:
    """
    Check if a reminder of this type is already scheduled for the same participant and visit_date.
    """
    resp = (
        supabase.table("notifications")
        .select("id")
        .eq("participant_id", participant_id)
        .eq("template_type", template_type)
        .eq("visit_date", visit_date.isoformat())
        .execute()
    )
    return len(resp.data) > 0


def schedule_reminder(
    participant_id: str,
    message: str,
    delay_minutes: int = 60,
    template_type: str = "generic",
    visit_date: datetime | None = None,
    immediate: bool = False
):
    from datetime import datetime, timedelta, timezone

    scheduled_time = (
        datetime.now(timezone.utc) if immediate
        else datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    )

    # fallback: use scheduled_time as visit_date if not provided
    visit_date_val = visit_date or scheduled_time

    # simple dedupe check (query before insert)
    existing = supabase.table("notifications").select("id").eq("participant_id", participant_id)\
        .eq("template_type", template_type).eq("visit_date", visit_date_val.isoformat()).execute()

    if existing.data:
        logger.info(f"Skipped duplicate reminder for {participant_id}, type={template_type}, visit_date={visit_date_val}")
        return

    payload = {
        "participant_id": participant_id,
        "message": message,
        "scheduled_at": scheduled_time.isoformat(),
        "template_type": template_type,
        "status": "pending",
        "retry_count": 0,
        "visit_date": visit_date_val.isoformat(),
    }

    supabase.table("notifications").insert(payload).execute()
    logger.info(f"Inserted reminder for {participant_id}, type={template_type}, scheduled_at={scheduled_time}")


# -------- Core Sending --------
def fetch_due_reminders(limit=5):
    now = datetime.now(timezone.utc).isoformat()
    resp = (
        supabase.table("notifications")
        .select("*")
        .lte("scheduled_at", now)
        .eq("status", "pending")
        .order("scheduled_at", desc=False)
        .limit(limit)  # rate limit
        .execute()
    )
    return resp.data

def mark_as_status(reminder_id, status):
    supabase.table("notifications").update({
        "status": status,
        "last_attempt": datetime.now(timezone.utc).isoformat()
    }).eq("id", reminder_id).execute()

def send_due_reminders():
    reminders = fetch_due_reminders(limit=5)  # rate limiting: max 5 per cycle
    for r in reminders:
        try:
            phone = get_phone(r["participant_id"])
            if not phone:
                logger.error(f"No phone for participant {r['participant_id']}")
                mark_as_status(r["id"], "failed")
                continue

            send_text(phone, r["message"])
            mark_as_status(r["id"], "sent")
            logger.info(f"Sent reminder {r['id']} to {phone}")

        except Exception as e:
            logger.error(f"Failed reminder {r['id']}: {e}")
            # Retry policy: allow up to 3 attempts
            if r.get("retry_count", 0) < 3:
                supabase.table("notifications").update({
                    "retry_count": r.get("retry_count", 0) + 1,
                    "status": "pending"
                }).eq("id", r["id"]).execute()
            else:
                mark_as_status(r["id"], "failed")

# -------- Loop Runner --------
if __name__ == "__main__":
    logger.info("Reminder service started...")
    while True:
        send_due_reminders()
        time.sleep(60)  # check every 1 minute
