import os
import asyncio
import requests
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, request, jsonify, send_from_directory
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import (
    User, Channel, Chat,
    UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth
)

# ---------------- Config ----------------
app = Flask(__name__, template_folder='templates')
PORT = int(os.environ.get('PORT', 5000))

API_ID = os.getenv('API_ID')           # required for username (Telethon)
API_HASH = os.getenv('API_HASH')       # required for username (Telethon)
SESSION_STRING = os.getenv('SESSION_STRING', '')  # Telethon session string (optional but recommended)
BOT_TOKEN = os.getenv('BOT_TOKEN', '')            # required for numeric ID lookups

# Validate minimal config (note: username-only searches can work without BOT_TOKEN)
# We'll not crash on start; but api routes will return friendly errors if creds missing.

# ---------------- Helpers ----------------
def estimate_account_creation_date(user_id: int) -> datetime:
    """
    Estimate account creation date from user id (approximation).
    Works without Telethon; used for numeric-id results where Telethon is not called.
    """
    reference_points = [
        (100000000, datetime(2013, 8, 1)),
        (1273841502, datetime(2020, 8, 13)),
        (1500000000, datetime(2021, 5, 1)),
        (2000000000, datetime(2022, 12, 1)),
    ]
    closest_point = min(reference_points, key=lambda x: abs(x[0] - user_id))
    closest_user_id, closest_date = closest_point
    id_difference = user_id - closest_user_id
    days_difference = id_difference / 20000000  # heuristic used earlier
    return closest_date + timedelta(days=days_difference)

def calculate_account_age(creation_date: datetime) -> str:
    today = datetime.now(creation_date.tzinfo)
    delta = relativedelta(today, creation_date)
    parts = []
    if delta.years > 0:
        parts.append(f"{delta.years} years")
    if delta.months > 0:
        parts.append(f"{delta.months} months")
    if delta.days > 0:
        parts.append(f"{delta.days} days")
    return ", ".join(parts) if parts else "Created today"

def format_status(status):
    if not status:
        return "Not available"
    if isinstance(status, UserStatusOnline):
        try:
            return f"Online (expires at {status.expires.astimezone().strftime('%I:%M %p')})"
        except Exception:
            return "Online"
    if isinstance(status, UserStatusOffline):
        try:
            return f"Last seen: {status.was_online.astimezone().strftime('%d %b, %Y %I:%M %p')}"
        except Exception:
            return "Last seen (time not available)"
    if isinstance(status, UserStatusRecently):
        return "Recently online"
    if isinstance(status, UserStatusLastWeek):
        return "Last seen within a week"
    if isinstance(status, UserStatusLastMonth):
        return "Last seen within a month"
    return "Unknown"

# ---------------- Telethon (username-only) ----------------
async def fetch_via_telethon(username: str):
    """
    Only used for username queries (no Telethon calls for numeric ID).
    Returns dict (data) or (None, error_message)
    """
    if not (API_ID and API_HASH):
        return None, "Telethon credentials not set (API_ID/API_HASH)."

    # Build client per-call to avoid background loop issues
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.connect()
    try:
        # accept both '@name' and 'name'
        name = username.lstrip('@').strip()
        try:
            entity = await client.get_entity(name)
        except Exception as e:
            return None, f"Telethon error: {str(e)}"

        # ensure static folder exists
        if not os.path.exists('static'):
            os.makedirs('static')

        photo_url = None
        try:
            photo_path = await client.download_profile_photo(entity, file=f'static/{getattr(entity, "id", "unknown")}.jpg')
            if photo_path:
                photo_url = f"/static/{os.path.basename(photo_path)}"
        except Exception:
            photo_url = None  # ignore photo errors

        if isinstance(entity, User):
            uid = entity.id
            created = estimate_account_creation_date(uid)
            data = {
                "source": "telethon",
                "type": "Bot" if getattr(entity, "bot", False) else "User",
                "id": uid,
                "first_name": getattr(entity, "first_name", "") or "",
                "last_name": getattr(entity, "last_name", "") or "",
                "full_name": " ".join(filter(None, [getattr(entity, "first_name", ""), getattr(entity, "last_name", "")])).strip(),
                "username": getattr(entity, "username", None) or "N/A",
                "is_verified": bool(getattr(entity, "verified", False)),
                "photo": photo_url or "N/A",
                "account_created": created.strftime("%d %B, %Y"),
                "account_age": calculate_account_age(created),
                "is_premium": bool(getattr(entity, "premium", False)),
                "status": format_status(getattr(entity, "status", None))
            }
            # bot-specific fields
            if getattr(entity, "bot", False):
                data.update({
                    "can_join_groups": not getattr(entity, "bot_nochats", False),
                    "can_read_all_group_messages": getattr(entity, "bot_chat_history", False),
                    "inline_query_placeholder": getattr(entity, "bot_inline_placeholder", None) or "N/A"
                })
            return data, None

        elif isinstance(entity, (Channel, Chat)):
            try:
                if isinstance(entity, Channel):
                    full = await client(GetFullChannelRequest(channel=entity))
                    participants = getattr(full.full_chat, "participants_count", None)
                    type_name = "Supergroup" if getattr(entity, "megagroup", False) else "Channel"
                else:
                    full = await client(GetFullChatRequest(chat_id=entity.id))
                    participants = len(getattr(full, "users", []) or [])
                    type_name = "Group"

                uid = -abs(entity.id)  # keep sign for display
                created = estimate_account_creation_date(abs(uid))  # approximate
                data = {
                    "source": "telethon",
                    "type": type_name,
                    "id": uid,
                    "title": getattr(entity, "title", "N/A"),
                    "username": getattr(entity, "username", None) or "N/A",
                    "status": "Public" if getattr(entity, "username", None) else "Private",
                    "is_verified": bool(getattr(entity, "verified", False)),
                    "participants_count": participants,
                    "photo": None
                }
                # download photo if possible
                try:
                    photo_path = await client.download_profile_photo(entity, file=f'static/{abs(entity.id)}.jpg')
                    if photo_path:
                        data["photo"] = f"/static/{os.path.basename(photo_path)}"
                except Exception:
                    pass
                return data, None
            except Exception as e:
                return None, f"Telethon error: {str(e)}"

        else:
            return None, "Telethon: Unknown entity type."
    finally:
        if client.is_connected():
            await client.disconnect()

