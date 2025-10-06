from .state import StateMachine, get_state, set_state, clear_state

# -------------------------------
# Claims Upload Workflow
# -------------------------------
def claims_idle(msg):
    return "Please upload your claim as a PDF.", "awaiting_claim_pdf"

def claims_awaiting_pdf(msg):
    if msg.document_id:
        return "Thanks, your claim PDF has been received.", "end"
    else:
        return "I expected a PDF document. Please try again.", "awaiting_claim_pdf"

claims_upload_workflow = StateMachine(
    name="claims_upload",
    states=["idle", "awaiting_claim_pdf"],
    transitions={
        "idle": ["awaiting_claim_pdf"],
        "awaiting_claim_pdf": ["end"],
    },
    handlers={
        "idle": claims_idle,
        "awaiting_claim_pdf": claims_awaiting_pdf,
    },
)


# -------------------------------
# Visit Prep Workflow
# -------------------------------
def visit_idle(msg):
    return "Are you ready for your upcoming visit? Reply YES or NO.", "awaiting_confirmation"

def visit_confirmation(msg):
    text = (msg.text or "").strip().lower()
    if text in ["yes", "y"]:
        return "Great! You're all set for your visit.", "end"
    elif text in ["no", "n"]:
        return "Okay, please contact your coordinator for assistance.", "end"
    else:
        return "Please reply YES or NO.", "awaiting_confirmation"

visit_prep_workflow = StateMachine(
    name="visit_prep",
    states=["idle", "awaiting_confirmation"],
    transitions={
        "idle": ["awaiting_confirmation"],
        "awaiting_confirmation": ["end"],
    },
    handlers={
        "idle": visit_idle,
        "awaiting_confirmation": visit_confirmation,
    },
)


# -------------------------------
# Workflow Runner
# -------------------------------
def run_workflow(workflow_name: str, user_id: str, msg):
    if workflow_name == "claims_upload":
        return claims_upload_workflow.handle(user_id, msg)
    elif workflow_name == "visit_prep":
        return visit_prep_workflow.handle(user_id, msg)
    else:
        return "Unknown workflow."
