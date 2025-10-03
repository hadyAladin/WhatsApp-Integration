consents = {}

def check_opt_in_out(user_id, text):
    lower = text.strip().lower()
    if lower == "stop":
        consents[user_id] = False
        return "You have been unsubscribed."
    if lower == "start":
        consents[user_id] = True
        return "You are now subscribed again."
    return None
