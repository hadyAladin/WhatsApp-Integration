import logging
import os
from flask import Flask, request
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

# FSM manager (stateful)
from backend.fsm_manager import advance_state

# Intent detector (multi-intent version)
from backend.intent_detector import detect_intents

# WhatsApp send function
from Whatsapp.utils import send_text

# AI fallback service
from Whatsapp.ai_service import get_ai_reply  # make sure ai_service.py defines this


app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")


@app.route("/webhook", methods=["GET"])
def verify():
    """
    Verification endpoint for Meta (used when you first set up the webhook).
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

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
            sender = msg_raw["from"]  # WhatsApp number
            body_text = msg_raw.get("text", {}).get("body", "")
            print("Got body:", body_text)

            # Step 1: detect intents
            intents = detect_intents(body_text)
            print("Detected intents:", intents)

            reply_map = {
                "WAITING_FOR_RECEIPT": "Please upload your receipt.",
                "RECEIPT_RECEIVED": "Receipt received, validating now...",
                "VALIDATED": "Your claim was validated.",
                "DONE": "Workflow complete."
            }

            if intents:
                # FSM routing
                for intent in intents:
                    if intent in ("begin", "upload", "validate_ok", "finish", "reset"):
                        workflow = "claims_upload_workflow"
                    elif intent == "confirm":
                        workflow = "visit_prep_workflow"
                    elif intent == "provide_id":
                        workflow = "run_workflow"
                    else:
                        workflow = "claims_upload_workflow"

                    print(f"Advancing state: {sender} {workflow} {intent}")
                    new_state = advance_state(sender, workflow, intent)
                    reply = reply_map.get(new_state, f"Processed intent {intent}")
                    print(f"Reply: {reply}")
                    send_text(sender, reply)

            else:
                # Step 2: Fallback to OpenAI
                ai_reply = get_ai_reply(body_text)
                print(f"AI reply: {ai_reply}")
                send_text(sender, ai_reply)

        elif "statuses" in change:
            status = change["statuses"][0]["status"]
            logger.info(f"Status update: {status}")

    except Exception as e:
        logger.error(f"Webhook error: {e}")

    return "OK", 200


if __name__ == "__main__":
    app.run(port=8000, debug=True)
