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

# === Load Bot Flow JSON ===
with open("zp_buldhana_flow.json") as f:
    MENU = json.load(f)

# In-memory user state storage
USER_STATE = {}

app = Flask(__name__)

# === Verify Webhook ===
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
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
                        reply_text, options, opt_type = get_response(from_number, msg_body.strip())
                        send_whatsapp_message(from_number, reply_text, options, opt_type)

    return jsonify({"status": "ok"}), 200

# === Generate Bot Response Based on User State ===
def get_response(user_id, msg_text):
    state = USER_STATE.get(user_id, {"stage": "opening", "language": "en"})

    # --- Opening ---
    if state["stage"] == "opening":
        USER_STATE[user_id] = {"stage": "waiting_language", "language": "en"}
        text = MENU["opening"]["text"]["en"]
        options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
        return text, options, "buttons"

    # --- Language Selection ---
    if state["stage"] == "waiting_language":
        if msg_text.lower() in ["मराठी", "marathi"]:
            lang_key = "lang_marathi"
            lang = "mr"
        else:
            lang_key = "lang_english"
            lang = "en"

        USER_STATE[user_id] = {"stage": "services_menu", "language": lang}
        text = MENU["languages"][lang_key]["text"]
        options = [o["label"][lang] for o in MENU["menus"]["services_menu"]["options"]]
        return text, options, "list"

    # --- Services Menu ---
    if state["stage"] == "services_menu":
        lang = state["language"]
        selected = msg_text.lower()

        # Change Language
        if "change language" in selected or "भाषा" in selected:
            USER_STATE[user_id] = {"stage": "opening", "language": "en"}
            text = MENU["opening"]["text"]["en"]
            options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
            return text, options, "buttons"

        # About ZP
        if "about zp" in selected or "बद्दल" in selected:
            USER_STATE[user_id]["stage"] = "about_submenu"
            text = MENU["menus"]["about_zp"]["text"][lang]
            options = [o["label"][lang] for o in MENU["menus"]["about_submenu"]["options"]]
            return text, options, "list"

        # Departments
        if "departments" in selected or "विभाग" in selected:
            USER_STATE[user_id]["stage"] = "departments"
            text = "Select Department:"
            options = [o["label"][lang] for o in MENU["menus"]["departments"]["options"]]
            return text, options, "list"

        # Default fallback
        options = [o["label"][lang] for o in MENU["menus"]["services_menu"]["options"]]
        return "Service not recognized. Please select from menu.", options, "list"

    # --- About Submenu or Departments ---
    if state["stage"] in ["about_submenu", "departments"]:
        lang = state["language"]
        options = []
        # Check if user wants Main Menu
        if "main menu" in msg_text.lower() or "मुख्य" in msg_text:
            USER_STATE[user_id]["stage"] = "services_menu"
            options = [o["label"][lang] for o in MENU["menus"]["services_menu"]["options"]]
            return "Returning to main menu.", options, "list"
        # Stay in same submenu
        if state["stage"] == "about_submenu":
            options = [o["label"][lang] for o in MENU["menus"]["about_submenu"]["options"]]
            return "Select an option from About Z.P.", options, "list"
        if state["stage"] == "departments":
            options = [o["label"][lang] for o in MENU["menus"]["departments"]["options"]]
            return "Select a department.", options, "list"

    # --- Fallback ---
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
