import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, send_from_directory, jsonify

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import User, Channel, Chat, PeerUser, PeerChannel, PeerChat, UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth

# --- Flask App ---
app = Flask(__name__)
PORT = int(os.environ.get('PORT', 5000))

# --- Credentials ---
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')
SESSION_STRING = os.environ.get('SESSION_STRING')
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# --- Helper functions ---
def calculate_account_age(creation_date):
    today = datetime.now(creation_date.tzinfo)
    delta = relativedelta(today, creation_date)
    parts = []
    if delta.years > 0: parts.append(f"{delta.years} years")
    if delta.months > 0: parts.append(f"{delta.months} months")
    if delta.days > 0: parts.append(f"{delta.days} days")
    return ", ".join(parts) if parts else "Created today"

def estimate_account_creation_date(user_id):
    reference_points = [
        (100000000, datetime(2013, 8, 1)),
        (1273841502, datetime(2020, 8, 13)),
        (1500000000, datetime(2021, 5, 1)),
        (2000000000, datetime(2022, 12, 1)),
    ]
    closest_point = min(reference_points, key=lambda x: abs(x[0] - user_id))
    closest_user_id, closest_date = closest_point
    id_difference = user_id - closest_user_id
    days_difference = id_difference / 20000000
    return closest_date + timedelta(days=days_difference)

def format_status(status):
    if not status: return "Not available"
    if isinstance(status, UserStatusOnline):
        return f"Online (expires at {status.expires.astimezone().strftime('%I:%M %p')})"
    elif isinstance(status, UserStatusOffline):
        return f"Last seen: {status.was_online.astimezone().strftime('%d %b, %Y %I:%M %p')}"
    elif isinstance(status, UserStatusRecently):
        return "Recently online"
    elif isinstance(status, UserStatusLastWeek):
        return "Last seen within a week"
    elif isinstance(status, UserStatusLastMonth):
        return "Last seen within a month"
    return "Unknown"

# --- Telethon async fetch ---
async def get_entity_info_telethon(query):
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    try:
        is_numeric = query.isdigit()
        entity = None

        if is_numeric:
            try: entity = await client.get_entity(PeerUser(int(query)))
            except: entity = None
        else:
            try: entity = await client.get_entity(query.lstrip('@'))
            except: entity = None

        if not entity: return None, "Telethon: Entity not found."

        # Profile photo
        if not os.path.exists('static'): os.makedirs('static')
        photo_path = await client.download_profile_photo(entity, file=f'static/{getattr(entity,"id","unknown")}.jpg')
        photo_url = f'/static/{os.path.basename(photo_path)}' if photo_path else 'N/A'

        if isinstance(entity, User):
            acc_created = estimate_account_creation_date(entity.id)
            data = {
                'type': 'Bot' if entity.bot else 'User',
                'id': entity.id,
                'first_name': entity.first_name,
                'last_name': entity.last_name or '',
                'username': entity.username or 'N/A',
                'is_verified': entity.verified,
                'photo_url': photo_url,
                'account_created': acc_created.strftime("%d %B, %Y"),
                'account_age': calculate_account_age(acc_created)
            }
            if entity.bot:
                data.update({
                    'can_join_groups': not entity.bot_nochats,
                    'can_read_all_group_messages': entity.bot_chat_history,
                    'inline_query_placeholder': entity.bot_inline_placeholder or 'N/A'
                })
            else:
                data.update({
                    'is_premium': getattr(entity, 'premium', False),
                    'status': format_status(entity.status)
                })
            return data, None

        elif isinstance(entity, (Channel, Chat)):
            try:
                if isinstance(entity, Channel):
                    full = await client(GetFullChannelRequest(channel=entity))
                    count = full.full_chat.participants_count
                    type_name = 'Group' if entity.megagroup else 'Channel'
                    type_detail = 'Supergroup' if entity.megagroup else 'Channel'
                else:
                    full = await client(GetFullChatRequest(chat_id=entity.id))
                    count = len(full.users)
                    type_name, type_detail = 'Group', 'Normal Group'
                full_id = int(f"-100{entity.id}") if isinstance(entity, Channel) and not str(entity.id).startswith('-100') else -entity.id
                data = {
                    'type': type_name,
                    'id': full_id,
                    'title': getattr(entity,'title','N/A'),
                    'username': getattr(entity,'username','N/A'),
                    'type_detail': type_detail,
                    'status': 'Public' if getattr(entity,'username',None) else 'Private',
                    'participants_count': count,
                    'photo_url': photo_url
                }
                return data, None
            except Exception as e:
                return None, f"Telethon: {str(e)}"

        return None, "Telethon: Unknown entity type."
    finally:
        if client.is_connected():
            await client.disconnect()

# --- Async Bot API fetch ---
async def get_entity_info_bot_api(user_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat?chat_id={user_id}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get('result', {}), None
                return None, f"Bot API: Status {resp.status}"
        except Exception as e:
            return None, f"Bot API: {str(e)}"

# --- Hybrid fetch logic ---
async def get_entity_hybrid(query):
    if query.isdigit():  # ID
        bot_data, bot_err = await get_entity_info_bot_api(int(query))
        telethon_data, tele_err = await get_entity_info_telethon(query)
        data = telethon_data or {}
        if bot_data: data['bot_api'] = bot_data
        if tele_err and not data: return {'status':'error','message':tele_err or bot_err}
        return {'status':'success','data':data}
    else:  # Username
        telethon_data, tele_err = await get_entity_info_telethon(query)
        if tele_err: return {'status':'error','message':tele_err}
        bot_data, _ = await get_entity_info_bot_api(telethon_data.get('id')) if telethon_data else (None,None)
        if bot_data: telethon_data['bot_api'] = bot_data
        return {'status':'success','data':telethon_data}

# --- Flask routes ---
@app.route('/')
def index(): 
    # Just serve the HTML; JS handles fetch
    from flask import render_template
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search_web():
    # JS handles API fetch, so this can just redirect or ignore
    from flask import redirect
    return redirect('/')

@app.route('/api/info')
def api_info():
    query = request.args.get('query')
    if not query: return jsonify({'status':'error','message':'Query parameter required'}), 400
    data = asyncio.run(get_entity_hybrid(query))
    return jsonify(data)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# --- Run Flask ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
