from flask import Flask, request, jsonify
import requests
import os
import json
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

# In-memory user state and last active timestamp
USER_STATE = {}
LAST_ACTIVE = {}

# Helper to sanitize titles (max 20 chars)
def sanitize_title(title):
    return str(title).strip()[:20] if title else "Option"

# Send WhatsApp message using Cloud API
def send_whatsapp_message(to, message_text, options=None, opt_type="text"):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to
    }

    if opt_type == "buttons" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "button",
            "body": {"text": message_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": str(i), "title": sanitize_title(b)}}
                    for i, b in enumerate(options, 1)
                ]
            }
        }
    elif opt_type == "list" and options:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "list",
            "body": {"text": message_text},
            "action": {
                "button": "Choose",
                "sections": [{
                    "title": "Options",
                    "rows": [{"id": str(i), "title": sanitize_title(b)} for i, b in enumerate(options, 1)]
                }]
            }
        }
    else:
        payload["type"] = "text"
        payload["text"] = {"body": message_text}

    resp = requests.post(url, headers=headers, json=payload)
    print("📤 Send message response:", resp.status_code, resp.text)
    return resp.json()

# Schedule follow-up message if no activity for 1 hour
def schedule_followup(user_id):
    def followup():
        try:
            followup_timeout = 3600  # 1 hour in seconds
            time.sleep(followup_timeout)
            last = LAST_ACTIVE.get(user_id)
            if last and time.time() - last >= followup_timeout:
                # Use follow up message from rules or default fallback
                msg = MENU.get("rules", {}).get("follow_up", "Knock Knock 👋 Are you there?")
                send_whatsapp_message(user_id, msg)
        except Exception as e:
            print("⚠️ Follow-up thread error:", e)
    threading.Thread(target=followup, daemon=True).start()

# Sanitize incoming text
def clean_msg(text):
    if not text:
        return ""
    return text.replace("\n", " ").replace("\r", " ").strip()

# Handle restart command
def handle_restart(user_id, user_text):
    if user_text.strip().lower() in ["restart", "पुन्हा सुरू करा"]:
        USER_STATE[user_id] = {
            "stage": "INIT",
            "language": None,
            "current_menu": "opening",
            "expecting_reply": True
        }
        # Send opening message with buttons
        send_whatsapp_message(user_id, MENU["opening"]["msg"], [btn["Value"] for btn in MENU["opening"]["buttons"]], "buttons")
        return True
    return False

# Webhook verify GET request
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed ❌", 403

# Webhook POST - message handler
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
                            msg_body = clean_msg(interactive["button_reply"]["title"])
                        elif interactive["type"] == "list_reply":
                            msg_body = clean_msg(interactive["list_reply"]["title"])

                    if msg.get("text"):
                        user_text = clean_msg(msg["text"].get("body"))

                    # Restart handling
                    if user_text and handle_restart(from_number, user_text):
                        continue

                    # Handle interactive button/list reply
                    if msg_body:
                        handle_user_input(from_number, msg_body)
                        continue

                    # Handle free text input
                    if user_text:
                        handle_free_text(from_number, user_text)
                        continue

    return jsonify({"status": "ok"}), 200

# Handle free text input (e.g., language selection on init)
def handle_free_text(user_id, user_text):
    state = USER_STATE.get(user_id, {
        "stage": "INIT",
        "language": None,
        "current_menu": "opening",
        "expecting_reply": False
    })
    supported_languages = [l.lower() for l in ["English", "Marathi"]]

    if state["stage"] == "INIT":
        if user_text.lower() in supported_languages:
            lang = "English" if user_text.lower() == "english" else "Marathi"
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": lang,
                "current_menu": "main_menu",
                "expecting_reply": True
            }
            send_bot_message(user_id)
        else:
            # Resend opening menu
            send_whatsapp_message(user_id, MENU["opening"]["msg"], [btn["Value"] for btn in MENU["opening"]["buttons"]], "buttons")
        return

    # If not INIT, fallback and resend current menu
    send_whatsapp_message(user_id, "Sorry, I did not understand. Please select from the menu.")
    send_bot_message(user_id)

