import os
import sys
import asyncio
import time
import psycopg2
import pandas as pd

from psycopg2.extras import execute_batch
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash, check_password_hash

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# Load environment variables
load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
USER_TOKEN = os.getenv("USER_BOT_TOKEN")
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode()

cipher_suite = Fernet(FERNET_KEY)

# Conversation States
GET_USER, GET_PASS = range(2)

# ======================================
# DATABASE CONNECTION
# ======================================

def get_connection():
    retries = 3
    safe_url = DB_URL
    if "sslmode=require" not in safe_url:
        safe_url += "?sslmode=require"

    for attempt in range(retries):
        try:
            return psycopg2.connect(safe_url)
        except psycopg2.OperationalError:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                raise

def verify_login(username, password, role):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pass, role FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        if user:
            db_pass, db_role = user
            if check_password_hash(db_pass, password) and db_role == role:
                return True
    return False

# ======================================
# SHARED LOGIN FLOW (NO COMMANDS)
# ======================================

async def start_login_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by the 'Login' button"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👤 من فضلك أدخل اسم المستخدم:")
    return GET_USER

async def process_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tmp_user'] = update.message.text
    await update.message.reply_text("🔑 من فضلك أدخل كلمة المرور:")
    return GET_PASS

# ======================================
# USER BOT LOGIC
# ======================================

async def user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔐 تسجيل الدخول", callback_data="start_login")]]
    await update.message.reply_text("👋 مرحبا بك في بوت الأكواد", reply_markup=InlineKeyboardMarkup(keyboard))

async def process_user_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('tmp_user')
    password = update.message.text
    
    if verify_login(username, password, "user"):
        context.user_data['authenticated'] = True
        return await show_user_main_menu(update, context)
    else:
        await update.message.reply_text("❌ بيانات غير صحيحة. حاول مرة أخرى عبر /start")
        return ConversationHandler.END

async def show_user_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT name FROM code WHERE parent_id IS NULL")
        tables = [r[0] for r in cur.fetchall()]

    keyboard = [[InlineKeyboardButton(t, callback_data=f"table_{t}")] for t in tables]
    
    msg = "📂 القائمة الرئيسية - اختر القسم:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def user_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("table_"):
        table = data.replace("table_", "")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT name FROM code WHERE name LIKE %s AND parent_id IS NOT NULL", (f"{table}%",))
            groups = [r[0] for r in cur.fetchall()]

        keyboard = [[InlineKeyboardButton(g, callback_data=f"group_{g}")] for g in groups]
        keyboard.append([InlineKeyboardButton("⬅️ عودة", callback_data="back_to_main")])
        await query.edit_message_text(f"📁 قسم {table}: اختر المجموعة", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "back_to_main":
        await show_user_main_menu(update, context)

    elif data.startswith("group_"):
        group = data.replace("group_", "")
        sql = """
            UPDATE code SET is_active = FALSE, used_at = NOW()
            WHERE id = (SELECT id FROM code WHERE name=%s AND is_active=TRUE LIMIT 1 FOR UPDATE SKIP LOCKED)
            RETURNING code
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (group,))
            result = cur.fetchone()
            conn.commit()

        if result:
            code = cipher_suite.decrypt(result[0].encode()).decode()
            await query.edit_message_text(f"✅ الكود الخاص بك:\n`{code}`", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ نأسف، الأكواد انتهت لهذه المجموعة.")

# ======================================
# ADMIN BOT LOGIC
# ======================================

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("⚙️ دخول لوحة التحكم", callback_data="start_login")]]
    await update.message.reply_text("💎 لوحة تحكم الإدارة", reply_markup=InlineKeyboardMarkup(keyboard))

async def process_admin_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('tmp_user')
    password = update.message.text
    
    if verify_login(username, password, "admin"):
        keyboard = [
            [InlineKeyboardButton("📊 الاحصائيات", callback_data="stats")],
            [InlineKeyboardButton("📥 تصدير Excel", callback_data="export")]
        ]
        await update.message.reply_text("✅ تم الدخول بنجاح", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ فشل تسجيل دخول الأدمن.")
        return ConversationHandler.END

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "stats":
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM code")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM code WHERE is_active=TRUE")
            active = cur.fetchone()[0]
        await query.edit_message_text(f"📈 الإحصائيات:\n\nإجمالي الأكواد: {total}\nالمتاحة: {active}")

    elif data == "export":
        keyboard = [
            [InlineKeyboardButton("الكل", callback_data="exp_all")],
            [InlineKeyboardButton("المتاحة فقط", callback_data="exp_active")]
        ]
        await query.edit_message_text("اختر البيانات للتصدير:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("exp_"):
        condition = "WHERE is_active=TRUE" if "active" in data else ""
        with get_connection() as conn:
            df = pd.read_sql(f"SELECT name, code, is_active FROM code {condition}", conn)
        
        df["code"] = df["code"].apply(lambda c: cipher_suite.decrypt(c.encode()).decode())
        file_path = "export.xlsx"
        df.to_excel(file_path, index=False)
        await query.message.reply_document(document=open(file_path, 'rb'))

# ======================================
# MAIN RUNNER
# ======================================

async def main():
    # Setup User Bot
    user_app = ApplicationBuilder().token(USER_TOKEN).build()
    
    user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_login_flow, pattern="^start_login$")],
        states={
            GET_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_username)],
            GET_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_user_password)],
        },
        fallbacks=[],
    )
    
    user_app.add_handler(CommandHandler("start", user_start))
    user_app.add_handler(user_conv)
    user_app.add_handler(CallbackQueryHandler(user_callback_handler))

    # Setup Admin Bot
    admin_app = ApplicationBuilder().token(ADMIN_TOKEN).build()
    
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_login_flow, pattern="^start_login$")],
        states={
            GET_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_username)],
            GET_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_password)],
        },
        fallbacks=[],
    )
    
    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(admin_conv)
    admin_app.add_handler(CallbackQueryHandler(admin_callback_handler))

    # Run both
    await asyncio.gather(
        user_app.initialize(),
        admin_app.initialize()
    )
    await asyncio.gather(
        user_app.start(),
        admin_app.start()
    )
    await asyncio.gather(
        user_app.updater.start_polling(),
        admin_app.updater.start_polling()
    )
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
