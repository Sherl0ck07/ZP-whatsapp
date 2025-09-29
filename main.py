from flask import Flask, request, jsonify
import requests
import os
import json
from datetime import datetime, timedelta

# === Load Credentials ===
with open("credentials.json") as f:
    creds = json.load(f)

ACCESS_TOKEN = creds["ACCESS_TOKEN"]
VERIFY_TOKEN = creds["VERIFY_TOKEN"]
PHONE_NUMBER_ID = creds["PHONE_NUMBER_ID"]

# === Load Bot Flow JSON ===
with open("zp_buldhana_flow.json") as f:
    BOT_CONFIG = json.load(f)

# In-memory user state storage
USER_SESSIONS = {}

app = Flask(__name__)


# === Session Management ===
def get_user_session(user_id):
    """Get or create user session"""
    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {
            "current_state": "INITIAL",
            "language": BOT_CONFIG["bot_metadata"]["default_language"],
            "history": [],
            "last_activity": datetime.now()
        }
    else:
        USER_SESSIONS[user_id]["last_activity"] = datetime.now()
    return USER_SESSIONS[user_id]


def check_session_timeout(user_id):
    """Check if session has timed out"""
    if user_id in USER_SESSIONS:
        session = USER_SESSIONS[user_id]
        timeout_minutes = BOT_CONFIG["bot_metadata"]["session_config"]["timeout_minutes"]
        time_diff = datetime.now() - session["last_activity"]
        
        if time_diff > timedelta(minutes=timeout_minutes):
            # Send idle followup if enabled
            if BOT_CONFIG["bot_metadata"]["session_config"]["idle_followup_enabled"]:
                return True
    return False


def update_session_state(user_id, new_state, data=None):
    """Update user session state"""
    session = USER_SESSIONS[user_id]
    session["history"].append(session["current_state"])
    session["current_state"] = new_state
    session["last_activity"] = datetime.now()
    
    if data:
        session.update(data)


def check_global_triggers(msg_text):
    """Check if message matches any global triggers"""
    triggers = BOT_CONFIG["global_triggers"]
    msg_lower = msg_text.lower().strip()
    
    for trigger_name, trigger_config in triggers.items():
        if msg_lower in [k.lower() for k in trigger_config["keywords"]]:
            return trigger_name, trigger_config
    return None, None


# === Verify Webhook ===
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verified")
        return challenge, 200
    return "❌ Verification failed", 403


# === Handle Incoming Messages ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Received webhook:", json.dumps(data, indent=2, ensure_ascii=False))

    if data and "entry" in data:
        for entry in data["entry"]:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    from_number = msg.get("from")
                    msg_body = None

                    # Handle different message types
                    if "text" in msg:
                        msg_body = msg["text"].get("body", "").strip()
                    elif "interactive" in msg:
                        interactive = msg["interactive"]
                        if interactive["type"] == "button_reply":
                            msg_body = interactive["button_reply"]["id"]
                        elif interactive["type"] == "list_reply":
                            msg_body = interactive["list_reply"]["id"]

                    if msg_body:
                        handle_user_message(from_number, msg_body)

    return jsonify({"status": "ok"}), 200


# === Handle User Message ===
def handle_user_message(user_id, msg_text):
    """Main message handler"""
    session = get_user_session(user_id)
    
    # Check for global triggers (restart, main menu, help)
    trigger_name, trigger_config = check_global_triggers(msg_text)
    
    if trigger_name == "restart":
        if trigger_config.get("clear_session"):
            USER_SESSIONS[user_id] = {
                "current_state": "INITIAL",
                "language": BOT_CONFIG["bot_metadata"]["default_language"],
                "history": [],
                "last_activity": datetime.now()
            }
        send_state_message(user_id, "INITIAL")
        return
    
    elif trigger_name == "main_menu":
        next_state = resolve_main_menu_state(session["language"])
        send_state_message(user_id, next_state)
        return
    
    elif trigger_name == "help":
        send_help_message(user_id)
        return
    
    # Process based on current state
    current_state = session["current_state"]
    state_config = BOT_CONFIG["conversation_states"].get(current_state)
    
    if not state_config:
        send_error_message(user_id)
        return
    
    # Handle state-specific logic
    handle_state_interaction(user_id, msg_text, state_config)


