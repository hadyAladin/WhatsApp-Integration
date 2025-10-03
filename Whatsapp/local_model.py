# Whatsapp/local_model.py

import spacy
from spacy.matcher import PhraseMatcher

# Load English NLP model
nlp = spacy.load("en_core_web_sm")

# Create PhraseMatcher
matcher = PhraseMatcher(nlp.vocab, attr="LOWER")

# Define intent patterns (phrases, synonyms, natural expressions)
intent_patterns = {
    "claims_upload": [
        "claim", "receipt", "reimbursement", "bill", "invoice",
        "refund", "expenses", "compensation", "insurance",
        "proof of purchase", "medical expense", "payment receipt"
    ],
    "visit_prep": [
        "visit", "appointment", "check-in", "meeting", "doctor",
        "clinic", "ready", "schedule", "exam", "baseline",
        "confirm attendance", "pre-visit", "attend checkup"
    ],
    "notification": [
        "remind", "notify", "alert", "update", "follow-up",
        "heads up", "ping", "visit reminder", "appointment alert"
    ],
}

# Register all patterns in the matcher
for intent, phrases in intent_patterns.items():
    patterns = [nlp.make_doc(p) for p in phrases]
    matcher.add(intent, patterns)

def classify_local(text: str):
    doc = nlp(text.lower())
    matches = matcher(doc)

    candidates = []

    # --- 1. Phrase matches ---
    for match_id, start, end in matches:
        intent = nlp.vocab.strings[match_id]
        span_len = end - start
        score = 0.9 if span_len > 1 else 0.85
        candidates.append((intent, score))

    # --- 2. Lemma-based fallback ---
    lemmas = [t.lemma_ for t in doc]
    if "claim" in lemmas:
        candidates.append(("claims_upload", 0.8))
    if "receipt" in lemmas:
        candidates.append(("claims_upload", 0.8))
    if "visit" in lemmas:
        candidates.append(("visit_prep", 0.8))
    if "appointment" in lemmas:
        candidates.append(("visit_prep", 0.8))
    if "remind" in lemmas:
        candidates.append(("notification", 0.8))

    # --- 3. Pick best ---
    if candidates:
        return max(candidates, key=lambda x: x[1])

    return ("qa", 0.3)  # fallback → OpenAI
