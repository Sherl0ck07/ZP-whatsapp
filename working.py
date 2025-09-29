from flask import Flask, request, jsonify
import requests, os, json, threading, time

# === Load JSON Flow ===
with open("zp_buldhana_flow.json") as f:
    MENU = json.load(f)

with open("credentials.json", "r") as f:
    creds = json.load(f)

ACCESS_TOKEN = creds.get("ACCESS_TOKEN")
VERIFY_TOKEN = creds.get("VERIFY_TOKEN")
PHONE_NUMBER_ID = creds.get("PHONE_NUMBER_ID")

app = Flask(__name__)

# In-memory state and last active timestamp
USER_STATE = {}
LAST_ACTIVE = {}

def handle_restart(user_id, user_text):
    """
    Check if the user wants to restart the bot and reset state accordingly.
    """
    if user_text.strip().lower() in ["restart", "पुन्हा सुरू करा"]:
        # Reset user state
        USER_STATE[user_id] = {
            "stage": "INIT",
            "language": None,
            "current_menu": "opening",
            "expecting_reply": True
        }

        # Send restart confirmation
        lang = MENU["default_language"]
        restart_msg = MENU["restart"]["msg"].get(lang, "Restarting the bot...")
        send_whatsapp_message(user_id, restart_msg)

        return True  # restart handled

    return False




# === Helper Functions ===

def sanitize_title(title):
    return str(title).strip()[:20] if title else "Option"

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
            "action": {
                "button": "Choose",
                "sections": [{"title": "Options", 
                              "rows": [{"id": str(i), "title": sanitize_title(b)} 
                                       for i, b in enumerate(options, 1)]}]
            }
        }
    else:
        payload["text"] = {"body": message_text}

    resp = requests.post(url, headers=headers, json=payload)
    print("📤 Send message response:", resp.status_code, resp.text)
    return resp.json()

def schedule_followup(user_id):
    def followup():
        time.sleep(MENU["timed_followup"]["timeout"])
        last = LAST_ACTIVE.get(user_id)
        if last and time.time() - last >= MENU["timed_followup"]["timeout"]:
            lang = USER_STATE.get(user_id, {}).get("language", MENU["default_language"])
            msg = MENU["timed_followup"]["msg"].get(lang, "Are you still there?")
            send_whatsapp_message(user_id, msg)
    threading.Thread(target=followup).start()

# === Webhook Verification ===
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed ❌", 403

# === Helper Function to Clean Incoming Messages ===
def clean_msg(text):
    """Remove newlines, carriage returns, extra spaces and lowercase the text."""
    if not text:
        return ""
    return text.replace("\n", "").replace("\r", "").strip().lower()

# === Webhook Message Handler ===
# --- Webhook Message Handler ---
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

                    msg_body = None
                    user_text = None

                    if "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = clean_msg(interactive["button_reply"]["title"])
                        elif interactive["type"] == "list_reply":
                            msg_body = clean_msg(interactive["list_reply"]["title"])

                    if msg.get("text"):
                        user_text = clean_msg(msg["text"].get("body"))

                    # --- Restart Command ---
                    if user_text:
                        if handle_restart(from_number, user_text):
                            send_bot_message(from_number)   # show opening menu

                            continue

                    # --- Handle input ---
                    if msg_body:
                        handle_user_input(from_number, msg_body)
                        continue

                    if user_text:
                        handle_free_text(from_number, user_text)
                        continue

    return jsonify({"status": "ok"}), 200


# === Handle Free Text / Fallback ===
def handle_free_text(user_id, user_text):
    state = USER_STATE.get(user_id, {"stage": "INIT", "language": None, "current_menu": "opening", "expecting_reply": False})

    if state["stage"] == "INIT":
        if user_text.lower() in [l.lower() for l in MENU["languages"]]:
            USER_STATE[user_id] = {"stage": "LANG_SELECTED", "language": user_text, "current_menu": "main_menu", "expecting_reply": True}
            send_bot_message(user_id)
        else:
            lang = MENU["default_language"]
            send_whatsapp_message(user_id, MENU["opening"]["msg"], MENU["opening"]["buttons"], "buttons")
        return

    if state.get("expecting_reply", False):
        lang = state.get("language", MENU["default_language"])
        reply_text = MENU["fallback"]["msg"].get(lang)
        send_whatsapp_message(user_id, reply_text)
        send_bot_message(user_id)
    else:
        send_bot_message(user_id)