# Handle user interactive input (buttons or lists)
def handle_user_input(user_id, msg_text):
    clean_text = msg_text.lower()
    state = USER_STATE.get(user_id, {
        "stage": "INIT",
        "language": None,
        "current_menu": "opening",
        "expecting_reply": False
    })
    lang = state.get("language") or "English"
    current_menu = state.get("current_menu") or "opening"
    lang_key = "en" if lang == "English" else "mr"

    # Language selection on opening menu
    if current_menu == "opening":
        if clean_text in ["english", "इंग्रजी"]:
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": "English",
                "current_menu": "main_menu",
                "expecting_reply": True
            }
            send_whatsapp_message(user_id, MENU["language_selected"]["en"], [opt["en"] for opt in MENU["main_menu"]["options"]], "list")
            return
        elif clean_text in ["marathi", "मराठी"]:
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": "Marathi",
                "current_menu": "main_menu",
                "expecting_reply": True
            }
            send_whatsapp_message(user_id, MENU["language_selected"]["mr"], [opt["mr"] for opt in MENU["main_menu"]["options"]], "list")
            return

    # Change language
    if clean_text in ["change language", "भाषा बदल"]:
        USER_STATE[user_id] = {
            "stage": "INIT",
            "language": None,
            "current_menu": "opening",
            "expecting_reply": True
        }
        send_whatsapp_message(user_id, MENU["opening"]["msg"], [btn["Value"] for btn in MENU["opening"]["buttons"]], "buttons")
        return

    # Using current_menu to fetch menu details from JSON
    current_menu_data = MENU.get(current_menu, {})

    # Check options in current menu to match reply and navigate
    if "options" in current_menu_data:
        for opt in current_menu_data["options"]:
            # Match user text with option in current language
            option_text = opt.get(lang_key, "").strip().lower()
            if clean_text == option_text:
                USER_STATE[user_id]["current_menu"] = opt["id"]
                USER_STATE[user_id]["expecting_reply"] = True
                send_bot_message(user_id)
                return
    # Check buttons in current menu similarly
    if "buttons" in current_menu_data:
        for btn in current_menu_data["buttons"]:
            btn_text = btn.get("Value", "").strip().lower()
            if clean_text == btn_text:
                # Buttons might not have submenus; just resend or handle accordingly
                send_bot_message(user_id)
                return

    # Fallback if input not recognized
    send_whatsapp_message(user_id, "Sorry, I did not understand. Please select a valid option.")
    send_bot_message(user_id)

# Send bot message based on current state and menu
def send_bot_message(user_id):
    state = USER_STATE.get(user_id)
    if not state:
        # Reset state if missing
        USER_STATE[user_id] = {
            "stage": "INIT",
            "language": None,
            "current_menu": "opening",
            "expecting_reply": True
        }
        send_whatsapp_message(user_id, MENU.get("opening", {}).get("msg", "Welcome!"), [btn["Value"] for btn in MENU.get("opening", {}).get("buttons", [])], "buttons")
        return

    current_menu = state.get("current_menu")
    lang = state.get("language") or "English"
    lang_key = "en" if lang == "English" else "mr"

    menu_data = MENU.get(current_menu, {})
    if not menu_data:
        # If no menu data, fallback to main menu
        USER_STATE[user_id]["current_menu"] = "main_menu"
        menu_data = MENU.get("main_menu", {})

    # Message text
    text = ""
    if "msg" in menu_data:
        if isinstance(menu_data["msg"], dict):
            text = menu_data["msg"].get(lang_key, menu_data["msg"].get("en", ""))
        else:
            text = menu_data["msg"]

    # Options/buttons text
    options = []
    opt_type = "text"
    if "options" in menu_data:
        options = [opt[lang_key] for opt in menu_data["options"]]
        opt_type = "list"
        state["expecting_reply"] = True
    elif "buttons" in menu_data:
        options = [btn["Value"] for btn in menu_data["buttons"]]
        opt_type = "buttons"
        state["expecting_reply"] = True
    else:
        state["expecting_reply"] = False

    send_whatsapp_message(user_id, text, options, opt_type)

# Home route
@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
