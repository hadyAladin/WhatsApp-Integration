class ChannelMessage:
    """Unified schema for incoming WhatsApp messages."""
    def __init__(self, msg: dict):
        self.id = msg["id"]
        self.sender = msg["from"]
        self.type = msg["type"]
        self.text = msg.get("text", {}).get("body")
        self.image_id = msg.get("image", {}).get("id")
        self.document_id = msg.get("document", {}).get("id")
