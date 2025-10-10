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

# Send WhatsApp message with proper formatting
def send_whatsapp_message(to, message_text, options=None, opt_type="text"):
    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"messaging_product": "whatsapp", "to": to}

    if opt_type == "buttons" and options and len(options) <= 3:
        payload["type"] = "interactive"
        payload["interactive"] = {
            "type": "button",
            "body": {"text": message_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": opt["id"], "title": sanitize_title(opt["title"])}} 
                    for opt in options
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
                    "rows": [
                        {
                            "id": opt["id"], 
                            "title": sanitize_title(opt["title"]),
                            **({'description': opt["description"][:72]} if "description" in opt else {})
                        }
                        for opt in options
                    ]
                }]
            }
        }
    else:
        payload["type"] = "text"
        payload["text"] = {"body": message_text}

    resp = requests.post(url, headers=headers, json=payload)
    print(f"📤 Send message response: {resp.status_code} {resp.text}")
    return resp.json()

# Idle check for each user
def schedule_idle_check(user_id):
    def idle_checker():
        try:
            while True:
                time.sleep(30)  # check every 30s
                last = LAST_ACTIVE.get(user_id)
                if not last:
                    return  # no activity yet

                idle_time = time.time() - last
                state = USER_STATE.get(user_id, {})
                lang = state.get("language", "en")

                # Case 1: 3 min idle → follow-up
                if 180 <= idle_time < 300: #if 180 <= idle_time < 300:
                    if not state.get("warned"):  # send only once
                        follow_msg = MENU.get("rules", {}).get("follow_up", {})
                        msg_text = follow_msg.get(lang, follow_msg.get("en", "Are you still there?"))
                        send_whatsapp_message(user_id, msg_text)
                        USER_STATE.setdefault(user_id, {})["warned"] = True

                # Case 2: 5 min idle → session close
                elif idle_time >= 300:
                    close_msg = MENU.get("rules", {}).get("session_close", {})
                    msg_text = close_msg.get(lang, close_msg.get("en", "Session closed. Please say anything to restart."))
                    send_whatsapp_message(user_id, msg_text)

                    # Reset state
                    USER_STATE[user_id] = {
                        "stage": "INIT",
                        "language": None,
                        "current_menu": "opening",
                        "expecting_reply": False,
                        "warned": False
                    }
                    LAST_ACTIVE[user_id] = None
                    return  # stop checking for this user

        except Exception as e:
            print("⚠️ Idle checker error:", e)

    threading.Thread(target=idle_checker, daemon=True).start()

# Clean input text
def clean_msg(text):
    if not text:
        return ""
    return text.replace("\n", " ").replace("\r", " ").strip()

# Handle 'Restart'
def handle_restart(user_id, user_text):
    restart_keywords = ["restart", "पुन्हा सुरू करा", "start", "begin", "सुरू करा"]
    if user_text.strip().lower() in restart_keywords:
        USER_STATE[user_id] = {
            "stage": "INIT", 
            "language": None, 
            "current_menu": "opening", 
            "expecting_reply": True
        }
        send_opening_menu(user_id)
        return True
    return False

# Send opening menu
def send_opening_menu(user_id):
    opening = MENU["opening"]
    buttons = [
        {"id": btn["id"], "title": btn["Value"]} 
        for btn in opening["buttons"]
    ]
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
    print("Webhook triggered!")
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
                    schedule_idle_check(from_number)

                    msg_body, user_text = None, None
                    
                    # Handle interactive messages (buttons/lists)
                    if "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = interactive["button_reply"]["id"]
                        elif interactive["type"] == "list_reply":
                            msg_body = interactive["list_reply"]["id"]
                    
                    # Handle text messages
                    if msg.get("text"):
                        user_text = clean_msg(msg["text"].get("body"))

                    # Check for restart command
                    if user_text and handle_restart(from_number, user_text):
                        continue

                    # Handle interactive reply (button/list selection)
                    if msg_body:
                        handle_user_input(from_number, msg_body)
                        continue

                    # Handle free text (for language selection or unknown input)
                    if user_text:
                        handle_free_text(from_number, user_text)
                        continue

    return jsonify({"status": "ok"}), 200

