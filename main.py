from flask import Flask, request, jsonify
import requests
import os

import json

# === Load Credentials from JSON ===
with open("credentials.json") as f:
    creds = json.load(f)

ACCESS_TOKEN = creds["ACCESS_TOKEN"]
VERIFY_TOKEN = creds["VERIFY_TOKEN"]
PHONE_NUMBER_ID = creds["PHONE_NUMBER_ID"]

app = Flask(__name__)

# === Verify Webhook ===
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("Webhook verified successfully ✅")
            return challenge, 200
    return "Verification failed ❌", 403

# === Handle Incoming Messages ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Received webhook:", data)

    if data and "entry" in data:
        for entry in data["entry"]:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    from_number = msg.get("from")
                    msg_body = msg.get("text", {}).get("body")

                    if msg_body:
                        reply_text = f"You said: {msg_body}"
                        send_whatsapp_message(from_number, reply_text)

    return jsonify({"status": "ok"}), 200

# === Send Message Function ===
def send_whatsapp_message(to, message_text):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
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
    print("📤 Send message response:", resp.status_code, resp.text)
    return resp.json()

# === Root Endpoint ===
@app.route("/")
def home():
    return "🚀 WhatsApp Echo Bot is running!", 200

# === Run App ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
