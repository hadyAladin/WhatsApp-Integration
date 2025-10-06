import base64
import os
from openai import OpenAI
from .adapter_meta import download_media
from .media_service import save_pdf, extract_pdf_text
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY_PROJECT"),
    project=os.getenv("OPENAI_PROJECT")
)

def get_ai_reply(user_input: str) -> str:
    """
    Default text AI reply handler.
    """
    system_prompt = (
        "You are a professional Clinical Trial Companion chatbot, assisting participants "
        "throughout their study. Always respond in a polite, supportive, and clear tone. "
        "Your role is to help participants with: visit schedules, claim reimbursements, "
        "study entitlements, reminders, and general guidance. "
        "Keep answers concise and easy to understand (like WhatsApp messages), "
        "but always accurate according to study procedures. "
        "If a question cannot be answered, politely say you will connect them with study staff. "
        "Never expose technical system details or internal terms like FSM, workflow, or database. "
        "Always maintain participant trust and confidentiality. "
        "If a new user contacts you who is not yet registered as a participant, "
        "flexibly ask if they would like to participate in the trial "
        "(for example: 'Would you like to join the study?', "
        "'Are you interested in participating in the trial?', "
        "or 'Can I register you as a participant in the clinical study?')."
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]
        )
        return resp.choices[0].message.content
    except Exception as e:
        print("OpenAI error:", e)
        return "Sorry, I couldn’t generate a reply right now."


# Alias for gateway fallback
def ask_openai(user_input: str) -> str:
    return get_ai_reply(user_input)


def handle_image(media_id, caption=""):
    """
    Handle image uploads → analyze with GPT-4o-mini vision.
    """
    try:
        img_data = download_media(media_id)
        b64_img = base64.b64encode(img_data).decode("utf-8")
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": caption or "Please analyze this image."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                ]
            }]
        )
        return resp.choices[0].message.content
    except Exception as e:
        print("Image handling error:", e)
        return "Sorry, I couldn’t analyze the image."


def handle_document(media_id):
    """
    Handle PDF uploads → extract text then summarize with GPT.
    """
    try:
        path = save_pdf(media_id)
        text = extract_pdf_text(path)
        resp = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "Summarize the following PDF clearly and briefly."},
                {"role": "user", "content": text[:4000]}
            ]
        )
        return resp.choices[0].message.content
    except Exception as e:
        print("Document handling error:", e)
        return "Sorry, I couldn’t process the document."