# Handle free text input
def handle_free_text(user_id, user_text):
    # Always get state with defaults
    state = USER_STATE.setdefault(user_id, {
        "stage": "INIT",
        "language": None,
        "current_menu": "opening",
        "expecting_reply": False,
        "warned": False
    })

    # Language selection via text
    if state.get("stage") == "INIT" or state.get("current_menu") == "opening":
        lang_text = user_text.lower()
        if "english" in lang_text or lang_text == "en":
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": "en",
                "current_menu": "main_menu",
                "expecting_reply": True,
                "warned": False
            }
            send_menu_by_id(user_id, "main_menu", "en")
            return
        elif "marathi" in lang_text or "मराठी" in lang_text or lang_text == "mr":
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": "mr",
                "current_menu": "main_menu",
                "expecting_reply": True,
                "warned": False
            }
            send_menu_by_id(user_id, "main_menu", "mr")
            return

    # Unknown input - resend current menu or opening
    lang = state.get("language", "en")
    current_menu = state.get("current_menu", "opening")
    # --- NEW: handle 'help' input ---
    if user_text.strip().lower() == "help":
        send_menu_by_id(user_id, "help", lang)
        return 
    
    if current_menu == "opening" or not state.get("language"):
        send_opening_menu(user_id)
    else:
        help_msg = {
            "en": "Please use the buttons below to continue:",
            "mr": "कृपया पुढे जाण्यासाठी खालील बटणे वापरा:"
        }
        send_whatsapp_message(user_id, help_msg.get(lang, help_msg["en"]))
        send_menu_by_id(user_id, current_menu, lang)


# Handle user button/list input
def handle_user_input(user_id, selected_id):
    state = USER_STATE.get(user_id, {
        "stage": "INIT", 
        "language": None, 
        "current_menu": "opening", 
        "expecting_reply": False
    })
    
    # Handle language selection buttons
    if selected_id == "language_en":
        USER_STATE[user_id] = {
            "stage": "LANG_SELECTED", 
            "language": "en", 
            "current_menu": "main_menu", 
            "expecting_reply": True
        }
        send_menu_by_id(user_id, "main_menu", "en")
        return
    elif selected_id == "language_mr":
        USER_STATE[user_id] = {
            "stage": "LANG_SELECTED", 
            "language": "mr", 
            "current_menu": "main_menu", 
            "expecting_reply": True
        }
        send_menu_by_id(user_id, "main_menu", "mr")
        return
    
    # Get language
    lang = state.get("language") or "en"
    
    # Find the selected menu item
    item = find_menu_item_by_id(selected_id)
    if not item:
        # Invalid selection - resend current menu
        send_menu_by_id(user_id, state.get("current_menu", "main_menu"), lang)
        return
    
    # Update state
    USER_STATE[user_id]["current_menu"] = selected_id
    USER_STATE[user_id]["expecting_reply"] = True
    
    # Send the selected menu
    send_menu_item(user_id, item, lang)

# Send menu by ID
def send_menu_by_id(user_id, menu_id, lang):
    item = find_menu_item_by_id(menu_id)
    if item:
        send_menu_item(user_id, item, lang)
    else:
        send_menu_item(user_id, find_menu_item_by_id("main_menu"), lang)

# Send menu item with proper button/list formatting
def send_menu_item(user_id, item, lang):
    # Get message text based on language
    msg_text = item.get("msg")
    if isinstance(msg_text, dict):
        msg_text = msg_text.get(lang, msg_text.get("en", ""))

   

    # Prepare options/buttons
    options = []
    opt_type = "text"
    
    if "options" in item:
        options = []
        for opt in item["options"]:
            row = {
                "id": opt["id"],
                "title": opt.get(lang, opt.get("en", opt["id"]))
            }
            # Include description if present
            if "desc" in opt:
                desc = ""
                if isinstance(opt["desc"], dict):
                    desc = opt["desc"].get(lang, opt["desc"].get("en", ""))
                elif isinstance(opt["desc"], str):
                    desc = opt["desc"].strip()
                if desc:
                    row["description"] = desc
            options.append(row)
        opt_type = "list"
    elif "buttons" in item:
        # Button options
        options = [
            {"id": btn["id"], "title": btn.get(lang, btn.get("en", btn["id"]))} 
            for btn in item["buttons"]
        ]
        opt_type = "buttons" if len(options) <= 3 else "list"

    send_whatsapp_message(user_id, msg_text, options, opt_type)

@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)