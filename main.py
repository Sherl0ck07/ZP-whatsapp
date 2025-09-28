from flask import Flask, request, jsonify
import requests
import os
import json

# === Load Credentials ===
with open("credentials.json") as f:
    creds = json.load(f)

ACCESS_TOKEN = creds["ACCESS_TOKEN"]
VERIFY_TOKEN = creds["VERIFY_TOKEN"]
PHONE_NUMBER_ID = creds["PHONE_NUMBER_ID"]

# === Load Menu JSON ===
with open("zp_buldhana_flow.json") as f:
    MENU = json.load(f)

# In-memory user states
USER_STATE = {}

app = Flask(__name__)

# === Verify Webhook ===
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token and mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified ✅")
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
                        reply_text, options, opt_type = get_response(from_number, msg_body)
                        send_whatsapp_message(from_number, reply_text, options, opt_type)

    return jsonify({"status": "ok"}), 200

# === Generate Bot Response based on State ===
def get_response(user_id, msg_text):
    state = USER_STATE.get(user_id, "opening")

    # Opening
    if state == "opening":
        USER_STATE[user_id] = "waiting_language"
        text = MENU["opening"]["text"]["en"]
        options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
        return text, options, "buttons"

    # Language selection
    if state == "waiting_language":
        if msg_text.lower() in ["मराठी", "marathi"]:
            lang_key = "lang_marathi"
        else:
            lang_key = "lang_english"
        USER_STATE[user_id] = "services_menu"
        text = MENU["languages"][lang_key]["text"]
        options = [o["label"]["en"] for o in MENU["menus"]["services_menu"]["options"]]
        return text, options, "list"

    # Services Menu
    if state == "services_menu":
        selected = msg_text.lower()
        if "about zp" in selected:
            USER_STATE[user_id] = "about_submenu"
            text = MENU["menus"]["about_zp"]["text"]["en"]
            options = [o["label"]["en"] for o in MENU["menus"]["about_submenu"]["options"]]
            return text, options, "list"
        elif "departments" in selected:
            USER_STATE[user_id] = "departments"
            options = [o["label"]["en"] for o in MENU["menus"]["departments"]["options"]]
            return "Select Department:", options, "list"
        elif "change language" in selected:
            USER_STATE[user_id] = "opening"
            text = MENU["opening"]["text"]["en"]
            options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
            return text, options, "buttons"
        else:
            return "Service not recognized. Please select from menu.", [o["label"]["en"] for o in MENU["menus"]["services_menu"]["options"]], "list"

    # Default fallback
    return "Sorry, I didn't understand.", [], "text"

# === Send WhatsApp Message ===
def send_whatsapp_message(to, message_text, options=None, opt_type="text"):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {"messaging_product": "whatsapp", "to": to}

    if opt_type == "buttons" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "button",
            "body": {"text": message_text},
            "action": {"buttons": [{"type": "reply", "reply": {"id": str(i), "title": b}} for i, b in enumerate(options, 1)]}
        }
    elif opt_type == "list" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "list",
            "body": {"text": message_text},
            "action": {
                "button": "Choose",
                "sections": [{"title": "Options", "rows": [{"id": str(i), "title": b} for i, b in enumerate(options, 1)]}]
            }
        }
    else:
        payload["text"] = {"body": message_text}

    resp = requests.post(url, headers=headers, json=payload)
    print("📤 Send message response:", resp.status_code, resp.text)
    return resp.json()

# === Root Endpoint ===
@app.route("/")
def home():
    return "🚀 WhatsApp Bot is running!", 200

# === Run App ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
