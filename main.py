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
        return challenge, 200
    return "Verification failed ❌", 403

# === Handle Incoming Messages ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Received webhook:", json.dumps(data, indent=2, ensure_ascii=False))

    if data.get("entry"):
        for entry in data["entry"]:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    from_number = msg.get("from")
                    msg_body = None

                    # Handle interactive messages
                    if "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = interactive["button_reply"]["title"]
                        elif interactive["type"] == "list_reply":
                            msg_body = interactive["list_reply"]["title"]

                    # Handle restart
                    if msg.get("text"):
                        user_text = msg["text"].get("body", "").strip()
                        if user_text.lower() in ["restart", "पुन्हा सुरू करा"]:
                            USER_STATE[from_number] = {"stage": "INIT", "language": None, "current_menu": "initial_greet"}
                            send_bot_message(from_number)
                            continue
                        if not msg_body:
                            handle_free_text(from_number)
                            continue

                    # Normal flow
                    if msg_body:
                        handle_user_input(from_number, msg_body)

    return jsonify({"status": "ok"}), 200

# === Handle Free Text / Fallback ===
def handle_free_text(user_id):
    state = USER_STATE.get(user_id, {"stage": "INIT", "language": None, "current_menu": "initial_greet"})
    reply_text = MENU["fallback"]["msg"]
    options, opt_type = [], "text"

    # Provide relevant options based on last menu
    current_menu = state.get("current_menu")
    if current_menu and current_menu in MENU["menus"]:
        lang = state.get("language") or MENU["default_language"]
        menu_data = MENU["menus"][current_menu].get(lang, {})
        if "options" in menu_data:
            options = [o["label"] for o in menu_data["options"]]
            opt_type = "list"
        elif "buttons" in menu_data:
            options = menu_data["buttons"]
            opt_type = "buttons"

    send_whatsapp_message(user_id, reply_text, options, opt_type)

# === Handle User Input ===
def handle_user_input(user_id, msg_text):
    state = USER_STATE.get(user_id, {"stage": "INIT", "language": None, "current_menu": "initial_greet"})

    # Initial greet -> language selection
    if state["stage"] == "INIT":
        USER_STATE[user_id] = {"stage": "LANG_SELECTED", "language": msg_text, "current_menu": "main_menu"}
        send_bot_message(user_id)
        return

    # Main Menu
    current_menu = state.get("current_menu")
    lang = state.get("language") or MENU["default_language"]

    # Handle "Change Language"
    if msg_text.lower() in ["change language", "भाषा बदल"]:
        USER_STATE[user_id] = {"stage": "INIT", "language": None, "current_menu": "initial_greet"}
        send_bot_message(user_id)
        return

    # Navigate menus
    menu_data = MENU["menus"].get(current_menu, {}).get(lang, {})
    if "options" in menu_data:
        matched = False
        for opt in menu_data["options"]:
            if msg_text.strip().lower() == opt["label"].strip().lower():
                key = opt["key"]
                USER_STATE[user_id]["current_menu"] = key
                if key in MENU["menus"]:
                    send_bot_message(user_id)
                else:
                    # handle department_details or other info
                    send_info(user_id, key, lang)
                matched = True
                break
        if not matched:
            handle_free_text(user_id)
    elif "buttons" in menu_data:
        # Handle button clicks
        send_info(user_id, msg_text, lang)
    else:
        handle_free_text(user_id)

# === Send Bot Message Based on Current Menu ===
def send_bot_message(user_id):
    state = USER_STATE[user_id]
    current_menu = state.get("current_menu")
    lang = state.get("language") or MENU["default_language"]
    menu_data = MENU["menus"].get(current_menu, {}).get(lang, {})

    if not menu_data:
        send_whatsapp_message(user_id, MENU["fallback"]["msg"])
        return

    text = menu_data.get("msg", "")
    options, opt_type = [], "text"
    if "options" in menu_data:
        options = [o["label"] for o in menu_data["options"]]
        opt_type = "list"
    elif "buttons" in menu_data:
        options = menu_data["buttons"]
        opt_type = "buttons"
    elif "submenu" in menu_data:
        for sub in menu_data["submenu"]:
            USER_STATE[user_id]["current_menu"] = sub
            send_bot_message(user_id)
        return

    send_whatsapp_message(user_id, text, options, opt_type)

# === Send Info for Departments / Schemes / Contacts ===
def send_info(user_id, key, lang):
    if key in MENU["menus"].get("department_details", {}):
        dept = MENU["menus"]["department_details"][key].get(lang, {})
        text = dept.get("msg", "")
        options = dept.get("buttons", [])
        send_whatsapp_message(user_id, text, options, "buttons")
    else:
        # fallback for unknown key
        send_whatsapp_message(user_id, MENU["fallback"]["msg"])

# === Sanitize Titles ===
def sanitize_title(title):
    if not title or str(title).strip() == "":
        return "Option"
    return str(title).strip()[:20]

# === Send WhatsApp Message ===
def send_whatsapp_message(to, message_text, options=None, opt_type="text"):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to}

    if opt_type == "buttons" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "button",
            "body": {"text": message_text},
            "action": {"buttons": [{"type": "reply", "reply": {"id": str(i), "title": sanitize_title(b)}} for i, b in enumerate(options, 1)]}
        }
    elif opt_type == "list" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "list",
            "body": {"text": message_text},
            "action": {"button": "Choose",
                       "sections": [{"title": "Options",
                                     "rows": [{"id": str(i), "title": sanitize_title(b)} for i, b in enumerate(options, 1)]}]}
        }
    else:
        payload["text"] = {"body": message_text}

    resp = requests.post(url, headers=headers, json=payload)
    print("📤 Send message response:", resp.status_code, resp.text)
    return resp.json()

# === Root Endpoint ===
@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200

# === Run App ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
