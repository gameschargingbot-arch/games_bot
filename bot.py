import os
import asyncio
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash, check_password_hash
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from keep_alive import keep_alive
import sys

keep_alive()
sys.stdout.reconfigure(encoding='utf-8')
# ==========================================
# 1. SETUP & SECURITY
# ==========================================
load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
USER_TOKEN = os.getenv("USER_BOT_TOKEN")
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode() if os.getenv("FERNET_KEY") else None

cipher_suite = Fernet(FERNET_KEY) if FERNET_KEY else None

# In-memory login sessions: {telegram_user_id: True}
admin_sessions = {}
user_sessions = {}

import time

def get_connection():
    """Tries to connect, and waits if the Neon database is waking up from sleep."""
    retries = 3
    
    # Ensure sslmode=require is attached, as Neon strictly rejects non-SSL connections
    safe_url = DB_URL
    if "sslmode=require" not in safe_url:
        safe_url += "?sslmode=require" if "?" not in safe_url else "&sslmode=require"

    for attempt in range(retries):
        try:
            return psycopg2.connect(safe_url)
        except psycopg2.OperationalError as e:
            if attempt < retries - 1:
                print(f"⚠️ Database is waking up... Retrying in 2 seconds (Attempt {attempt+1}/{retries})")
                time.sleep(2)
            else:
                print("❌ Database failed to wake up.")
                raise e

# ==========================================
# 2. DATABASE OPERATIONS
# ==========================================

def verify_login(username, password, required_role):
    """Checks DB for user and verifies hashed password."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pass, role FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        if user:
            db_hash, role = user
            if check_password_hash(db_hash, password) and role == required_role:
                return True
    return False

def create_default_admin():
    """Creates an admin if the table is empty so you aren't locked out!"""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            hashed_pw = generate_password_hash("admin123")
            cur.execute("INSERT INTO users (username, pass, role) VALUES (%s, %s, %s)", ("admin", hashed_pw, "admin"))
            conn.commit()
            print("🚨 Default admin created! Username: admin | Password: admin123")

