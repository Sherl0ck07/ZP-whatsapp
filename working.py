  # you define this
from flask import Flask, request, jsonify
import requests
import os

ACCESS_TOKEN = "EAAYtyB9hTPsBPla6eZBvA79i16Qud60wVwm5XjbvEPJEnzpdnnw8Glnw75jbv3jbvFp0feevoTQd80hiqc3YmZCoKy1nHANYcw3mASrcSv1i4BtrS8oJcOj90cRQWjBb0sUf2jVanclzOtv6QusCb3rI2pm6bbev2tKOQ8ZBVdedZCivZCXQoqnYCECWLpaZAZAUFZA9Mv2ognqb6uZC6GJQlSipX1Oqiny6bNos6MDeu7JXFVgZDZD"  # from Meta App Dashboard
                
app = Flask(__name__)

VERIFY_TOKEN = "123456"
PHONE_NUMBER_ID = "729844620223276"

@app.route("/webhook", methods=["GET"])
def verify_webhook():
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
    print("Received webhook:", data)

    entry_list = data.get("entry", [])
    for entry in entry_list:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                from_number = msg.get("from")
                msg_body = None
                if msg.get("text"):
                    msg_body = msg["text"].get("body")

                if msg_body:
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
        "text": {"body": message_text}
    }
    resp = requests.post(url, headers=headers, json=payload)
    print("Send message response:", resp.status_code, resp.text)
    return resp.json()

@app.route("/")
def home():
    return "WhatsApp Echo Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
