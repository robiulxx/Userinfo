# app.py

import os
import requests
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template_string, request, Markup

# ===================================================================
# 📦 আপনার মূল লজিক (OfficialBotAPI ক্লাস, Formatting Functions, ইত্যাদি)
# ===================================================================

BOT_TOKEN = os.environ.get('BOT_TOKEN')

class OfficialBotAPI:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def get_chat_info(self, chat_id):
        """Official Bot API দিয়ে User/Group/Bot/Channel information নেয় - FIXED"""
        if not self.bot_token:
            return {'status': 'error', 'message': "BOT_TOKEN Environment Variable is not set."}
        
        url = f"{self.base_url}/getChat"

        try:
            clean_chat_id = str(chat_id).strip()

            if isinstance(clean_chat_id, str):
                if not clean_chat_id.startswith('@') and not clean_chat_id.lstrip('-').isdigit():
                    clean_chat_id = '@' + clean_chat_id
                elif clean_chat_id.startswith('@') and clean_chat_id.count('@') > 1:
                    clean_chat_id = '@' + clean_chat_id.split('@')[-1]

            if isinstance(clean_chat_id, str) and clean_chat_id.lstrip('-').isdigit():
                clean_chat_id = int(clean_chat_id)

            response = requests.post(url, json={"chat_id": clean_chat_id}, timeout=10)
            result = response.json()

            if not result.get('ok'):
                error_msg = result.get('description', 'Unknown error')
                return {'status': 'error', 'message': error_msg}

            data = result['result']

            if data.get('username') and data['username'].lower().endswith('bot'):
                data['is_bot'] = True

            if data.get('type') == 'private' or data.get('is_bot'):
                user_id = data.get('id')
                if user_id and user_id > 0:
                    estimated_created = self.estimate_account_creation_from_id(user_id)
                    data['estimated_created'] = estimated_created.strftime("%d %B, %Y")
                    data['estimated_age'] = self.calculate_age_from_estimation(estimated_created)
                    data['estimated_status'] = self.estimate_smart_status(
                        user_id,
                        data.get('username'),
                        data.get('is_premium', False),
                        data.get('is_bot', False)
                    )

            if data.get('type') in ['group', 'supergroup', 'channel']:
                try:
                    count_url = f"{self.base_url}/getChatMemberCount"
                    count_resp = requests.post(count_url, json={"chat_id": clean_chat_id}, timeout=10)
                    count_data = count_resp.json()
                    if count_data.get('ok'):
                        data['members_count'] = count_data['result']
                except Exception:
                    data['members_count'] = None

                try:
                    link_url = f"{self.base_url}/exportChatInviteLink"
                    link_resp = requests.post(link_url, json={"chat_id": clean_chat_id}, timeout=10)
                    link_data = link_resp.json()
                    if link_data.get('ok'):
                        data['invite_link'] = link_data['result']
                except Exception:
                    pass

            return {'status': 'success', 'data': data}

        except Exception as e:
            return {'status': 'error', 'message': f"API Error: {str(e)}"}
    
    def get_user_profile_photos(self, user_id, limit=1):
        url = f"{self.base_url}/getUserProfilePhotos"
        response = requests.post(url, json={"user_id": user_id, "limit": limit})
        return response.json()
    
    def estimate_account_creation_from_id(self, user_id):
        reference_points = [
            (100000000, datetime(2013, 8, 1)),
            (500000000, datetime(2016, 5, 1)),
            (1000000000, datetime(2018, 12, 1)),
            (1500000000, datetime(2020, 8, 1)),
            (2000000000, datetime(2021, 12, 1)),
            (2500000000, datetime(2023, 3, 1)),
            (3000000000, datetime(2024, 6, 1)),
            (3500000000, datetime(2025, 9, 1)),
        ]
        
        closest_point = min(reference_points, key=lambda x: abs(x[0] - user_id))
        closest_user_id, closest_date = closest_point
        
        id_difference = user_id - closest_user_id
        days_difference = id_difference / 6000000
        estimated_date = closest_date + timedelta(days=days_difference)
        
        current_date = datetime.now()
        if estimated_date > current_date:
            estimated_date = current_date - timedelta(days=30)
        
        return estimated_date
    
    def calculate_age_from_estimation(self, creation_date):
        today = datetime.now()
        delta = relativedelta(today, creation_date)
        
        years, months, days = delta.years, delta.months, delta.days
        parts = []
        if years > 0: parts.append(f"{years} years")
        if months > 0: parts.append(f"{months} months")
        if days > 0: parts.append(f"{days} days")
        
        return ", ".join(parts) if parts else "Created today"
    
    def estimate_smart_status(self, user_id, username, is_premium, is_bot):
        if is_bot:
            return "Bot"
        
        activity_score = 0
        if username: activity_score += 40
        if is_premium: activity_score += 30
        
        if user_id > 2000000000: activity_score += 20
        elif user_id > 1000000000: activity_score += 15
        else: activity_score += 5
        
        consistent_var = (user_id % 30)
        total_score = min(activity_score + consistent_var, 100)
        
        if total_score > 70:
            return "Recently online"
        elif total_score > 50:
            return "Within this week"
        elif total_score > 30:
            return "Within this month"
        else:
            return "Long time ago"

