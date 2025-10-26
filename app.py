import os
import asyncio
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, request, jsonify, send_from_directory
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import UsernameNotOccupiedError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import User, Channel, Chat, UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth
import requests

# --- Flask App setup ---
app = Flask(__name__)

# --- Environment Variables ---
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')
SESSION_STRING = os.environ.get('SESSION_STRING')
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# --- Telethon Client ---
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# --- Official Bot API Class ---
class OfficialBotAPI:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def get_chat_info(self, chat_id):
        try:
            clean_chat_id = str(chat_id).strip()
            if not clean_chat_id.startswith('@') and not clean_chat_id.lstrip('-').isdigit():
                clean_chat_id = '@' + clean_chat_id
            if clean_chat_id.lstrip('-').isdigit():
                clean_chat_id = int(clean_chat_id)

            # Get Chat Info
            resp = requests.post(f"{self.base_url}/getChat", json={"chat_id": clean_chat_id}, timeout=10)
            result = resp.json()
            if not result.get('ok'):
                return {'status':'error','message':result.get('description','Unknown error')}
            data = result['result']

            # Member count
            if data.get('type') in ['group','supergroup','channel']:
                try:
                    count_resp = requests.post(f"{self.base_url}/getChatMemberCount", json={"chat_id": clean_chat_id}, timeout=10)
                    data['members_count'] = count_resp.json().get('result')
                except: data['members_count'] = None

                # Invite link
                try:
                    link_resp = requests.post(f"{self.base_url}/exportChatInviteLink", json={"chat_id": clean_chat_id}, timeout=10)
                    if link_resp.json().get('ok'):
                        data['invite_link'] = link_resp.json()['result']
                except: data['invite_link'] = None

            return {'status':'success','data':data}
        except Exception as e:
            return {'status':'error','message':str(e)}

    def get_user_profile_photos(self, user_id, limit=1):
        resp = requests.post(f"{self.base_url}/getUserProfilePhotos", json={"user_id": user_id, "limit": limit})
        return resp.json()

    def estimate_account_creation_from_id(self, user_id):
        reference_points = [
            (100000000, datetime(2013,8,1)),
            (500000000, datetime(2016,5,1)),
            (1000000000, datetime(2018,12,1)),
            (1500000000, datetime(2020,8,1)),
            (2000000000, datetime(2021,12,1)),
            (2500000000, datetime(2023,3,1)),
            (3000000000, datetime(2024,6,1)),
            (3500000000, datetime(2025,9,1)),
        ]
        closest_point = min(reference_points, key=lambda x: abs(x[0]-user_id))
        closest_user_id, closest_date = closest_point
        est_days = (user_id - closest_user_id)/6000000
        est_date = closest_date + timedelta(days=est_days)
        if est_date > datetime.now():
            est_date = datetime.now() - timedelta(days=30)
        return est_date

bot_api = OfficialBotAPI(BOT_TOKEN)

# --- Helper Functions ---
def calculate_account_age(creation_date):
    delta = relativedelta(datetime.now(), creation_date)
    parts=[]
    if delta.years>0: parts.append(f"{delta.years} years")
    if delta.months>0: parts.append(f"{delta.months} months")
    if delta.days>0: parts.append(f"{delta.days} days")
    return ", ".join(parts) if parts else "Created today"

def format_status(status):
    if not status: return "Not available"
    if isinstance(status, UserStatusOnline): return "Online"
    if isinstance(status, UserStatusOffline): return f"Last seen: {status.was_online.strftime('%d %b, %Y %I:%M %p')}"
    if isinstance(status, UserStatusRecently): return "Recently online"
    if isinstance(status, UserStatusLastWeek): return "Last seen within a week"
    if isinstance(status, UserStatusLastMonth): return "Last seen within a month"
    return "Unknown"

async def get_entity_info_data(query):
    await client.connect()
    try:
        # Numeric ID → Bot API
        try:
            int(query)
            is_numeric = True
        except: is_numeric=False

        if is_numeric:
            result = bot_api.get_chat_info(query)
            if result['status']=='error': return {'status':'error','message':result['message']}
            data = result['data']
            if data.get('type') in ['private'] or data.get('is_bot',False):
                photos = bot_api.get_user_profile_photos(data['id'])
                if photos.get('ok') and photos['result']['total_count']>0:
                    data['photo_url'] = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{photos['result']['photos'][0][-1]['file_id']}"
            return {'status':'success','data':data}

        # Username → Telethon
        try:
            entity = await client.get_entity(query)
        except UsernameNotOccupiedError:
            return {'status':'error','message':f"No user found with username '{query}'."}

        # Profile photo
        if not os.path.exists('static'): os.makedirs('static')
        photo_path = await client.download_profile_photo(entity, file=f'static/{entity.id}.jpg')
        photo_url = f'/static/{entity.id}.jpg' if photo_path else None

        # User
        if isinstance(entity, User):
            acc_created = bot_api.estimate_account_creation_from_id(entity.id)
            data = {
                'type':'Bot' if entity.bot else 'User',
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
                data.update({'is_premium': entity.premium, 'status': format_status(entity.status)})
            return {'status':'success','data':data}

        # Group/Channel
        elif isinstance(entity,(Channel,Chat)):
            try:
                if isinstance(entity, Channel):
                    full = await client(GetFullChannelRequest(channel=entity))
                    count = full.full_chat.participants_count
                    type_name = 'Supergroup' if entity.megagroup else 'Channel'
                else:
                    full = await client(GetFullChatRequest(chat_id=entity.id))
                    count = len(full.users)
                    type_name = 'Group'

                full_id = int(f"-100{entity.id}") if isinstance(entity, Channel) and not str(entity.id).startswith('-100') else -entity.id

                # Invite link from Bot API
                invite_link = None
                try:
                    bot_result = bot_api.get_chat_info(full_id)
                    invite_link = bot_result['data'].get('invite_link')
                except: pass

                data = {
                    'type': type_name,
                    'id': full_id,
                    'title': entity.title,
                    'username': entity.username or 'N/A',
                    'status': 'Public' if entity.username else 'Private',
                    'is_verified': getattr(entity,'verified',False),
                    'participants_count': count,
                    'invite_link': invite_link,
                    'photo_url': photo_url
                }
                return {'status':'success','data':data}
            except: return {'status':'error','message':'Failed to retrieve group/channel data'}
    finally:
        if client.is_connected(): await client.disconnect()

# --- Flask routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info')
def api_info():
    query = request.args.get('query')
    if not query: return jsonify({'status':'error','message':'Query parameter is required'}),400
    data = asyncio.run(get_entity_info_data(query))
    return jsonify(data)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
