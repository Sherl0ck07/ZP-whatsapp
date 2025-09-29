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

USER_STATE = {}
LAST_ACTIVE = {}

def sanitize_title(title):
    return str(title).strip()[:20] if title else "Option"

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
                    {"type": "reply", "reply": {"id": b, "title": sanitize_title(b)}}
                    for b in options
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
                    "rows": [{"id": b, "title": sanitize_title(b)} for b in options]
                }]
            }
        }
    else:
        payload["type"] = "text"
        payload["text"] = {"body": message_text}

    resp = requests.post(url, headers=headers, json=payload)
    print(f"📤 Send message response: {resp.status_code} {resp.text}")
    return resp.json()

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

def clean_msg(text):
    if not text:
        return ""
    return text.replace("\n", " ").replace("\r", " ").strip()

def handle_restart(user_id, user_text):
    if user_text.strip().lower() in ["restart", "पुन्हा सुरू करा"]:
        USER_STATE[user_id] = {
            "stage": "INIT",
            "language": None,
            "current_menu": "opening",
            "expecting_reply": True
        }
        send_opening_menu(user_id)
        return True
    return False

def send_opening_menu(user_id):
    opening = MENU["opening"]
    lang = "en"
    buttons = []
    # Buttons array in opening uses 'id' and 'en'/'mr'
    for b in opening["buttons"]:
        buttons.append(b["id"])
    send_whatsapp_message(user_id, opening["msg"][lang], buttons, "buttons")

def find_menu_item_by_id(menu_id):
    # For opening node, handle specially
    if menu_id == "opening":
        return MENU.get("opening")
    # Look inside menus dict
    return MENU.get("menus", {}).get(menu_id)

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

                    # Handle restart
                    if user_text and handle_restart(from_number, user_text):
                        continue

                    # Handle interactive reply by ID
                    if msg_body:
                        handle_user_input(from_number, msg_body)
                        continue

                    # Handle free text (language input only expected at INIT)
                    if user_text:
                        handle_free_text(from_number, user_text)
                        continue

    return jsonify({"status": "ok"}), 200

def handle_free_text(user_id, user_text):
    state = USER_STATE.get(user_id, {
        "stage": "INIT",
        "language": None,
        "current_menu": "opening",
        "expecting_reply": False
    })
    if state["stage"] == "INIT":
        lang_text = user_text.lower()
        if lang_text in ["english", "english"]:
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": "en",
                "current_menu": "main_menu",
                "expecting_reply": True
            }
            send_menu_by_id(user_id, "main_menu", "en")
            return
        elif lang_text in ["marathi", "मराठी"]:
            USER_STATE[user_id] = {
                "stage": "LANG_SELECTED",
                "language": "mr",
                "current_menu": "main_menu",
                "expecting_reply": True
            }
            send_menu_by_id(user_id, "main_menu", "mr")
            return
    # fallback
    send_opening_menu(user_id)

def handle_user_input(user_id, selected_id):
    state = USER_STATE.get(user_id, {
        "stage": "INIT",
        "language": None,
        "current_menu": "opening",
        "expecting_reply": False
    })
    lang = state.get("language") or "en"
    # Find this selected_id menu node
    item = find_menu_item_by_id(selected_id)
    if not item:
        # Ignore invalid inputs - fallback to current menu
        send_menu_by_id(user_id, state.get("current_menu", "main_menu"), lang)
        return
    # Update user state to this menu
    USER_STATE[user_id]["current_menu"] = selected_id
    USER_STATE[user_id]["expecting_reply"] = True

    send_menu_item(user_id, item, lang)

def send_menu_by_id(user_id, menu_id, lang):
    item = find_menu_item_by_id(menu_id)
    if item:
        send_menu_item(user_id, item, lang)
    else:
        # fallback main menu
        main_menu = find_menu_item_by_id("main_menu")
        send_menu_item(user_id, main_menu, lang)

def send_menu_item(user_id, item, lang):
    # Prepare message text
    msg_text = ""
    if "msg" in item:
        if isinstance(item["msg"], dict):
            msg_text = item["msg"].get(lang, item["msg"].get("en", ""))
        else:
            msg_text = item["msg"]
    else:
        msg_text = "Welcome!"

    # Prepare buttons/options for response
    options = []
    opt_type = "text"

    # Always include navigation buttons except on main menu or opening
    navigation_ids = []
    parent_id = item.get("parent_id")
    if parent_id and parent_id != "opening":
        navigation_ids.append(parent_id)  # Back
    if item.get("id") != "main_menu":
        navigation_ids.append("main_menu")  # Main Menu

    # Compose options from item options or buttons
    if "options" in item:
        options = [opt["id"] for opt in item["options"]]
        # Append navigation buttons
        options.extend(navigation_ids)
        opt_type = "list"
    elif "buttons" in item:
        options = [btn["id"] for btn in item["buttons"]]
        options.extend(navigation_ids)
        opt_type = "buttons" if len(options) <= 3 else "list"
    else:
        # No explicit options/buttons - show navigation only
        if navigation_ids:
            options = navigation_ids
            opt_type = "buttons" if len(options) <= 3 else "list"

    # Map option IDs to display titles based on language for sending
    display_options = []
    for opt_id in options:
        opt_item = None
        # find option in options/buttons by id or menu id itself
        if "options" in item:
            opt_item = next((o for o in item["options"] if o["id"] == opt_id), None)
        elif "buttons" in item:
            opt_item = next((b for b in item["buttons"] if b["id"] == opt_id), None)
        else:
            opt_item = find_menu_item_by_id(opt_id)
        if not opt_item:
            # fallback label for navigation buttons by id
            if opt_id == "main_menu":
                display_options.append("Main Menu" if lang == "en" else "मुख्य मेनू")
            elif opt_id == item.get("parent_id"):
                # Back label from parent menu
                parent_menu = find_menu_item_by_id(item.get("parent_id"))
                if parent_menu:
                    display_options.append(parent_menu["msg"].get(lang, "Back") if isinstance(parent_menu.get("msg"), dict) else "Back")
                else:
                    display_options.append("Back" if lang == "en" else "मागे")
            else:
                display_options.append(opt_id)
        else:
            # Use en/mr label from option or buttons object
            if "en" in opt_item and "mr" in opt_item:
                display_options.append(opt_item[lang])
            elif "msg" in opt_item:
                if isinstance(opt_item["msg"], dict):
                    display_options.append(opt_item["msg"].get(lang, opt_item["msg"].get("en", opt_id)))
                else:
                    display_options.append(opt_item["msg"])
            else:
                display_options.append(opt_id)

    send_whatsapp_message(user_id, msg_text, display_options, opt_type)

@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
