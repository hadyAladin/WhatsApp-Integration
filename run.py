import os
from dotenv import load_dotenv
from Whatsapp.gateway import app

if __name__ == "__main__":
    load_dotenv()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    debug = os.getenv("DEBUG", "true").lower() == "true"
    app.run(host=host, port=port, debug=debug)