# 📦 Formatting Functions
def format_bot_information(data):
    full_name = data.get('first_name', '')
    if data.get('last_name'): full_name += f" {data.get('last_name')}"
    
    response = f"""🤖 <b>Bot Information</b>

🆔 <b>ID:</b> <code>{data.get('id', 'N/A')}</code>
📛 <b>Username:</b> @{data.get('username', 'N/A')}
👨‍💼 <b>Full Name:</b> {full_name or 'N/A'}
📅 <b>Account Created:</b> {data.get('estimated_created', 'N/A')}
⏳ <b>Account Age:</b> {data.get('estimated_age', 'N/A')}
⚙️ <b>Bot Settings:</b>
• Can Join Groups: {'✅' if data.get('can_join_groups') else '❌'}
• Can Read Messages: {'✅' if data.get('can_read_all_group_messages') else '❌'}
• Inline Mode: {'✅' if data.get('supports_inline_queries') else '❌'}
✅ <b>Verified:</b> {'✅' if data.get('is_verified') else '❌'}"""
    return response

def format_user_information(data):
    full_name = data.get('first_name', '')
    if data.get('last_name'): full_name += f" {data.get('last_name')}"
    
    response = f"""👤 <b>User Information</b>

🆔 <b>ID:</b> <code>{data.get('id', 'N/A')}</code>
👨‍💼 <b>Full Name:</b> {full_name or 'N/A'}
📛 <b>Username:</b> @{data.get('username', 'N/A')}
📅 <b>Account Created:</b> {data.get('estimated_created', 'N/A')}
⏳ <b>Account Age:</b> {data.get('estimated_age', 'N/A')}
📱 <b>Status:</b> {data.get('estimated_status', 'N/A')}
💎 <b>Premium:</b> {'✅' if data.get('is_premium') else '❌'}
✅ <b>Verified:</b> {'✅' if data.get('is_verified') else '❌'}"""
    
    if data.get('language_code'): response += f"\n🌐 <b>Language:</b> {data.get('language_code')}"
    return response

def format_group_information(data):
    response = f"""👥 <b>Group Information</b>

🆔 <b>ID:</b> <code>{data.get('id', 'N/A')}</code>
📛 <b>Title:</b> {data.get('title', 'N/A')}
👥 <b>Username:</b> @{data.get('username', 'N/A')}
📊 <b>Type:</b> {data.get('type', 'N/A').title()}
🔒 <b>Privacy:</b> {'Public' if data.get('username') else 'Private'}
✅ <b>Verified:</b> {'✅' if data.get('is_verified') else '❌'}
👥 <b>Members Count:</b> {data.get('members_count', 'N/A'):,}"""
    
    if data.get('invite_link'): response += f"\n🔗 <b>Invite Link:</b> {data.get('invite_link')}"
    return response

def format_supergroup_information(data):
    response = f"""💬 <b>Supergroup Information</b>

🆔 <b>ID:</b> <code>{data.get('id', 'N/A')}</code>
📛 <b>Title:</b> {data.get('title', 'N/A')}
👥 <b>Username:</b> @{data.get('username', 'N/A')}
🔒 <b>Privacy:</b> {'Public' if data.get('username') else 'Private'}
✅ <b>Verified:</b> {'✅' if data.get('is_verified') else '❌'}
👥 <b>Members Count:</b> {data.get('members_count', 'N/A'):,}"""
    
    if data.get('invite_link'): response += f"\n🔗 <b>Invite Link:</b> {data.get('invite_link')}"
    return response

