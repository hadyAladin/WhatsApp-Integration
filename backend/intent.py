# Whatsapp/intent.py

import os
from openai import OpenAI
from .local_model import classify_local
from .rag_service import rag_answer

# Initialize OpenAI client (only for classification, not answering)
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY_PROJECT"),
    project=os.getenv("OPENAI_PROJECT")
)

def classify_intents(user_text: str, trial_id: str = "default", participant_id: str = None):
    """
    Classify a user's message intent using rules, local NLP, and fallbacks.
    - Local NLP (spaCy) used first for speed & cost efficiency.
    - If confidence < 0.3 → directly call RAG and return the answer.
    - Otherwise use OpenAI for intent classification (qa/claims/visit/notification).
    Returns a tuple: (intent, answer or None)
    """

    # 1. Local NLP classifier
    intent, confidence = classify_local(user_text)
    print(f"[Intent] Local NLP intent={intent}, confidence={confidence}")

    # 2. If local NLP confidence is too low → forward to RAG
    if confidence < 0.3:
        print("[Intent] Low confidence → forwarding to RAG")
        rag_resp = rag_answer(user_text, trial_id=trial_id, participant_id=participant_id)
        return ("qa", rag_resp)

    # 3. Otherwise, ask OpenAI to confirm classification
    system_prompt = """You are an intent classifier for a clinical trial WhatsApp assistant.
    Return only one of: ["qa", "claims_upload", "visit_prep", "notification", "other"].
    - "qa" → free-text question.
    - "claims_upload" → upload receipts, reimbursements, or claims.
    - "visit_prep" → visits, reminders, readiness, confirmations.
    - "notification" → reminders/templates.
    - "other" → everything else.
    Reply ONLY with the intent label, no explanations.
    """

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ]
        )
        ai_intent = resp.choices[0].message.content.strip().lower()
        print(f"[Intent] OpenAI classified as: {ai_intent}")
        return (ai_intent, None)

    except Exception as e:
        print(f"[Intent] OpenAI classification error: {e}")
        # fallback again to RAG if OpenAI fails
        rag_resp = rag_answer(user_text, trial_id=trial_id, participant_id=participant_id)
        return ("qa", rag_resp)