# === State Interaction Handler ===
def handle_state_interaction(user_id, selection, state_config):
    """Handle user interaction based on current state"""
    session = USER_SESSIONS[user_id]
    state_type = state_config["state_type"]
    
    if state_type == "interactive_button":
        # Find matching button
        for button in state_config.get("buttons", []):
            if button["id"] == selection or button["id"] in selection:
                next_state = button["next_state"]
                
                # Execute actions
                if "action" in button:
                    execute_action(user_id, button["action"])
                
                update_session_state(user_id, next_state)
                send_state_message(user_id, next_state)
                return
    
    elif state_type == "interactive_list":
        # Find matching row across all sections
        for section in state_config.get("sections", []):
            for row in section.get("rows", []):
                if row["id"] == selection or row["id"] in selection:
                    next_state = row["next_state"]
                    update_session_state(user_id, next_state)
                    send_state_message(user_id, next_state)
                    return
    
    elif state_type == "text_with_buttons":
        # Find matching button
        for button in state_config.get("buttons", []):
            if button["id"] == selection or button["id"] in selection:
                next_state = button["next_state"]
                update_session_state(user_id, next_state)
                send_state_message(user_id, next_state)
                return
    
    # If no match found, send fallback
    send_fallback_message(user_id, state_config)


# === Send State Message ===
def send_state_message(user_id, state_name):
    """Send message for a given state"""
    session = USER_SESSIONS[user_id]
    lang = session["language"]
    
    # Handle redirect states
    if state_name == "MAIN_MENU":
        state_name = resolve_main_menu_state(lang)
    
    state_config = BOT_CONFIG["conversation_states"].get(state_name)
    
    if not state_config:
        send_error_message(user_id)
        return
    
    # Execute entry actions
    for action in state_config.get("entry_actions", []):
        execute_action(user_id, action)
    
    # Get message text
    message_key = state_config["message_config"]["message_key"]
    message_text = get_message_text(message_key, lang)
    
    state_type = state_config["state_type"]
    
    if state_type == "interactive_button":
        buttons = []
        for btn in state_config.get("buttons", []):
            label = get_message_text(btn["label_key"], lang)
            buttons.append({
                "id": btn["id"],
                "title": sanitize_title(label)
            })
        send_whatsapp_button_message(user_id, message_text, buttons)
    
    elif state_type == "interactive_list":
        list_config = state_config["interaction_config"]
        list_title = get_message_text(list_config["list_title_key"], lang)
        button_text = get_message_text(list_config["button_text_key"], lang)
        
        sections = []
        for section in state_config.get("sections", []):
            section_title = get_message_text(section["section_title_key"], lang)
            rows = []
            
            for row in section.get("rows", []):
                row_title = get_message_text(row["title_key"], lang)
                row_desc = get_message_text(row.get("description_key", ""), lang) if "description_key" in row else ""
                rows.append({
                    "id": row["id"],
                    "title": sanitize_title(row_title),
                    "description": row_desc[:72] if row_desc else ""
                })
            
            sections.append({
                "title": section_title[:24],
                "rows": rows
            })
        
        send_whatsapp_list_message(user_id, message_text, button_text, sections)
    
    elif state_type == "text_with_buttons":
        buttons = []
        for btn in state_config.get("buttons", []):
            label = get_message_text(btn["label_key"], lang)
            buttons.append({
                "id": btn["id"],
                "title": sanitize_title(label)
            })
        
        if buttons:
            send_whatsapp_button_message(user_id, message_text, buttons)
        else:
            send_whatsapp_text_message(user_id, message_text)
    
    elif state_type == "redirect":
        redirect_logic = state_config.get("redirect_logic", {})
        if redirect_logic.get("check_language"):
            if lang == "mr":
                next_state = redirect_logic["if_marathi"]
            else:
                next_state = redirect_logic["if_english"]
        else:
            next_state = redirect_logic.get("default", "INITIAL")
        
        update_session_state(user_id, next_state)
        send_state_message(user_id, next_state)
    
    else:
        send_whatsapp_text_message(user_id, message_text)


