"""
server/app.py

Local Flask API + frontend server for the Airline Resolution Agent.

Run:
    python server/app.py

Then open:
    http://127.0.0.1:5000
"""

import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Make agent/ importable
sys.path.append(str(Path(__file__).resolve().parent.parent / "agent"))

from agent import handle_message, _conversations  # noqa: E402


# --------------------------------------------------
# Flask application
# --------------------------------------------------

app = Flask(__name__)
CORS(app)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# --------------------------------------------------
# Frontend
# --------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def frontend_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# --------------------------------------------------
# Chat endpoint
# --------------------------------------------------

@app.route("/chat", methods=["POST"])
def chat():
    """
    Body:
        {
            "pnr": "SK4821X",
            "message": "my flight got cancelled"
        }

    Returns:
        {
            "reply": "...",
            "escalated": true/false
        }
    """

    data = request.get_json(silent=True) or {}

    pnr = data.get("pnr", "").strip()
    message = data.get("message", "").strip()

    if not pnr or not message:
        return jsonify({
            "error": "Both 'pnr' and 'message' are required."
        }), 400

    try:
        result = handle_message(pnr, message)

    except Exception:
        app.logger.exception("Error handling message")

        return jsonify({
            "error": "Something went wrong processing that request."
        }), 500

    return jsonify(result)


# --------------------------------------------------
# Conversation history
# --------------------------------------------------

@app.route("/history/<pnr>", methods=["GET"])
def history(pnr):
    """
    Returns the in-memory conversation for a PNR.
    """

    convo = _conversations.get(pnr, [])

    return jsonify({
        "pnr": pnr,
        "history": convo
    })


# --------------------------------------------------
# Start server
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)