# Whatsapp/rules.py

def check_rules(text: str):
    lower = text.strip().lower()

    # Compliance keywords
    if lower == "stop":
        return "opt_out"
    if lower == "start":
        return "opt_in"

    # Simple intent cues
    if "claim" in lower or "receipt" in lower:
        return "claims_upload"
    if "visit" in lower or "appointment" in lower:
        return "visit_prep"

    return None
