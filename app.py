import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# =========================
# CONFIG (set these as env vars on Render)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()  # e.g. https://ex-v1.onrender.com

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable required")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID environment variable required (your Telegram numeric id)")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== DATABASE ==========
DB_PATH = "bot.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            banned INTEGER DEFAULT 0,
            free_redeem_used INTEGER DEFAULT 0,
            premium_until TEXT DEFAULT NULL,
            pending_action TEXT DEFAULT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            key TEXT PRIMARY KEY,
            expires_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS redeem_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            details TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ========== UTILITIES ==========
def add_or_update_user(user):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    if c.fetchone():
        c.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (user.username or "", user.first_name or "", user.id))
    else:
        c.execute("INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (user.id, user.username or "", user.first_name or ""))
    conn.commit()
    conn.close()

def set_pending(user_id, action):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET pending_action=? WHERE user_id=?", (action, user_id))
    conn.commit()
    conn.close()

def get_user_row(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r

def mark_free_redeem_used(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET free_redeem_used=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def set_premium(user_id, until_iso):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET premium_until=? WHERE user_id=?", (until_iso, user_id))
    conn.commit()
    conn.close()

def add_key_to_db(key, expires_iso):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO keys (key, expires_at) VALUES (?, ?)", (key, expires_iso))
    conn.commit()
    conn.close()

def pop_key_from_db(key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT expires_at FROM keys WHERE key=?", (key,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    expires_at = row["expires_at"]
    c.execute("DELETE FROM keys WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return expires_at

def key_exists(key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT expires_at FROM keys WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row["expires_at"] if row else None

def add_redeem_request(user_id, username, details):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("INSERT INTO redeem_requests (user_id, username, details, created_at) VALUES (?, ?, ?, ?)",
              (user_id, username or "", details, now))
    conn.commit()
    conn.close()

def ban_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def list_all_user_ids():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = [r["user_id"] for r in c.fetchall()]
    conn.close()
    return rows

def is_premium_active(premium_until_iso):
    if not premium_until_iso:
        return False
    try:
        return datetime.fromisoformat(premium_until_iso) > datetime.utcnow()
    except:
        return False

# ========== KEY GENERATION (admin) ==========
def generate_key(days):
    k = str(uuid.uuid4()).upper().replace('-', '')[:16]
    expires = (datetime.utcnow() + timedelta(days=int(days))).isoformat()
    add_key_to_db(k, expires)
    return k, expires

# ========== KEYBOARD / MENU ==========
def main_menu_markup():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Redeem Request", callback_data="redeem"))
    kb.add(InlineKeyboardButton("Buy Premium", callback_data="buy"))
    kb.add(InlineKeyboardButton("Service", callback_data="service"))
    kb.add(InlineKeyboardButton("Dev", callback_data="dev"))
    return kb

# ========== BOT HANDLERS ==========
@bot.message_handler(commands=['start'])
def cmd_start(m):
    add_or_update_user(m.from_user)
    userrow = get_user_row(m.from_user.id)
    if userrow and userrow["banned"]:
        bot.send_message(m.chat.id, "🚫 You are banned.")
        return
    text = (f"👋 Hello {m.from_user.first_name or m.from_user.username}!\n\n"
            "Use the buttons below to interact.")
    bot.send_message(m.chat.id, text, reply_markup=main_menu_markup())

@bot.callback_query_handler(func=lambda call: True)
def cb_handler(call):
    uid = call.from_user.id
    add_or_update_user(call.from_user)
    row = get_user_row(uid)
    if row and row["banned"]:
        bot.answer_callback_query(call.id, "🚫 You are banned.")
        return

    if call.data == "redeem":
        # check free or premium usage
        if row and row["free_redeem_used"] == 1 and not is_premium_active(row["premium_until"]):
            bot.send_message(uid, "❌ Free users can redeem only once. Buy premium for unlimited requests.")
            return
        set_pending(uid, "redeem")
        bot.send_message(uid, "✍️ Enter details for redeem request:")

    elif call.data == "buy":
        set_pending(uid, "buy_key")
        bot.send_message(uid, "🔑 Please send your premium key to activate:")

    elif call.data == "service":
        bot.send_message(uid, "📦 Services:\n1. Prime Video\n2. Spotify\n3. Crunchyroll\n4. Turbo VPN\n5. Hotspot Shield VPN")

    elif call.data == "dev":
        bot.send_message(uid, "@YourAizen")

    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: True)
def all_messages(m):
    add_or_update_user(m.from_user)
    uid = m.from_user.id
    row = get_user_row(uid)
    if row and row["banned"]:
        return

    pending = row["pending_action"] if row else None
    text = m.text.strip() if m.text else ""

    if pending == "redeem":
        # record and forward to admin
        add_redeem_request(uid, m.from_user.username or "", text)
        bot.send_message(ADMIN_ID, f"📥 Redeem request from @{m.from_user.username or uid} ({uid}):\n\n{text}")
        # if free, mark used
        if row and row["free_redeem_used"] == 0 and not is_premium_active(row["premium_until"]):
            mark_free_redeem_used(uid)
        set_pending(uid, None)
        bot.send_message(uid, "✅ Your redeem request was sent to admin. Thank you!")
        return

    if pending == "buy_key":
        key = text
        expires_iso = key_exists(key)
        if not expires_iso:
            bot.send_message(uid, "❌ Invalid key. Please check and try again.")
            set_pending(uid, None)
            return
        # Activate premium for user until expires_iso
        set_premium(uid, expires_iso)
        # remove key (single-use)
        pop_key_from_db(key)
        bot.send_message(uid, f"💎 Premium activated until {expires_iso}")
        bot.send_message(ADMIN_ID, f"🔔 User @{m.from_user.username or uid} ({uid}) activated premium until {expires_iso} with key {key}")
        set_pending(uid, None)
        return

    # Default: reply with menu
    bot.send_message(uid, "Use the menu below:", reply_markup=main_menu_markup())

# ========== ADMIN COMMANDS (telegram) ==========
@bot.message_handler(commands=['genk'])
def admin_genk(m):
    if m.from_user.id != ADMIN_ID:
        return
    parts = m.text.split()
    if len(parts) < 2:
        bot.send_message(m.chat.id, "Usage: /genk <days>")
        return
    try:
        days = int(parts[1])
    except:
        bot.send_message(m.chat.id, "Days must be an integer.")
        return
    key, expires = generate_key(days)
    bot.send_message(m.chat.id, f"✅ Key generated:\n`{key}`\nExpires: {expires}", parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def admin_broadcast(m):
    if m.from_user.id != ADMIN_ID:
        return
    text = m.text.replace("/broadcast", "", 1).strip()
    if not text:
        bot.send_message(m.chat.id, "Usage: /broadcast <message>")
        return
    ids = list_all_user_ids()
    sent = 0
    for uid in ids:
        try:
            bot.send_message(uid, f"📢 {text}")
            sent += 1
        except Exception:
            pass
    bot.send_message(m.chat.id, f"Broadcast sent to {sent} users.")

@bot.message_handler(commands=['ban'])
def admin_ban(m):
    if m.from_user.id != ADMIN_ID:
        return
    parts = m.text.split()
    if len(parts) < 2:
        bot.send_message(m.chat.id, "Usage: /ban <user_id>")
        return
    try:
        target = int(parts[1])
    except:
        bot.send_message(m.chat.id, "Invalid user id.")
        return
    ban_user(target)
    bot.send_message(m.chat.id, f"✅ Banned {target}")
    try:
        bot.send_message(target, "🚫 You have been banned by admin.")
    except:
        pass

@bot.message_handler(commands=['unban'])
def admin_unban(m):
    if m.from_user.id != ADMIN_ID:
        return
    parts = m.text.split()
    if len(parts) < 2:
        bot.send_message(m.chat.id, "Usage: /unban <user_id>")
        return
    try:
        target = int(parts[1])
    except:
        bot.send_message(m.chat.id, "Invalid user id.")
        return
    unban_user(target)
    bot.send_message(m.chat.id, f"✅ Unbanned {target}")
    try:
        bot.send_message(target, "✅ You have been unbanned by admin.")
    except:
        pass

@bot.message_handler(commands=['st'])
def admin_status(m):
    if m.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned=1")
    banned = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE free_redeem_used=1")
    free_used = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE premium_until IS NOT NULL AND premium_until > ?", (datetime.utcnow().isoformat(),))
    premium_users = c.fetchone()[0]
    conn.close()
    msg = (f"📊 Bot Status\n\nTotal users: {total}\nPremium active: {premium_users}\nFree redeem used: {free_used}\nBanned: {banned}")
    bot.send_message(m.chat.id, msg)

# ========== FLASK WEBHOOK ROUTES ==========
@app.route("/")
def index():
    return "Bot is running!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        # don't crash on bad updates
        print("Webhook error:", e)
    return "OK", 200

# route to (re)install webhook manually
@app.route("/setwebhook")
def set_webhook_route():
    if not RENDER_EXTERNAL_URL:
        return "RENDER_EXTERNAL_URL not set", 400
    url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/{BOT_TOKEN}"
    bot.remove_webhook()
    ok = bot.set_webhook(url=url)
    return f"set webhook: {ok} -> {url}"

# ========== STARTUP ==========
if __name__ == "__main__":
    # try to set webhook on start if URL provided
    if RENDER_EXTERNAL_URL:
        url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/{BOT_TOKEN}"
        bot.remove_webhook()
        bot.set_webhook(url=url)
        print("Webhook set to:", url)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
