from flask import Flask
import threading
from .webhook_routes import bp, tasks
from .backend_service import send_chat
from .whatsapp_service import send_message
from .config import logger

app = Flask(__name__)
app.register_blueprint(bp)

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


def worker():
    """Background worker processing queued messages."""
    while True:
        msg = tasks.get()
        try:
            sender = msg.get("from")
            mtype = msg.get("type")
            if not sender or not mtype:
                continue

            if mtype == "text":
                text = msg.get("text", {}).get("body", "").strip()
                if not text:
                    send_message(sender, "Please send a valid message.")
                    continue
                answer = send_chat(text)
                send_message(sender, answer)
            else:
                send_message(sender, "I can only process text or receipt uploads.")
        except Exception as e:
            logger.error(f"[Worker] error: {e}", exc_info=True)
        finally:
            tasks.task_done()


# Start a few background threads
for _ in range(4):
    threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