# === Helper Functions ===
def get_message_text(message_key, lang):
    """Get message text from templates"""
    templates = BOT_CONFIG["message_templates"]
    
    if message_key in templates:
        template = templates[message_key]
        if isinstance(template, dict):
            return template.get(lang, template.get("en", "Message not found"))
        return template
    
    return message_key  # Return key if not found


def sanitize_title(title):
    """Sanitize title for WhatsApp (max 20 chars for buttons, 24 for list titles)"""
    if not title or str(title).strip() == "":
        return "Option"
    t = str(title).strip()
    return t[:20] if len(t) > 20 else t


def execute_action(user_id, action):
    """Execute state actions"""
    session = USER_SESSIONS[user_id]
    
    if action == "set_language_marathi" or action == "set_language:mr":
        session["language"] = "mr"
    elif action == "set_language_english" or action == "set_language:en":
        session["language"] = "en"
    elif action == "clear_session":
        session["history"] = []
    elif action == "log_session_start":
        print(f"📝 Session started for {user_id}")
    elif action == "log_navigation":
        print(f"📍 Navigation: {user_id} -> {session['current_state']}")


def resolve_main_menu_state(lang):
    """Resolve which main menu state to use based on language"""
    return "LANGUAGE_SELECTED_MR" if lang == "mr" else "LANGUAGE_SELECTED_EN"


def send_help_message(user_id):
    """Send help message"""
    session = USER_SESSIONS[user_id]
    lang = session["language"]
    help_text = get_message_text("help_message", lang)
    send_whatsapp_text_message(user_id, help_text)


def send_error_message(user_id):
    """Send error message"""
    session = USER_SESSIONS[user_id]
    lang = session["language"]
    error_text = "An error occurred. Please type 'restart' to begin again." if lang == "en" else "त्रुटी आली. कृपया 'restart' टाइप करा."
    send_whatsapp_text_message(user_id, error_text)


def send_fallback_message(user_id, state_config):
    """Send fallback message for invalid input"""
    session = USER_SESSIONS[user_id]
    lang = session["language"]
    
    fallback = state_config.get("fallback", {})
    msg_key = fallback.get("invalid_response_message_key", "invalid_menu_selection_en")
    message = get_message_text(msg_key, lang)
    
    send_whatsapp_text_message(user_id, message)


# === WhatsApp API Functions ===
def send_whatsapp_text_message(to, text):
    """Send simple text message"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    print(f"📤 Text message sent: {resp.status_code}")
    return resp.json()


def send_whatsapp_button_message(to, text, buttons):
    """Send interactive button message"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    button_list = [
        {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}}
        for btn in buttons[:3]  # Max 3 buttons
    ]
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {"buttons": button_list}
        }
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    print(f"📤 Button message sent: {resp.status_code}")
    return resp.json()


def send_whatsapp_list_message(to, text, button_text, sections):
    """Send interactive list message"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": button_text[:20],
                "sections": sections
            }
        }
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    print(f"📤 List message sent: {resp.status_code}")
    return resp.json()


# === Root Endpoint ===
@app.route("/")
def home():
    return "🚀 ZP Buldhana WhatsApp Bot is running!", 200


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "active_sessions": len(USER_SESSIONS),
        "bot_version": BOT_CONFIG["bot_metadata"]["version"]
    }), 200


# === Run App ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Starting ZP Buldhana Bot on port {port}")
    print(f"📋 Loaded bot config: {BOT_CONFIG['bot_metadata']['bot_name']}")
    app.run(host="0.0.0.0", port=port, debug=True)