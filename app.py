import os
import asyncio
import requests
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, request, jsonify, send_from_directory
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import UsernameNotOccupiedError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import User, Channel, Chat, UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth

# --- Flask App setup ---
app = Flask(__name__)

# --- Environment Variables ---
API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
SESSION_STRING = os.environ.get('SESSION_STRING')
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# --- Telethon Client ---
client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)

# --- Official Bot API Class ---
class OfficialBotAPI:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def get_chat_info(self, chat_id):
        url = f"{self.base_url}/getChat"
        try:
            clean_chat_id = str(chat_id).strip()
            if isinstance(clean_chat_id, str):
                if not clean_chat_id.startswith('@') and not clean_chat_id.lstrip('-').isdigit():
                    clean_chat_id = '@' + clean_chat_id
            if isinstance(clean_chat_id, str) and clean_chat_id.lstrip('-').isdigit():
                clean_chat_id = int(clean_chat_id)
            response = requests.post(url, json={"chat_id": clean_chat_id}, timeout=10)
            result = response.json()
            if not result.get('ok'):
                return {'status': 'error', 'message': result.get('description', 'Unknown error')}
            data = result['result']
            
            # Member count & Invite link (Bot API)
            if data.get('type') in ['group', 'supergroup', 'channel']:
                try:
                    count_url = f"{self.base_url}/getChatMemberCount"
                    count_resp = requests.post(count_url, json={"chat_id": clean_chat_id}, timeout=10)
                    count_data = count_resp.json()
                    data['members_count'] = count_data['result'] if count_data.get('ok') else None
                except:
                    data['members_count'] = None
                try:
                    link_url = f"{self.base_url}/exportChatInviteLink"
                    link_resp = requests.post(link_url, json={"chat_id": clean_chat_id}, timeout=10)
                    link_data = link_resp.json()
                    data['invite_link'] = link_data['result'] if link_data.get('ok') else None
                except:
                    data['invite_link'] = None
            return {'status': 'success', 'data': data}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def get_user_profile_photos(self, user_id, limit=1):
        url = f"{self.base_url}/getUserProfilePhotos"
        response = requests.post(url, json={"user_id": user_id, "limit": limit})
        return response.json()

    # এই ফাংশনটি (estimate_account_creation_from_id) কোডের জটিলতা কমাতে অপরিবর্তিত রাখা হলো
    def estimate_account_creation_from_id(self, user_id):
        reference_points = [
            (100000000, datetime(2013, 8, 1)), (500000000, datetime(2016, 5, 1)),
            (1000000000, datetime(2018, 12, 1)), (1500000000, datetime(2020, 8, 1)),
            (2000000000, datetime(2021, 12, 1)), (2500000000, datetime(2023, 3, 1)),
            (3000000000, datetime(2024, 6, 1)), (3500000000, datetime(2025, 9, 1)),
        ]
        closest_point = min(reference_points, key=lambda x: abs(x[0]-user_id))
        closest_user_id, closest_date = closest_point
        days_diff = (user_id - closest_user_id)/6000000
        est_date = closest_date + timedelta(days=days_diff)
        if est_date > datetime.now(): est_date = datetime.now() - timedelta(days=30)
        return est_date

bot_api = OfficialBotAPI(BOT_TOKEN)

# --- Helper Functions ---
def calculate_account_age(creation_date):
    delta = relativedelta(datetime.now(), creation_date)
    parts = []
    if delta.years>0: parts.append(f"{delta.years} years")
    if delta.months>0: parts.append(f"{delta.months} months")
    if delta.days>0: parts.append(f"{delta.days} days")
    return ", ".join(parts) if parts else "Created today"

def format_status(status):
    if not status: return "Not available"
    if isinstance(status, UserStatusOnline): return "Online"
    elif isinstance(status, UserStatusOffline): return f"Last seen: {status.was_online.strftime('%d %b, %Y %I:%M %p')}"
    elif isinstance(status, UserStatusRecently): return "Recently online"
    elif isinstance(status, UserStatusLastWeek): return "Last seen within a week"
    elif isinstance(status, UserStatusLastMonth): return "Last seen within a month"
    return "Unknown"

# --- Telethon সংযোগ লজিক (প্রথমবার অ্যাপ চলার সময় রান হবে) ---
@app.before_first_request
async def connect_telethon():
    """Application startup-এ Telethon client-কে একবারই সংযুক্ত করে।"""
    try:
        if not client.is_connected():
            await client.start()
            print("✅ Telethon Client Connected Successfully.")
    except Exception as e:
        # এটি Render এ ত্রুটি কমাতে সাহায্য করবে
        print(f"❌ Failed to connect Telethon Client on startup: {e}")

