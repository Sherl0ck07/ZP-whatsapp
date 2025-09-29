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

                    # --- Handle interactive messages ---
                    if "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = interactive["button_reply"]["title"]
                        elif interactive["type"] == "list_reply":
                            msg_body = interactive["list_reply"]["title"]

                    # --- Handle restart ---
                    if msg.get("text"):
                        user_text = msg["text"].get("body", "").strip()
                        if user_text.lower() in ["restart", "पुन्हा सुरू करा"]:
                            USER_STATE[from_number] = {"stage": "opening", "language": "en"}
                            text = MENU["opening"]["text"]["en"]
                            options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
                            send_whatsapp_message(from_number, text, options, "buttons")
                            continue
                        if not msg_body:
                            handle_free_text(from_number)
                            continue

                    # --- Fallback for unknown messages ---
                    if not msg_body:
                        handle_free_text(from_number)
                        continue

                    # --- Normal interaction flow ---
                    reply_text, options, opt_type = get_response(from_number, msg_body.strip())
                    send_whatsapp_message(from_number, reply_text, options, opt_type)

    return jsonify({"status": "ok"}), 200

# --- Helper to sanitize option titles ---
def sanitize_title(title):
    if not title or str(title).strip() == "":
        return "Option"
    t = str(title).strip()
    return t[:20]

# === Handle free text fallback ===
def handle_free_text(user_id):
    state = USER_STATE.get(user_id, {"stage": "opening", "language": "en"})
    lang = state.get("language", "en")
    reply_text = "❌ Sorry, we didn't understand that. Please select from the menu or type Restart."

    # Decide options based on user state
    if state["stage"] == "opening":
        options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
        opt_type = "buttons"
    elif state["stage"] in ["waiting_language", "services_menu"]:
        options = [o["label"][lang] for o in MENU["menus"]["services_menu"]["options"]]
        opt_type = "list"
    elif state["stage"] == "about_submenu":
        options = [o["label"][lang] for o in MENU["menus"]["about_submenu"]["options"]]
        opt_type = "list"
    elif state["stage"] == "departments":
        options = [o["label"][lang] for o in MENU["menus"]["departments"]["options"]]
        opt_type = "list"
    else:
        options, opt_type = [], "text"

    send_whatsapp_message(user_id, reply_text, options, opt_type)

# === Generate bot response based on user state ===
def get_response(user_id, msg_text):
    state = USER_STATE.get(user_id, {"stage": "opening", "language": "en"})

    # --- Opening stage ---
    if state["stage"] == "opening":
        USER_STATE[user_id] = {"stage": "waiting_language", "language": "en"}
        text = MENU["opening"]["text"]["en"]
        options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
        return text, options, "buttons"

    # --- Language selection ---
    if state["stage"] == "waiting_language":
        if msg_text.lower() in ["मराठी", "marathi"]:
            lang_key, lang = "lang_marathi", "mr"
        else:
            lang_key, lang = "lang_english", "en"

        USER_STATE[user_id] = {"stage": "services_menu", "language": lang}
        text = MENU["languages"][lang_key]["text"]
        options = [o["label"][lang] for o in MENU["menus"]["services_menu"]["options"]]
        return text, options, "list"

    # --- Services menu ---
    if state["stage"] == "services_menu":
        lang = state["language"]
        selected = msg_text.lower()

        if "change language" in selected or "भाषा" in selected:
            USER_STATE[user_id] = {"stage": "opening", "language": "en"}
            text = MENU["opening"]["text"]["en"]
            options = [o["label"] for o in MENU["opening"]["options"]["choices"]]
            return text, options, "buttons"

        if "about zp" in selected or "बद्दल" in selected:
            USER_STATE[user_id]["stage"] = "about_submenu"
            text = MENU["menus"]["about_zp"]["text"][lang]
            options = [o["label"][lang] for o in MENU["menus"]["about_submenu"]["options"]]
            return text, options, "list"

        if "departments" in selected or "विभाग" in selected:
            USER_STATE[user_id]["stage"] = "departments"
            text = "Select Department:"
            options = [o["label"][lang] for o in MENU["menus"]["departments"]["options"]]
            return text, options, "list"

        options = [o["label"][lang] for o in MENU["menus"]["services_menu"]["options"]]
        return "Service not recognized. Please select from menu.", options, "list"

    # --- Submenus ---
    if state["stage"] in ["about_submenu", "departments"]:
        lang = state["language"]
        if "main menu" in msg_text.lower() or "मुख्य" in msg_text:
            USER_STATE[user_id]["stage"] = "services_menu"
            options = [o["label"][lang] for o in MENU["menus"]["services_menu"]["options"]]
            return "Returning to main menu.", options, "list"

        if state["stage"] == "about_submenu":
            options = [o["label"][lang] for o in MENU["menus"]["about_submenu"]["options"]]
            return "Select an option from About Z.P.", options, "list"

        if state["stage"] == "departments":
            options = [o["label"][lang] for o in MENU["menus"]["departments"]["options"]]
            return "Select a department.", options, "list"

    return "Sorry, I didn't understand.", [], "text"

# === Send WhatsApp message ===
def send_whatsapp_message(to, message_text, options=None, opt_type="text"):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to}

    if opt_type == "buttons" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "button",
            "body": {"text": message_text},
            "action": {"buttons": [{"type": "reply", "reply": {"id": str(i), "title": sanitize_title(b)}}
                                   for i, b in enumerate(options, 1)]}
        }
    elif opt_type == "list" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "list",
            "body": {"text": message_text},
            "action": {"button": "Choose",
                       "sections": [{"title": "Options",
                                     "rows": [{"id": str(i), "title": sanitize_title(b)}
                                              for i, b in enumerate(options, 1)]}]}
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
