from flask import Flask, request, jsonify
import requests
import json
import os
import threading
import time

# === Load JSON flow data ===
with open("zp_buldhana_flow.json", encoding="utf-8") as f:
    MENU = json.load(f)

with open("credentials.json", encoding="utf-8") as f:
    creds = json.load(f)

ACCESS_TOKEN = creds.get("ACCESS_TOKEN")
VERIFY_TOKEN = creds.get("VERIFY_TOKEN")
PHONE_NUMBER_ID = creds.get("PHONE_NUMBER_ID")

app = Flask(__name__)

# Track user state and last active time
USER_STATE = {}
LAST_ACTIVE = {}

# Utility
def sanitize_title(title):
    return str(title).strip()[:20] if title else "Option"

# Send WhatsApp message
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
            "action": {"buttons": [{"type": "reply", "reply": {"id": b, "title": sanitize_title(b)}} for b in options]}
        }
    elif opt_type == "list" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "list",
            "body": {"text": message_text},
            "action": {
                "button": "Choose",
                "sections": [{"title": "Options", "rows": [{"id": b, "title": sanitize_title(b)} for b in options]}]
            }
        }
    else:
        payload["type"] = "text"
        payload["text"] = {"body": message_text}

    resp = requests.post(url, headers=headers, json=payload)
    print(f"📤 Send message response: {resp.status_code} {resp.text}")
    return resp.json()

# Schedule 1-hour follow-up if inactive
def schedule_followup(user_id):
    def followup():
        try:
            followup_timeout = 3600  # 1 hour
            time.sleep(followup_timeout)
            last = LAST_ACTIVE.get(user_id)
            if last and time.time() - last >= followup_timeout:
                msg = MENU.get("rules", {}).get("follow_up", "Knock Knock 👋 Are you there?")
                send_whatsapp_message(user_id, msg)
        except Exception as e:
            print("⚠️ Follow-up thread error:", e)
    threading.Thread(target=followup, daemon=True).start()

# Clean input text
def clean_msg(text):
    if not text:
        return ""
    return text.replace("\n", " ").replace("\r", " ").strip()

# Handle 'Restart'
def handle_restart(user_id, user_text):
    if user_text.strip().lower() in ["restart", "पुन्हा सुरू करा"]:
        USER_STATE[user_id] = {"stage": "INIT", "language": None, "current_menu": "opening", "expecting_reply": True}
        send_opening_menu(user_id)
        return True
    return False

# Send opening menu
def send_opening_menu(user_id):
    opening = MENU["opening"]
    lang = "en"
    buttons = [b["id"] for b in opening["buttons"]]
    send_whatsapp_message(user_id, opening["msg"], buttons, "buttons")

# Find menu node
def find_menu_item_by_id(menu_id):
    if menu_id == "opening":
        return MENU.get("opening")
    return MENU.get("menus", {}).get(menu_id)

# === Webhook routes ===
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed ❌", 403

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
                    LAST_ACTIVE[from_number] = time.time()
                    schedule_followup(from_number)

                    msg_body, user_text = None, None
                    if "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = interactive["button_reply"]["id"]
                        elif interactive["type"] == "list_reply":
                            msg_body = interactive["list_reply"]["id"]
                    if msg.get("text"):
                        user_text = clean_msg(msg["text"].get("body"))

                    # Restart
                    if user_text and handle_restart(from_number, user_text):
                        continue

                    # Interactive reply
                    if msg_body:
                        handle_user_input(from_number, msg_body)
                        continue

                    # Free text (language selection)
                    if user_text:
                        handle_free_text(from_number, user_text)
                        continue

    return jsonify({"status": "ok"}), 200

# Handle free text (language)
def handle_free_text(user_id, user_text):
    state = USER_STATE.get(user_id, {"stage": "INIT", "language": None, "current_menu": "opening", "expecting_reply": False})
    if state["stage"] == "INIT":
        lang_text = user_text.lower()
        if lang_text in ["english", "english"]:
            USER_STATE[user_id] = {"stage": "LANG_SELECTED", "language": "en", "current_menu": "main_menu", "expecting_reply": True}
            send_menu_by_id(user_id, "main_menu", "en")
            return
        elif lang_text in ["marathi", "मराठी"]:
            USER_STATE[user_id] = {"stage": "LANG_SELECTED", "language": "mr", "current_menu": "main_menu", "expecting_reply": True}
            send_menu_by_id(user_id, "main_menu", "mr")
            return
    send_opening_menu(user_id)

# Handle user input
def handle_user_input(user_id, selected_id):
    state = USER_STATE.get(user_id, {"stage": "INIT", "language": None, "current_menu": "opening", "expecting_reply": False})
    lang = state.get("language") or "en"
    item = find_menu_item_by_id(selected_id)
    if not item:
        send_menu_by_id(user_id, state.get("current_menu", "main_menu"), lang)
        return
    USER_STATE[user_id]["current_menu"] = selected_id
    USER_STATE[user_id]["expecting_reply"] = True
    send_menu_item(user_id, item, lang)

# Send menu by ID
def send_menu_by_id(user_id, menu_id, lang):
    item = find_menu_item_by_id(menu_id)
    if item:
        send_menu_item(user_id, item, lang)
    else:
        send_menu_item(user_id, find_menu_item_by_id("main_menu"), lang)

# Send menu item
def send_menu_item(user_id, item, lang):
    msg_text = item.get("msg")
    if isinstance(msg_text, dict):
        msg_text = msg_text.get(lang, msg_text.get("en", ""))

    # Options/buttons
    options = []
    opt_type = "text"
    if "options" in item:
        options = [o["id"] for o in item["options"]]
        opt_type = "list"
    elif "buttons" in item:
        options = [b["id"] for b in item["buttons"]]
        opt_type = "buttons" if len(options) <= 3 else "list"

    send_whatsapp_message(user_id, msg_text, options, opt_type)

@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