# --- কোর ফাংশন (Async) ---
async def get_entity_info_data(query):
    # ক্লায়েন্ট কানেকশন বারবার কল করা হচ্ছে না
    if not client.is_connected():
        return {'status':'error','message':'Telethon client is not connected. Check environment variables.'}
        
    try:
        is_numeric = query.lstrip('-').isdigit()

        # Numeric ID → Bot API
        if is_numeric:
            result = bot_api.get_chat_info(query)
            if result['status']=='error': return {'status':'error','message':result['message']}
            data = result['data']
            
            # Profile photo URL
            if data.get('type') in ['private'] or data.get('is_bot',False):
                photos_result = bot_api.get_user_profile_photos(data['id'])
                if photos_result.get('ok') and photos_result['result']['total_count']>0:
                    file_id = photos_result['result']['photos'][0][-1]['file_id']
                    data['photo_url'] = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_id}"
            
            return {'status':'success','data':data}

        # Username → Telethon
        else:
            try:
                entity = await client.get_entity(query)
            except UsernameNotOccupiedError:
                return {'status':'error','message':f"No entity found with username/query '{query}'."}
            except Exception as e:
                return {'status':'error','message':f"Telethon error while getting entity: {e}"}

            # Profile photo ডাউনলোড ও URL তৈরি
            photo_path = await client.download_profile_photo(entity, file=f'static/{entity.id}.jpg')
            photo_url = f'/static/{entity.id}.jpg' if photo_path else 'N/A'

            if isinstance(entity, User):
                acc_created = bot_api.estimate_account_creation_from_id(entity.id)
                data = {
                    'type':'Bot' if entity.bot else 'User',
                    'id':entity.id,
                    'first_name':entity.first_name,
                    'last_name':entity.last_name or '',
                    'username':entity.username or 'N/A',
                    'is_verified':entity.verified,
                    'photo_url':photo_url,
                    'account_created':acc_created.strftime("%d %B, %Y"),
                    'account_age': calculate_account_age(acc_created),
                    'is_premium':entity.premium,
                    'status':format_status(entity.status)
                }
                if entity.bot: 
                    data.update({'can_join_groups': not entity.bot_nochats})
                return {'status':'success','data':data}

            elif isinstance(entity, (Channel, Chat)):
                try:
                    if isinstance(entity, Channel):
                        full = await client(GetFullChannelRequest(channel=entity))
                        count = full.full_chat.participants_count
                        type_name = 'Group' if entity.megagroup else 'Channel'
                        full_id = int(f"-100{entity.id}")
                    else: # Chat (Normal Group)
                        full = await client(GetFullChatRequest(chat_id=entity.id))
                        count = len(full.users)
                        type_name = 'Group'
                        full_id = -entity.id
                    
                    # Invite link (Bot API fallback)
                    bot_result = bot_api.get_chat_info(full_id)
                    invite_link = bot_result['data'].get('invite_link') if bot_result['status'] == 'success' else None

                    data = {
                        'type': type_name,
                        'id':full_id,
                        'title':entity.title,
                        'username':entity.username or 'N/A',
                        'status':'Public' if entity.username else 'Private',
                        'is_verified':getattr(entity,'verified',False),
                        'participants_count':count,
                        'invite_link':invite_link,
                        'photo_url':photo_url
                    }
                    return {'status':'success','data':data}
                except Exception as e:
                    return {'status':'error','message':f'Failed to retrieve group/channel data (Telethon): {e}'}
            
            return {'status':'error','message':'Unknown entity type.'}

    except Exception as main_e:
        return {'status':'error','message':f'An unexpected error occurred: {main_e}'}

# --- Flask routes (Fixed Async Route) ---

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/info')
async def api_info(): # <--- FIX: রুটটিকে async করা হয়েছে
    query = request.args.get('query')
    if not query:
        return jsonify({'status':'error','message':'Query parameter is required'}),400
        
    # FIX: asyncio.run() এর পরিবর্তে সরাসরি await ব্যবহার
    data = await get_entity_info_data(query) 
    
    return jsonify(data)


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


if __name__=='__main__':
    # লোকাল টেস্টিং এর জন্য
    print("⚠️ Local development mode. Ensure you run with an ASGI server for production on Render.")
    
    # লোকালি কানেক্ট করতে একটি লুপের প্রয়োজন হতে পারে, তবে production-এ ASGI সার্ভার এটি হ্যান্ডেল করবে।
    # app.run() স্বয়ংক্রিয়ভাবে app.before_first_request কল করবে।
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
