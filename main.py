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

# === Webhook Message Handler ===
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

                    # Interactive messages
                    msg_body = None
                    if "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = interactive["button_reply"]["title"]
                        elif interactive["type"] == "list_reply":
                            msg_body = interactive["list_reply"]["title"]

                    user_text = msg.get("text", {}).get("body", "").strip() if msg.get("text") else None

                    # --- Restart Command ---
                    if user_text and user_text.lower() in ["restart", "पुन्हा सुरू करा"]:
                        lang = USER_STATE.get(from_number, {}).get("language", MENU["default_language"])
                        USER_STATE[from_number] = {"stage": "INIT", "language": None, "current_menu": "opening", "expecting_reply": True}
                        send_whatsapp_message(from_number, MENU["restart"]["msg"].get(lang))
                        send_bot_message(from_number)
                        continue

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
            send_whatsapp_message(user_id, MENU["opening"][lang]["msg"], MENU["opening"][lang]["buttons"], "buttons")
        return

    if state.get("expecting_reply", False):
        lang = state.get("language", MENU["default_language"])
        reply_text = MENU["fallback"]["msg"].get(lang)
        send_whatsapp_message(user_id, reply_text)
        send_bot_message(user_id)
    else:
        send_bot_message(user_id)

# === Handle User Input ===
def handle_user_input(user_id, msg_text):
    state = USER_STATE.get(user_id, {"stage": "INIT", "language": None, "current_menu": "initial_greet", "expecting_reply": False})

    # --- Initial Stage: Language Selection ---
    if state["stage"] == "INIT":
        if msg_text.lower() in ["english", "marathi", "इंग्रजी", "मराठी"]:
            lang = "English" if msg_text.lower() in ["english", "इंग्रजी"] else "Marathi"
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": lang,
                "current_menu": "main_menu",
                "expecting_reply": True
            }
            send_bot_message(user_id)
        else:
            # Re-send opening message if invalid
            menu_data = MENU["opening"]["English"]  # default English
            send_whatsapp_message(user_id, menu_data["msg"], menu_data.get("buttons", []), "buttons")
        return

    # --- Change Language ---
    if msg_text.lower() in ["change language", "भाषा बदल"]:
        USER_STATE[user_id] = {
            "stage": "INIT",
            "language": None,
            "current_menu": "initial_greet",
            "expecting_reply": False
        }
        send_bot_message(user_id)
        return

    # --- Menu Navigation ---
    current_menu = state.get("current_menu")
    lang = state.get("language") or MENU["default_language"]
    menu_data = MENU["flow"][lang].get(current_menu, {})

    if not menu_data:
        send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
        return

    # --- Options Handling ---
    options = []
    if "options" in menu_data:
        options = [o["label"] for o in menu_data["options"]]
        for opt in menu_data["options"]:
            if msg_text.strip().lower() == opt["label"].strip().lower():
                USER_STATE[user_id]["current_menu"] = opt["key"]
                USER_STATE[user_id]["expecting_reply"] = True
                send_bot_message(user_id)
                return

    # --- Buttons Handling ---
    if "buttons" in menu_data:
        if msg_text.strip() in menu_data["buttons"]:
            # Move back to parent menu if needed
            send_bot_message(user_id)
            return

    # --- If reply invalid and bot expects input ---
    if state.get("expecting_reply", False):
        send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
        send_bot_message(user_id)


def send_bot_message(user_id):
    state = USER_STATE[user_id]
    current_menu = state.get("current_menu")
    lang = state.get("language") or MENU["default_language"]

    # Opening menu (language selection)
    if current_menu == "initial_greet":
        menu_data = MENU["opening"].get(lang, {})
    else:
        menu_data = MENU["flow"].get(lang, {}).get(current_menu, {})

    if not menu_data:
        send_whatsapp_message(user_id, MENU["fallback"]["msg"].get(lang, "Sorry, I didn't understand that."))
        return

    text = menu_data.get("msg", "")
    options, opt_type = [], "text"

    if current_menu == "initial_greet":
        options = menu_data.get("buttons", [])
        opt_type = "buttons"
        USER_STATE[user_id]["expecting_reply"] = True
    elif "options" in menu_data:
        options = [o["label"] for o in menu_data["options"]]
        opt_type = "list"
        USER_STATE[user_id]["expecting_reply"] = True
    elif "buttons" in menu_data:
        options = menu_data["buttons"]
        opt_type = "buttons"
        USER_STATE[user_id]["expecting_reply"] = True
    else:
        USER_STATE[user_id]["expecting_reply"] = False

    send_whatsapp_message(user_id, text, options, opt_type)


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
