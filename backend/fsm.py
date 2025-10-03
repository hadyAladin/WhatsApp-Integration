# Stateless transitions for three workflows
FSM_CLAIMS_UPLOAD = {
    "START": {"begin": "WAITING_FOR_RECEIPT"},
    "WAITING_FOR_RECEIPT": {"upload": "RECEIPT_RECEIVED", "reset": "START"},
    "RECEIPT_RECEIVED": {"validate_ok": "VALIDATED", "reset": "START"},
    "VALIDATED": {"finish": "DONE", "reset": "START"},
    "DONE": {"reset": "START"},
}

FSM_VISIT_PREP = {
    "START": {"begin": "WAITING_FOR_CONFIRMATION"},
    "WAITING_FOR_CONFIRMATION": {"confirm": "CONFIRMED", "reset": "START"},
    "CONFIRMED": {"finish": "DONE", "reset": "START"},
    "DONE": {"reset": "START"},
}

FSM_RUN = {
    "START": {"begin": "WAITING_FOR_ID"},
    "WAITING_FOR_ID": {"provide_id": "ID_RECEIVED", "reset": "START"},
    "ID_RECEIVED": {"validate_ok": "VALIDATED", "reset": "START"},
    "VALIDATED": {"finish": "DONE", "reset": "START"},
    "DONE": {"reset": "START"},
}

def step(current_state: str, event: str, workflow: str) -> str:
    if workflow == "claims_upload_workflow":
        return FSM_CLAIMS_UPLOAD.get(current_state, {}).get(event, current_state)
    return current_state
