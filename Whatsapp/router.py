from .intent import classify_intents
from .workflow import run_workflow
from .rag_service import rag_answer   

def route_message(msg, trial_id="default", participant_id=None):
    sender = msg["from"]
    msg_type = msg["type"]

    if msg_type != "text":
        return "Sorry, I can only handle text right now."

    user_text = msg["text"]["body"]

    # Step 1: classify
    intent, rag_resp = classify_intents(user_text, trial_id=trial_id, participant_id=participant_id)

    # Step 2: direct execution
    if rag_resp:
        # this means low-confidence → RAG already answered
        return rag_resp

    if intent == "qa":
        # Instead of local reply, call RAG
        return rag_answer(user_text, trial_id=trial_id, participant_id=participant_id)

    elif intent == "claims_upload":
        return "Please upload your claim as a PDF document."

    elif intent == "visit_prep":
        return run_workflow(sender, "visit_prep", msg)

    elif intent == "notification":
        return "You will receive a notification shortly."

    else:
        return "I didn’t understand that. Please try again."
