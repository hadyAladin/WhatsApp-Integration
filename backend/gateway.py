import logging
import os
from flask import Flask, request
from dotenv import load_dotenv, find_dotenv
from supabase import create_client, Client

from backend.connect_supabase import supabase
# FSM manager (stateful)
from backend.fsm_manager import advance_state

# Intent detector (multi-intent version)
from backend.intent_detector import detect_intents

# AI fallback service
from .ai_service import get_ai_reply

# WhatsApp send function
from .utils import send_text
from .media_service import handle_receipt, save_file


from backend.receipt_database import get_or_create_participant, get_or_create_claim

load_dotenv(find_dotenv())

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")


@app.route("/webhook", methods=["GET"])
def verify():
    """
    Verification endpoint for Meta (used when you first set up the webhook).
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

def get_participant_by_phone(phone: str):
    """Retrieve participant record using their WhatsApp number."""
    res = supabase.table("participants").select("*").eq("phone_number", phone).execute()
    return res.data[0] if res.data else None



@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("Raw incoming:", data)
    logger.info(f"Incoming: {data}")

    try:
        change = data["entry"][0]["changes"][0]["value"]

        if "messages" in change:
            msg_raw = change["messages"][0]
            sender = msg_raw["from"]
            msg_type = msg_raw["type"]

            # 🧩 Case 1: Text message
            if msg_type == "text":
                body_text = msg_raw.get("text", {}).get("body", "")
                logger.info(f"Got text: {body_text}")

                # ----- participant lookup -----
                participant = get_participant_by_phone(sender)
                next_visit = None
                if participant:
                    next_visit = participant.get("next_visit_at")

                # ----- intent detection -----
                intents = detect_intents(body_text)
                logger.info(f"Detected intents: {intents}")

                # --- new intent: user asks about visit date ---
                if "visit_inquiry" in intents or "visit_date" in body_text.lower():
                    if participant and next_visit:
                        send_text(sender, f"📅 Your next visit is scheduled on {next_visit[:16]} UTC.")
                    elif participant and not next_visit:
                        send_text(sender, "❌ You’re registered but have no upcoming visit scheduled.")
                    else:
                        send_text(sender, "👋 I couldn’t find your record yet. Please upload your visit schedule PDF so I can register you in the system.")
                    return "OK", 200

                # ----- workflow logic -----
                handled = False
                for intent in intents:
                    if intent in ("begin", "upload", "validate_ok", "finish", "reset"):
                        workflow = "claims_upload_workflow"
                    elif intent == "confirm":
                        workflow = "visit_prep_workflow"
                    elif intent == "provide_id":
                        workflow = "run_workflow"
                    else:
                        workflow = None

                    if workflow:
                        logger.info(f"Advancing state: {sender} {workflow} {intent}")
                        new_state = advance_state(sender, workflow, intent)

                        reply_map = {
                            "WAITING_FOR_RECEIPT": "Please upload your receipt.",
                            "RECEIPT_RECEIVED": "Receipt received, validating now...",
                            "VALIDATED": "Your claim was validated.",
                            "DONE": "Workflow complete."
                        }
                        reply = reply_map.get(new_state, f"Processed intent {intent}")
                        send_text(sender, reply)
                        handled = True

                if not handled:
                    reply = get_ai_reply(body_text)
                    send_text(sender, reply)

            # 🧩 Case 2: PDF document upload
            elif msg_type == "document":
                media_id = msg_raw["document"]["id"]

                try:
                    participant_id = get_or_create_participant(sender)
                    claim_id = get_or_create_claim(participant_id)

                    confirmation = handle_receipt(media_id, claim_id, participant_id)
                    send_text(sender, message=f"✅ {confirmation}")
                    advance_state(sender, "claims_upload_workflow", "upload")

                except Exception as e:
                    send_text(sender, message=f"❌ Error handling receipt: {e}")

            # 🧩 Case 3: Image upload
            elif msg_type == "image":
                media_id = msg_raw["image"]["id"]
                path = save_file(media_id, "jpg")
                send_text(sender, f"🖼️ Image received and saved at {path}. OCR will be added later.")
                advance_state(sender, "claims_upload_workflow", "upload")

        elif "statuses" in change:
            status = change["statuses"][0]["status"]
            logger.info(f"Status update: {status}")

    except Exception as e:
        logger.error(f"Webhook error: {e}")

    return "OK", 200


if __name__ == "__main__":
    app.run(port=8000, debug=True)
