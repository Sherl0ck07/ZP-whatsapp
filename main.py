from flask import Flask, request, jsonify
import requests
import os

# Environment variables for security
ACCESS_TOKEN = "EAAYtyB9hTPsBPla6eZBvA79i16Qud60wVwm5XjbvEPJEnzpdnnw8Glnw75jbv3jbvFp0feevoTQd80hiqc3YmZCoKy1nHANYcw3mASrcSv1i4BtrS8oJcOj90cRQWjBb0sUf2jVanclzOtv6QusCb3rI2pm6bbev2tKOQ8ZBVdedZCivZCXQoqnYCECWLpaZAZAUFZA9Mv2ognqb6uZC6GJQlSipX1Oqiny6bNos6MDeu7JXFVgZDZD"  # from Meta App Dashboard

VERIFY_TOKEN = "123456"
PHONE_NUMBER_ID = "729844620223276"

app = Flask(__name__)

# Simple in-memory user states
user_states = {}

# Products info
products_info = {
    "eng": {
        "product1": "ZP Buldhana Product 1: Description in English",
        "product2": "ZP Buldhana Product 2: Description in English",
    },
    "mar": {
        "product1": "ZP Buldhana उत्पादन 1: मराठीत माहिती",
        "product2": "ZP Buldhana उत्पादन 2: मराठीत माहिती",
    }
}

# Webhook verification
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode and token and mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

# Webhook receiver
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("Received webhook:", data)

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                from_number = msg.get("from")
                msg_body = None

                # Text messages
                if msg.get("text"):
                    msg_body = msg["text"].get("body").strip().lower()
                # Interactive messages (list/button)
                elif msg.get("interactive"):
                    interactive = msg["interactive"]
                    if interactive["type"] == "button_reply":
                        msg_body = interactive["button_reply"]["id"]
                    elif interactive["type"] == "list_reply":
                        msg_body = interactive["list_reply"]["id"]

                if msg_body:
                    handle_user_message(from_number, msg_body)

    return jsonify({"status": "ok"}), 200

# Handle user state and messages
def handle_user_message(user, message):
    state = user_states.get(user, "start")

    if state == "start":
        send_language_list(user)
        user_states[user] = "language"

    elif state == "language":
        if message in ["eng", "english"]:
            send_product_list(user, "eng")
            user_states[user] = "menu_eng"
        elif message in ["mar", "marathi"]:
            send_product_list(user, "mar")
            user_states[user] = "menu_mar"
        else:
            send_language_list(user)

    elif state in ["menu_eng", "menu_mar"]:
        lang = "eng" if state == "menu_eng" else "mar"
        if message in products_info[lang]:
            send_whatsapp_message(user, products_info[lang][message])
        else:
            send_product_list(user, lang)

# Send plain text message
def send_whatsapp_message(to, message_text):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message_text}
    }
    resp = requests.post(url, headers=headers, json=payload)
    print("Text message sent:", resp.status_code, resp.text)
    return resp.json()

# Send interactive list message
def send_interactive_message(payload):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    resp = requests.post(url, headers=headers, json=payload)
    print("Interactive message sent:", resp.status_code, resp.text)
    return resp.json()

# Language selection list
def send_language_list(to):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "Hello! Welcome to ZP Buldhana. Please choose your language:"},
            "action": {
                "button": "Choose Language",
                "sections": [
                    {
                        "title": "Languages",
                        "rows": [
                            {"id": "eng", "title": "English"},
                            {"id": "mar", "title": "Marathi"}
                        ]
                    }
                ]
            }
        }
    }
    send_interactive_message(payload)

# Product selection list
def send_product_list(to, lang):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "Please select a product:"},
            "action": {
                "button": "Products",
                "sections": [
                    {
                        "title": "ZP Buldhana Products",
                        "rows": [
                            {"id": "product1", "title": "Product 1" if lang=="eng" else "उत्पादन 1"},
                            {"id": "product2", "title": "Product 2" if lang=="eng" else "उत्पादन 2"}
                        ]
                    }
                ]
            }
        }
    }
    send_interactive_message(payload)

@app.route("/")
def home():
    return "WhatsApp ZP Buldhana Interactive Bot running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
