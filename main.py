  # you define this
ACCESS_TOKEN = "EAAYtyB9hTPsBPtJDJlWIKVAUDZAUXedhocIFduHHGY3sbnns0yP9NGNGBS8A3Jz1wJn7c3YjunespGydPY2VezZAY8DuL1bAihZCvZCv0YXznUxw0USaZBfByrA3mzB8MtVxUgGff1FCZAjy38Ynj0dSZAzLotfKUNcswscOUBmNqNem2YsPRpryFQrxYFZB1YIupzwNcZClxkLwi67NH6l2whnDbF3qqYnyd0fMXSg4HZBfcaiAZDZD"  # from Meta App Dashboard
from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)
# 08ecb69c3741be3a2b4515209a795268
# These should be environment variables or securely stored in production
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "my_verify_token")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "your_phone_number_id")

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    # Verify webhook setup (sent by Meta during webhook subscription)
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    # Log incoming data for debugging
    print("Received webhook:", data)

    # Meta’s webhook structure — parse messages
    entry_list = data.get("entry", [])
    for entry in entry_list:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                from_number = msg.get("from")  # user’s phone number
                msg_body = None
                # The message could be text or other types
                if msg.get("text"):
                    msg_body = msg["text"].get("body")
                # You can also handle images, stickers, etc. later

                if msg_body:
                    # Echo back the same text
                    reply_text = f"You said: {msg_body}"
                    send_whatsapp_message(from_number, reply_text)

    return jsonify({"status": "ok"}), 200

def send_whatsapp_message(to, message_text):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {
            "body": message_text
        }
    }
    resp = requests.post(url, headers=headers, json=payload)
    print("Send message response:", resp.status_code, resp.text)
    return resp.json()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