def format_channel_information(data):
    response = f"""📢 <b>Channel Information</b>

🆔 <b>ID:</b> <code>{data.get('id', 'N/A')}</code>
📛 <b>Title:</b> {data.get('title', 'N/A')}
👥 <b>Username:</b> @{data.get('username', 'N/A')}
🔒 <b>Privacy:</b> {'Public' if data.get('username') else 'Private'}
✅ <b>Verified:</b> {'✅' if data.get('is_verified') else '❌'}
👥 <b>Subscribers:</b> {data.get('members_count', 'N/A'):,}"""
    
    if data.get('invite_link'): response += f"\n🔗 <b>Invite Link:</b> {data.get('invite_link')}"
    return response

# ===================================================================
# 🌐 Flask ওয়েব অ্যাপ্লিকেশন সেটআপ
# ===================================================================

app = Flask(__name__)
bot_api = OfficialBotAPI(BOT_TOKEN)

# HTML টেমপ্লেট
HTML_TEMPLATE = """
<!doctype html>
<html lang="bn">
<head>
    <meta charset="utf-8">
    <title>Telegram ID/Username Checker</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background-color: #f0f2f5; color: #1c1e21; text-align: center; padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,.1); }
        h1 { color: #0088cc; }
        form { margin-bottom: 20px; }
        input[type="text"] { width: 80%; padding: 10px; margin-bottom: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        input[type="submit"] { background-color: #0088cc; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; }
        input[type="submit"]:hover { background-color: #0077b3; }
        .result-box { text-align: left; background: #e9ebee; padding: 15px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; }
        .error-box { background: #fcebeb; color: #d9534f; padding: 10px; border: 1px solid #d9534f; border-radius: 4px; text-align: center; }
        .result-box b { font-weight: bold; }
        .result-box code { background-color: #f7f7f7; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Telegram আইডি/ইউজারনেম চেকার</h1>
        <form method="POST">
            <label for="query">আইডি (যেমন: 12345) অথবা ইউজারনেম (যেমন: @example):</label><br>
            <input type="text" id="query" name="query" placeholder="Telegram ID বা Username দিন" value="{{ query }}" required><br>
            <input type="submit" value="তথ্য দেখুন">
        </form>
        
        {% if result %}
            {% if status == 'error' %}
                <div class="error-box">{{ result }}</div>
            {% else %}
                <h2>ফলাফল:</h2>
                <div class="result-box">{{ result|safe }}</div>
            {% endif %}
        {% endif %}
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def home():
    query = ""
    result_html = ""
    status = ""
    
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        
        if not BOT_TOKEN:
            result_html = "❌ সার্ভার কনফিগারেশন ত্রুটি: BOT_TOKEN Environment Variable সেট করা নেই।"
            status = "error"
        elif not query:
            result_html = "দয়া করে একটি আইডি বা ইউজারনেম প্রদান করুন।"
            status = "error"
        else:
            api_result = bot_api.get_chat_info(query)
            
            if api_result['status'] == 'error':
                err_msg = api_result['message']
                if "chat not found" in err_msg.lower() or "user not found" in err_msg.lower():
                    result_html = f"❌ এন্ট্রি খুঁজে পাওয়া যায়নি: '{query}'। আইডি সঠিক কিনা অথবা ইউজারনেম @ সহ দেওয়া হয়েছে কিনা, তা পরীক্ষা করুন।"
                else:
                    result_html = f"❌ ত্রুটি: {err_msg}"
                status = "error"
            else:
                data = api_result['data']
                
                # সঠিক ফরম্যাটিং ফাংশন নির্বাচন
                if data.get('is_bot'):
                    result_html = format_bot_information(data)
                elif data.get('type') == 'private':
                    result_html = format_user_information(data)
                elif data.get('type') == 'group':
                    result_html = format_group_information(data)
                elif data.get('type') == 'supergroup':
                    result_html = format_supergroup_information(data)
                elif data.get('type') == 'channel':
                    result_html = format_channel_information(data)
                else:
                    result_html = format_user_information(data)
        
    return render_template_string(HTML_TEMPLATE, query=query, result=Markup(result_html), status=status)

if __name__ == '__main__':
    app.run(debug=True)