# ---------------- Bot API (numeric-only) ----------------
def fetch_via_botapi_numeric(query_id: str):
    """
    Only used for numeric IDs (must use bot token). Returns data dict or (None, error_msg).
    Will attempt to return photo URL (direct file URL) if available.
    Also estimates account creation date & age from ID if numeric.
    """
    if not BOT_TOKEN:
        return None, "Bot token not set (BOT_TOKEN)."

    # Accept IDs like 12345 or -1001234567893
    chat_id = query_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat?chat_id={chat_id}"
    try:
        r = requests.get(url, timeout=10)
    except Exception as e:
        return None, f"Bot API network error: {str(e)}"

    try:
        res = r.json()
    except Exception:
        return None, f"Bot API: invalid JSON response (status {r.status_code})"

    if not res.get("ok"):
        # provide the Telegram description if available
        return None, f"Bot API: {res.get('description', f'status {r.status_code}')}"

    chat = res["result"]

    # Build basic data
    data = {
        "source": "botapi",
        "id": chat.get("id"),
        "type": chat.get("type"),
        "title": chat.get("title") or chat.get("first_name") or chat.get("username") or "N/A",
        "username": chat.get("username") or "N/A",
        "is_verified": False,  # not provided by Bot API
        "photo": None,
    }

    # Estimate account created & age if id is integer (use absolute for estimation)
    try:
        uid = int(chat.get("id"))
        created = estimate_account_creation_date(abs(uid))
        data["account_created"] = created.strftime("%d %B, %Y")
        data["account_age"] = calculate_account_age(created)
    except Exception:
        pass

    # If chat.photo present, try to get file path via getFile and form file URL
    photo = chat.get("photo")
    if photo:
        # choose big_file_id if exists (older API), or file_id extraction not always present in getChat
        # We'll attempt using getFile with file_id(s) if present; else try to use file_id from photo object fields
        # Bot API returns photo object with small_file_id/big_file_id in older versions.
        file_id = photo.get("big_file_id") or photo.get("small_file_id")
        if file_id:
            try:
                file_res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}", timeout=10).json()
                if file_res.get("ok"):
                    path = file_res["result"]["file_path"]
                    data["photo"] = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
            except Exception:
                data["photo"] = None

    # Bot-specific fields: for chats the Bot API returns various permissions; include raw "result" as bot_api if helpful
    data["raw"] = chat

    return data, None

# ---------------- Flask Routes ----------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/info')
def api_info():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({"status": "error", "message": "Query parameter required (username or numeric id)."}), 400

    # Decide numeric vs username: numeric if all digits OR starts with -100 and rest digits OR optional leading minus.
    q_sanit = query.replace("+", "").strip()
    is_numeric = False
    if q_sanit.lstrip('-').isdigit():
        is_numeric = True

    if is_numeric:
        # Numeric: use Bot API ONLY (no Telethon)
        data, err = fetch_via_botapi_numeric(q_sanit)
        if data:
            return jsonify({"status": "success", "data": data})
        else:
            return jsonify({"status": "error", "message": err or "Bot API error"}), 400
    else:
        # Username: use Telethon ONLY
        try:
            telethon_result = asyncio.run(fetch_via_telethon(query))
            data, err = telethon_result if isinstance(telethon_result, tuple) else (telethon_result, None)
        except Exception as e:
            return jsonify({"status": "error", "message": f"Telethon runtime error: {str(e)}"}), 500

        if data:
            return jsonify({"status": "success", "data": data})
        else:
            return jsonify({"status": "error", "message": err or "Telethon error"}), 400

# ---------------- Run ----------------
if __name__ == '__main__':
    # ensure static directory exists
    if not os.path.exists('static'):
        os.makedirs('static')
    app.run(host='0.0.0.0', port=PORT, debug=False)
