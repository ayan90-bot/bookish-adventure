import os
import time
import imghdr
from flask import Flask, request
import telebot
from datetime import datetime, timedelta

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Render env me set karo
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # Apna ID daalo

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Data storage (temporary memory, production me DB use karo)
users = {}
premium_keys = {}
banned_users = set()

# =========================
# Helper Functions
# =========================
def is_premium(user_id):
    if user_id in premium_keys:
        return datetime.now() < premium_keys[user_id]
    return False

def gen_key(days):
    key = f"KEY-{int(time.time())}"
    expiry = datetime.now() + timedelta(days=days)
    premium_keys[key] = expiry
    return key, expiry

# =========================
# Commands
# =========================
@bot.message_handler(commands=["start"])
def start_cmd(message):
    if message.from_user.id in banned_users:
        bot.send_message(message.chat.id, "🚫 You are banned from using this bot.")
        return

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("1️⃣ Redeem Request", callback_data="redeem"))
    markup.add(telebot.types.InlineKeyboardButton("2️⃣ Buy Premium", callback_data="buy"))
    markup.add(telebot.types.InlineKeyboardButton("3️⃣ Service", callback_data="service"))
    markup.add(telebot.types.InlineKeyboardButton("4️⃣ Dev", callback_data="dev"))
    bot.send_message(message.chat.id, "📍 Choose an option:", reply_markup=markup)

@bot.message_handler(commands=["genk"])
def genk_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        days = int(message.text.split()[1])
        key, expiry = gen_key(days)
        bot.send_message(message.chat.id, f"✅ Key Generated: `{key}`\nExpires: {expiry}", parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Usage: /genk <days>")

@bot.message_handler(commands=["ban"])
def ban_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(message.text.split()[1])
        banned_users.add(uid)
        bot.send_message(message.chat.id, f"✅ User {uid} banned.")
    except:
        bot.send_message(message.chat.id, "❌ Usage: /ban <user_id>")

@bot.message_handler(commands=["unban"])
def unban_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(message.text.split()[1])
        banned_users.discard(uid)
        bot.send_message(message.chat.id, f"✅ User {uid} unbanned.")
    except:
        bot.send_message(message.chat.id, "❌ Usage: /unban <user_id>")

@bot.message_handler(commands=["broadcast"])
def broadcast_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/broadcast ", "")
    for uid in users:
        try:
            bot.send_message(uid, f"📢 {text}")
        except:
            pass
    bot.send_message(message.chat.id, "✅ Broadcast sent.")

# =========================
# Button Handlers
# =========================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.from_user.id
    if uid in banned_users:
        bot.answer_callback_query(call.id, "🚫 You are banned.")
        return

    if call.data == "redeem":
        if uid not in users:
            users[uid] = {"redeemed": False}
        if not is_premium(uid) and users[uid]["redeemed"]:
            bot.send_message(uid, "❌ Free users can redeem only once. Buy premium for unlimited.")
            return
        bot.send_message(uid, "💬 Enter Details:")
        users[uid]["awaiting_details"] = True

    elif call.data == "buy":
        bot.send_message(uid, "🔑 Send me your premium key:")
        users[uid] = users.get(uid, {})
        users[uid]["awaiting_key"] = True

    elif call.data == "service":
        bot.send_message(uid, "📌 Choose service:\n1. Prime Video\n2. Spotify\n3. Crunchyroll\n4. Turbo VPN\n5. Hotspot Shield VPN")

    elif call.data == "dev":
        bot.send_message(uid, "@YourAizen")

# =========================
# Message Handler
# =========================
@bot.message_handler(func=lambda m: True)
def handle_all(message):
    uid = message.from_user.id
    if uid in banned_users:
        return

    if uid not in users:
        users[uid] = {}

    # Redeem details
    if users[uid].get("awaiting_details"):
        bot.send_message(ADMIN_ID, f"📥 Redeem Request from {uid}:\n{message.text}")
        bot.send_message(uid, "✅ Details sent to admin.")
        users[uid]["redeemed"] = True
        users[uid]["awaiting_details"] = False

    # Premium key
    elif users[uid].get("awaiting_key"):
        key = message.text.strip()
        if key in premium_keys:
            expiry = premium_keys[key]
            premium_keys[uid] = expiry
            del premium_keys[key]
            bot.send_message(uid, f"✅ Premium activated till {expiry}")
            bot.send_message(ADMIN_ID, f"🔔 User {uid} activated premium till {expiry}")
        else:
            bot.send_message(uid, "❌ Invalid key.")
        users[uid]["awaiting_key"] = False

# =========================
# Flask Routes
# =========================
@app.route("/")
def index():
    return "Bot is running!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = request.get_data().decode("utf-8")
    bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "OK", 200

# =========================
# Main
# =========================
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))
    bot.remove_webhook()
    bot.set_webhook(url=f"{os.getenv('RENDER_EXTERNAL_URL')}/{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=PORT)
