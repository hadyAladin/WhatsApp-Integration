import io, requests
from .config import BACKEND_BASE_URL, PARTICIPANT_ID, logger
from .backend_service import headers

pending_receipts = {}

def upload(sender: str, visit_id: str) -> str:
    receipt = pending_receipts.pop(sender, None)
    if not receipt:
        return "No pending receipt found."
    url = f"{BACKEND_BASE_URL}/api/receipts/upload"
    files = {"file": (receipt["filename"], io.BytesIO(receipt["file_bytes"]), receipt["mime_type"])}
    data = {"participant_id": PARTICIPANT_ID, "visit_id": visit_id, "source_channel": "whatsapp"}
    try:
        r = requests.post(url, data=data, files=files, headers=headers(), timeout=30)
        r.raise_for_status()
        return "Receipt uploaded successfully."
    except Exception as e:
        logger.error(f"[Backend] Upload failed: {e}", exc_info=True)
        return "Failed to upload receipt."
