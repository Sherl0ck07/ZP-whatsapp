


from flask import Flask, request, jsonify
import requests
import os
import json

# Load credentials from JSON
with open("credentials.json") as cred_file:
    creds = json.load(cred_file)

ACCESS_TOKEN = creds["ACCESS_TOKEN"]
VERIFY_TOKEN = creds["VERIFY_TOKEN"]
PHONE_NUMBER_ID = creds["PHONE_NUMBER_ID"]

app = Flask(__name__)

# Load JSON flow
with open("zp_buldhana_flow.json") as f:
    flow = json.load(f)

# Track user states
user_states = {}

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

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

                if msg.get("text"):
                    msg_body = msg["text"].get("body").strip().lower()
                elif msg.get("interactive"):
                    interactive = msg["interactive"]
                    if interactive["type"] == "button_reply":
                        msg_body = interactive["button_reply"]["id"]
                    elif interactive["type"] == "list_reply":
                        msg_body = interactive["list_reply"]["id"]

                if msg_body:
                    handle_message(from_number, msg_body)

    return jsonify({"status": "ok"}), 200

def handle_message(user, msg):
    state = user_states.get(user, "start")

    if state == "start":
        send_node(user, "start")
        user_states[user] = "departments"
        return

    # Departments menu
    if state == "departments":
        if msg in flow["departments"]:
            user_states[user] = msg
            send_node(user, "departments", msg)
        else:
            send_node(user, "start")
        return

    # Services menu
    if state in flow["departments"]:
        service_node = flow["departments"][state]["interactive"]["options"]
        valid_ids = [opt["id"] for opt in service_node]
        if msg in valid_ids:
            send_node(user, "services", msg)
        else:
            send_node(user, "departments", state)
        return

def send_node(user, category, msg_id=None):
    if category == "start":
        node = flow["start"]
        send_interactive(user, node["interactive"], node["message"])
    elif category == "departments":
        node = flow["departments"][msg_id]
        send_interactive(user, node["interactive"], node["message"])
    elif category == "services":
        node = flow["services"][msg_id]
        send_text(user, node["message"])

def send_text(to, text):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload)
    print("Text sent:", resp.status_code, resp.text)

def send_interactive(to, interactive_data, text):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": interactive_data["type"],
            "body": {"text": text},
            "action": {
                "button": interactive_data.get("button"),
                "sections": [
                    {"title": "Options", "rows": interactive_data["options"]}
                ]
            }
        }
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    resp = requests.post(f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages", headers=headers, json=payload)
    print("Interactive sent:", resp.status_code, resp.text)

@app.route("/")
def home():
    return "WhatsApp ZP Buldhana Bot running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
