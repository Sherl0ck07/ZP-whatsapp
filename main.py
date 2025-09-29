from flask import Flask, request, jsonify
import requests, os, json, threading, time

# === Load JSON Flow ===
with open("zp_buldhana_flow.json", "r", encoding="utf-8") as f:
    MENU = json.load(f)

with open("credentials.json", "r") as f:
    creds = json.load(f)

ACCESS_TOKEN = creds.get("ACCESS_TOKEN")
VERIFY_TOKEN = creds.get("VERIFY_TOKEN")
PHONE_NUMBER_ID = creds.get("PHONE_NUMBER_ID")

app = Flask(__name__)

# In-memory user state
USER_STATE = {}
LAST_ACTIVE = {}

# === Helper ===
def sanitize_title(title):
    return str(title).strip()[:20] if title else "Option"

def clean_msg(text):
    return text.replace("\n", "").replace("\r", "").strip().lower() if text else ""

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
    print("📤 Send:", resp.status_code, resp.text)
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

# === Incoming Webhook Handler ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Webhook:", json.dumps(data, indent=2, ensure_ascii=False))

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

                    # Interactive replies
                    if "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = clean_msg(interactive["button_reply"]["title"])
                        elif interactive["type"] == "list_reply":
                            msg_body = clean_msg(interactive["list_reply"]["title"])

                    if msg.get("text"):
                        user_text = clean_msg(msg["text"].get("body"))

                    # Restart
                    if user_text in ["restart", "पुन्हा सुरू करा"]:
                        restart_bot(from_number)
                        continue

                    if msg_body:
                        handle_user_input(from_number, msg_body)
                        continue

                    if user_text:
                        handle_free_text(from_number, user_text)
                        continue

    return jsonify({"status": "ok"}), 200

# === Restart handler ===
def restart_bot(user_id):
    lang = USER_STATE.get(user_id, {}).get("language", MENU["default_language"])
    USER_STATE[user_id] = {"stage": "INIT", "language": None, "current_menu": "opening",
                           "expecting_reply": True, "last_menu": "opening"}
    send_whatsapp_message(user_id, MENU["restart"]["msg"].get(lang))
    send_bot_message(user_id)

# === Free Text / Fallback ===
def handle_free_text(user_id, user_text):
    state = USER_STATE.get(user_id, {"stage": "INIT","language": None,
            "current_menu": "opening","expecting_reply": False,"last_menu": "opening"})

    lang = state.get("language") or MENU["default_language"]

    if state["stage"] == "INIT":
        # Language selection
        if user_text.lower() in [l.lower() for l in MENU["languages"]]:
            USER_STATE[user_id] = {"stage": "LANG_SELECTED","language": user_text.title(),
                                   "current_menu": "main_menu","expecting_reply": True,
                                   "last_menu": "main_menu"}
            send_bot_message(user_id)
        else:
            # Re-show language selection
            opening = MENU["opening"]
            send_whatsapp_message(user_id, opening["msg"], opening.get("buttons", []), "buttons")
        return

    # Fallback case
    send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
    last_menu = state.get("last_menu", "main_menu")
    USER_STATE[user_id]["current_menu"] = last_menu
    send_bot_message(user_id)

# === User Input Handler ===
def handle_user_input(user_id, msg_text):
    text = clean_msg(msg_text)
    state = USER_STATE.get(user_id, {"stage":"INIT","language":None,
                                     "current_menu":"opening","expecting_reply":False})

    # Language selection
    if state["stage"] == "INIT":
        if text in ["english","marathi","इंग्रजी","मराठी"]:
            lang = "English" if text in ["english","इंग्रजी"] else "Marathi"
            USER_STATE[user_id] = {"stage":"LANG_SELECTED","language":lang,
                                   "current_menu":"main_menu","expecting_reply":True,
                                   "last_menu":"main_menu"}
            send_bot_message(user_id)
            return
        else:
            opening = MENU["opening"]
            send_whatsapp_message(user_id, opening["msg"], opening.get("buttons", []), "buttons")
            return

    # Change Language
    if text in ["change language", "भाषा बदल"]:
        restart_bot(user_id)
        return

    # Menu navigation
    lang = state.get("language") or MENU["default_language"]
    current_menu = state.get("current_menu")
    menu_data = MENU["flow"][lang].get(current_menu, {})

    if "options" in menu_data:
        for opt in menu_data["options"]:
            if text == clean_msg(opt["label"]):
                USER_STATE[user_id]["current_menu"] = opt["key"]
                USER_STATE[user_id]["last_menu"] = current_menu
                send_bot_message(user_id)
                return

    if "buttons" in menu_data:
        if text in [clean_msg(b) for b in menu_data["buttons"]]:
            USER_STATE[user_id]["current_menu"] = [k for k,v in menu_data.items()][0]
            send_bot_message(user_id)
            return

    # Fallback
    send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
    last_menu = state.get("last_menu", "main_menu")
    USER_STATE[user_id]["current_menu"] = last_menu
    send_bot_message(user_id)

# === Send Bot Menu ===
def send_bot_message(user_id):
    state = USER_STATE[user_id]
    lang = state.get("language") or MENU["default_language"]
    current_menu = state.get("current_menu")

    if current_menu in MENU["flow"][lang]:
        menu_data = MENU["flow"][lang][current_menu]
    else:
        send_whatsapp_message(user_id, MENU["fallback"]["msg"][lang])
        return

    USER_STATE[user_id]["last_menu"] = current_menu
    text = menu_data.get("msg", "")
    options, opt_type = [], "text"
    if "options" in menu_data:
        options = [o["label"] for o in menu_data["options"]]
        opt_type = "list"
    elif "buttons" in menu_data:
        options = menu_data["buttons"]
        opt_type = "buttons"

    send_whatsapp_message(user_id, text, options, opt_type)
    USER_STATE[user_id]["expecting_reply"] = True

@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