# === Handle User Input ===
# === Handle User Input ===
def handle_user_input(user_id, msg_text):
    msg_text_clean = clean_msg(msg_text)

    state = USER_STATE.get(user_id, {
        "stage": "INIT",
        "language": None,
        "current_menu": "initial_greet",
        "expecting_reply": False
    })

    # --- Initial Stage: Language Selection ---
    if state["stage"] == "INIT":
        if msg_text_clean in ["english", "marathi", "इंग्रजी", "मराठी"]:
            lang = "English" if msg_text_clean in ["english", "इंग्रजी"] else "Marathi"
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": lang,
                "current_menu": "main_menu",
                "expecting_reply": True
            }
            send_bot_message(user_id)
            return
        else:
            # Invalid language, resend opening
            menu_data = MENU["opening"]["English"]
            send_whatsapp_message(user_id, menu_data["msg"], menu_data.get("buttons", []), "buttons")
            return

    # --- Change Language Command (handle before other buttons) ---
    if msg_text_clean in ["change language", "भाषा बदल"]:
        USER_STATE[user_id] = {
            "stage": "INIT",
            "language": None,
            "current_menu": "opening",
            "expecting_reply": True
        }
        # Send language selection directly
        lang = "English"  # Use default for opening message
        menu_data = MENU["opening"]
        send_whatsapp_message(user_id, menu_data["msg"], menu_data.get("buttons", []), "buttons")
        return

    # --- Menu Navigation ---
    current_menu = state.get("current_menu")
    lang = state.get("language") or MENU["default_language"]
    menu_data = MENU["flow"][lang].get(current_menu, {})

    if not menu_data:
        send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
        return

    # --- Options Handling ---
    if "options" in menu_data:
        for opt in menu_data["options"]:
            if msg_text_clean == clean_msg(opt["label"]):
                USER_STATE[user_id]["current_menu"] = opt["key"]
                USER_STATE[user_id]["expecting_reply"] = True
                send_bot_message(user_id)
                return

    # --- Buttons Handling ---
    if "buttons" in menu_data:
        button_mapping = {
            "main menu": "main_menu", "मुख्य मेनू": "main_menu",
            "about zp": "about_zp", "जि.प. बद्दल": "about_zp",
            "departments": "departments", "विभाग": "departments",
            "schemes": "schemes", "योजना": "schemes",
            "cess fund": "cess_fund", "सेस फंड": "cess_fund",
            "officers contact": "officers_contact", "अधिकारी यांचे संपर्क": "officers_contact",
            "online complaint": "online_complaint", "ऑनलाईन तक्रार": "online_complaint",
            "citizens charter": "citizens_charter", "नागरिकांची सनद": "citizens_charter"
        }

        selected_key = button_mapping.get(msg_text_clean)
        if selected_key:
            USER_STATE[user_id]["current_menu"] = selected_key
            USER_STATE[user_id]["expecting_reply"] = True
            send_bot_message(user_id)
            return

    # --- Fallback if reply invalid ---
    if state.get("expecting_reply", False):
        send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
        send_bot_message(user_id)

def send_bot_message(user_id):
    state = USER_STATE[user_id]
    current_menu = state.get("current_menu")
    
    # Store last valid menu
    if current_menu:
        USER_STATE[user_id]["last_menu"] = current_menu

    lang = state.get("language") or MENU["default_language"]

    if current_menu in MENU["flow"][lang]:
        menu_data = MENU["flow"][lang][current_menu]
    else:
        send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
        return

    text = menu_data.get("msg", "")
    options, opt_type = [], "text"

    if "options" in menu_data:
        options = [o["label"] for o in menu_data["options"]]
        opt_type = "list"
        state["expecting_reply"] = True
    elif "buttons" in menu_data:
        options = menu_data["buttons"]
        opt_type = "buttons"
        state["expecting_reply"] = True
    else:
        state["expecting_reply"] = False

    send_whatsapp_message(user_id, text, options, opt_type)
    USER_STATE[user_id] = state




# === Send Department / Scheme Info ===
def send_info(user_id, key, lang):
    # Check department details
    dept_data = MENU["flow"][lang].get("department_details", {}).get(key)
    if dept_data:
        text = dept_data.get("msg", "")
        options = dept_data.get("buttons", [])
        contact = dept_data.get("contact")
        if contact:
            text += f"\n📞 {contact['designation']}: {contact['name']} - {contact['phone']}"
        send_whatsapp_message(user_id, text, options, "buttons")
        USER_STATE[user_id]["expecting_reply"] = True
        return
    # Otherwise fallback
    send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
    USER_STATE[user_id]["expecting_reply"] = True

# === Root Endpoint ===
@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200

# === Run App ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