def fetch_stats():
    """Gathers all requested statistics."""
    stats = {}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM code")
        stats['total'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM code WHERE is_active = TRUE")
        stats['active'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM code WHERE is_active = FALSE")
        stats['unactive'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM code WHERE used_at >= CURRENT_DATE")
        stats['today'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM code WHERE used_at >= CURRENT_DATE - INTERVAL '1 week'")
        stats['week'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM code WHERE used_at >= CURRENT_DATE - INTERVAL '1 month'")
        stats['month'] = cur.fetchone()[0]
    return stats

# ==========================================
# 3. USER BOT HANDLERS
# ==========================================

async def user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Please login using the command:\n`/login username password`", 
        parse_mode="Markdown"
    )

async def user_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, username, password = update.message.text.split(" ", 2)
        if verify_login(username, password, "user"):
            user_sessions[update.message.from_user.id] = True
            await update.message.reply_text("✅ Login successful! Send /menu to view available groups.")
        else:
            await update.message.reply_text("❌ Invalid username, password, or role.")
    except ValueError:
        await update.message.reply_text("⚠️ Format: `/login username password`", parse_mode="Markdown")

async def user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_sessions.get(update.message.from_user.id):
        await update.message.reply_text("🔒 You must /login first.")
        return

    # Find all unique names that have active codes
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT name FROM code WHERE is_active = TRUE")
        names = [row[0] for row in cur.fetchall()]

    if not names:
        await update.message.reply_text("📦 No active codes available right now.")
        return

    # Create a button for each name
    keyboard = [[InlineKeyboardButton(name, callback_data=f"get_{name}")] for name in names]
    await update.message.reply_text("Select a group to get a code:", reply_markup=InlineKeyboardMarkup(keyboard))

async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not user_sessions.get(query.from_user.id):
        await query.edit_message_text("🔒 Session expired. Please /login again.")
        return

    if query.data.startswith("get_"):
        group_name = query.data.replace("get_", "")
        
        # 🚨 THE LOCKING MECHANISM 🚨
        sql = """
            UPDATE code SET is_active = FALSE, used_at = NOW() 
            WHERE id = (
                SELECT id FROM code WHERE name = %s AND is_active = TRUE LIMIT 1 FOR UPDATE SKIP LOCKED
            ) RETURNING code;
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (group_name,))
            result = cur.fetchone()
            conn.commit()

        if result:
            decrypted_code = cipher_suite.decrypt(result[0].encode()).decode()
            await query.edit_message_text(f"✅ Here is your code for **{group_name}**:\n`{decrypted_code}`", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"❌ Sorry, all codes for {group_name} were just taken!")

# ==========================================
# 4. ADMIN BOT HANDLERS
# ==========================================

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ Admin Panel. Login using:\n`/login username password`", parse_mode="Markdown")

async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, username, password = update.message.text.split(" ", 2)
        if verify_login(username, password, "admin"):
            admin_sessions[update.message.from_user.id] = True
            menu = (
                "✅ Admin Login Successful!\n\n"
                "**Available Commands:**\n"
                "📊 `/stats` - View database statistics\n"
                "➕ `/addcodes GroupName\ncode1\ncode2` - Add new codes\n"
                "👤 `/adduser user pass role` - Create user/admin\n"
                "🔑 `/changepass user newpass` - Change user password\n"
                "🗑️ `/deluser username` - Delete a user"
            )
            await update.message.reply_text(menu, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Invalid Admin credentials.")
    except ValueError:
        await update.message.reply_text("⚠️ Format: `/login username password`", parse_mode="Markdown")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_sessions.get(update.message.from_user.id): return
    
    stats = fetch_stats()
    msg = (
        "📊 **System Statistics** 📊\n\n"
        f"🔹 Total Codes: {stats['total']}\n"
        f"🟢 Active: {stats['active']} | 🔴 Used: {stats['unactive']}\n\n"
        "📈 **Usage History:**\n"
        f"• Used Today: {stats['today']}\n"
        f"• Used Last 7 Days: {stats['week']}\n"
        f"• Used Last 30 Days: {stats['month']}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def admin_add_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_sessions.get(update.message.from_user.id): return
    
    lines = update.message.text.split('\n')
    try:
        # line 0 is the command and group name (e.g. "/addcodes Netflix")
        command_part = lines[0].split(" ", 1)
        group_name = command_part[1].strip()
        raw_codes = lines[1:]
        
        # Encrypt codes
        clean_codes = [code.strip() for code in raw_codes if code.strip()]
        data_to_insert = [(group_name, cipher_suite.encrypt(c.encode()).decode(), True) for c in clean_codes]
        
        sql = "INSERT INTO code (name, code, is_active) VALUES (%s, %s, %s)"
        with get_connection() as conn, conn.cursor() as cur:
            execute_batch(cur, sql, data_to_insert)
            conn.commit()
            
        await update.message.reply_text(f"✅ Successfully added {len(clean_codes)} codes to group '{group_name}'!")
    except Exception as e:
        await update.message.reply_text("⚠️ Format:\n`/addcodes GroupName\ncode1\ncode2\ncode3`", parse_mode="Markdown")

async def admin_user_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_sessions.get(update.message.from_user.id): return
    
    text = update.message.text
    try:
        if text.startswith("/adduser"):
            _, username, password, role = text.split(" ")
            hashed_pw = generate_password_hash(password)
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO users (username, pass, role) VALUES (%s, %s, %s)", (username, hashed_pw, role))
                conn.commit()
            await update.message.reply_text(f"✅ User '{username}' created as '{role}'.")

        elif text.startswith("/changepass"):
            _, username, newpass = text.split(" ")
            hashed_pw = generate_password_hash(newpass)
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE users SET pass = %s WHERE username = %s", (hashed_pw, username))
                conn.commit()
            await update.message.reply_text(f"✅ Password changed for '{username}'.")

        elif text.startswith("/deluser"):
            _, username = text.split(" ")
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE username = %s", (username,))
                conn.commit()
            await update.message.reply_text(f"✅ User '{username}' deleted.")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing command. Check your spacing.")

# ==========================================
# 5. ASYNC LOOP RUNNER
# ==========================================
async def main():
    print("Checking Database...")
    create_default_admin()

    print("Building Bots...")
    admin_app = ApplicationBuilder().token(ADMIN_TOKEN).build()
    user_app = ApplicationBuilder().token(USER_TOKEN).build()

    # Admin Routing
    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(CommandHandler("login", admin_login))
    admin_app.add_handler(CommandHandler("stats", admin_stats))
    admin_app.add_handler(CommandHandler("addcodes", admin_add_codes))
    admin_app.add_handler(MessageHandler(filters.Regex(r'^/(adduser|changepass|deluser)'), admin_user_management))

    # User Routing
    user_app.add_handler(CommandHandler("start", user_start))
    user_app.add_handler(CommandHandler("login", user_login))
    user_app.add_handler(CommandHandler("menu", user_menu))
    user_app.add_handler(CallbackQueryHandler(user_callback))

    # Boot them up
    await admin_app.initialize()
    await admin_app.start()
    await admin_app.updater.start_polling()
    print("🟢 Admin Bot Started!")

    await user_app.initialize()
    await user_app.start()
    await user_app.updater.start_polling()
    print("🟢 User Bot Started!")

    print("🚀 System Online! Press Ctrl+C to stop.")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    if not FERNET_KEY:
        print("🚨 CRITICAL: Missing FERNET_KEY in .env file! Codes cannot be encrypted.")
    else:

        asyncio.run(main())
