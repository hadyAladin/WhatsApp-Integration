import logging
import os
from flask import Flask, request
from dotenv import load_dotenv

# FSM manager (stateful)
from backend.fsm_manager import advance_state

# Intent detector (multi-intent version)
from backend.intent_detector import detect_intents

# AI fallback service
from Whatsapp.ai_service import get_ai_reply

# WhatsApp send function
from Whatsapp.utils import send_text

# Media handlers
from Whatsapp.media_service import handle_receipt, save_file
from backend.receipt_database import get_or_create_participant, get_or_create_claim

load_dotenv()

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

            # Case 1: Text message
            if msg_type == "text":
                body_text = msg_raw.get("text", {}).get("body", "")
                logger.info(f"Got text: {body_text}")

                intents = detect_intents(body_text)
                logger.info(f"Detected intents: {intents}")

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

            # Case 2: PDF document upload
            elif msg_type == "document":
                media_id = msg_raw["document"]["id"]

                try:
                    # Step 1: ensure participant exists
                    participant_id = get_or_create_participant(sender)

                    # Step 2: ensure participant has an active claim
                    claim_id = get_or_create_claim(participant_id)

                    # Step 3: handle receipt
                    confirmation = handle_receipt(media_id, claim_id, participant_id)
                    send_text(sender, message=f"✅ {confirmation}")
                    advance_state(sender, "claims_upload_workflow", "upload")

                except Exception as e:
                    send_text(sender, message=f"❌ Error handling receipt: {e}")

            # Case 3: Image upload
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
