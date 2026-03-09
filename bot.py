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
    filters
)

from keep_alive import keep_alive

keep_alive()
sys.stdout.reconfigure(encoding='utf-8')

# ======================================
# ENV
# ======================================

load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
USER_TOKEN = os.getenv("USER_BOT_TOKEN")
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode()

cipher_suite = Fernet(FERNET_KEY)

admin_sessions = {}
user_sessions = {}

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
                print("database waking up...")
                time.sleep(2)
            else:
                raise


# ======================================
# LOGIN SYSTEM
# ======================================

def verify_login(username,password,role):

    with get_connection() as conn, conn.cursor() as cur:

        cur.execute(
            "SELECT pass,role FROM users WHERE username=%s",
            (username,)
        )

        user = cur.fetchone()

        if user:

            db_pass , db_role = user

            if check_password_hash(db_pass,password) and db_role == role:
                return True

    return False


# ======================================
# STATS
# ======================================

def fetch_stats():

    stats = {}

    with get_connection() as conn, conn.cursor() as cur:

        cur.execute("SELECT COUNT(*) FROM code")
        stats["total"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM code WHERE is_active=TRUE")
        stats["active"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM code WHERE is_active=FALSE")
        stats["used"] = cur.fetchone()[0]

    return stats


# ======================================
# USER BOT
# ======================================

async def user_start(update:Update,context:ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "👋 مرحبا\n\n"
        "قم بتسجيل الدخول:\n"
        "/login username password"
    )


async def user_login(update:Update,context:ContextTypes.DEFAULT_TYPE):

    try:

        _,username,password = update.message.text.split(" ",2)

        if verify_login(username,password,"user"):

            user_sessions[update.message.from_user.id] = True

            await update.message.reply_text(
                "✅ تم تسجيل الدخول\n"
                "استخدم /menu لعرض الأقسام"
            )

        else:
            await update.message.reply_text("❌ بيانات غير صحيحة")

    except:
        await update.message.reply_text(
            "⚠️ الصيغة:\n/login username password"
        )


# ======================================
# USER MENU
# ======================================

async def user_menu(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if not user_sessions.get(update.message.from_user.id):
        await update.message.reply_text("🔒 يجب تسجيل الدخول")
        return

    with get_connection() as conn, conn.cursor() as cur:

        cur.execute(
            "SELECT DISTINCT name FROM code WHERE parent_id IS NULL"
        )

        tables = [r[0] for r in cur.fetchall()]

    keyboard = [
        [InlineKeyboardButton(t,callback_data=f"table_{t}")]
        for t in tables
    ]

    await update.message.reply_text(
        "📂 اختر القسم",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ======================================
# USER CALLBACK
# ======================================

async def user_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("table_"):

        table = data.replace("table_","")

        with get_connection() as conn, conn.cursor() as cur:

            cur.execute(
                "SELECT DISTINCT name FROM code WHERE name LIKE %s AND parent_id IS NOT NULL",
                (f"{table}%",)
            )

            groups = [r[0] for r in cur.fetchall()]

        keyboard = [
            [InlineKeyboardButton(g,callback_data=f"group_{g}")]
            for g in groups
        ]

        await query.edit_message_text(
            "اختر المجموعة",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


    elif data.startswith("group_"):

        group = data.replace("group_","")

        sql = """

        UPDATE code
        SET is_active = FALSE , used_at = NOW()

        WHERE id = (

        SELECT id FROM code
        WHERE name=%s AND is_active=TRUE
        LIMIT 1
        FOR UPDATE SKIP LOCKED

        )

        RETURNING code

        """

        with get_connection() as conn, conn.cursor() as cur:

            cur.execute(sql,(group,))
            result = cur.fetchone()
            conn.commit()

        if result:

            code = cipher_suite.decrypt(result[0].encode()).decode()

            await query.edit_message_text(
                f"✅ الكود:\n`{code}`",
                parse_mode="Markdown"
            )

        else:

            await query.edit_message_text(
                "❌ انتهت الأكواد"
            )


# ======================================
# ADMIN PANEL
# ======================================

async def admin_login(update:Update,context:ContextTypes.DEFAULT_TYPE):

    try:

        _,username,password = update.message.text.split(" ",2)

        if verify_login(username,password,"admin"):

            admin_sessions[update.message.from_user.id] = True

            keyboard = [

                [InlineKeyboardButton("📊 الاحصائيات",callback_data="stats")],

                [InlineKeyboardButton("➕ اضافة اكواد",callback_data="addcodes")],

                [InlineKeyboardButton("📥 تصدير اكواد Excel",callback_data="export")],

                [InlineKeyboardButton("👤 ادارة المستخدمين",callback_data="users")]

            ]

            await update.message.reply_text(
                "لوحة تحكم الادمن",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        else:

            await update.message.reply_text("❌ خطأ تسجيل الدخول")

    except:

        await update.message.reply_text(
            "/login username password"
        )


# ======================================
# EXPORT EXCEL
# ======================================

async def export_codes(update:Update,context:ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    keyboard = [

        [InlineKeyboardButton("كل الأكواد",callback_data="exp_all")],
        [InlineKeyboardButton("الأكواد المتاحة",callback_data="exp_active")],
        [InlineKeyboardButton("الأكواد المستخدمة",callback_data="exp_used")]

    ]

    await query.edit_message_text(
        "اختر نوع الأكواد",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def generate_excel(update:Update,context:ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "exp_all":
        condition = ""

    elif data == "exp_active":
        condition = "WHERE is_active=TRUE"

    else:
        condition = "WHERE is_active=FALSE"

    with get_connection() as conn:

        df = pd.read_sql(f"SELECT name,code,is_active FROM code {condition}",conn)

    df["code"] = df["code"].apply(lambda c: cipher_suite.decrypt(c.encode()).decode())

    file = "codes.xlsx"
    df.to_excel(file,index=False)

    await query.message.reply_document(InputFile(file))


# ======================================
# MAIN
# ======================================

import asyncio

async def main():

    admin_app = ApplicationBuilder().token(ADMIN_TOKEN).build()
    user_app = ApplicationBuilder().token(USER_TOKEN).build()

    # Admin handlers
    admin_app.add_handler(CommandHandler("login", admin_login))
    admin_app.add_handler(CallbackQueryHandler(export_codes, pattern="export"))
    admin_app.add_handler(CallbackQueryHandler(generate_excel, pattern="exp_"))

    # User handlers
    user_app.add_handler(CommandHandler("start", user_start))
    user_app.add_handler(CommandHandler("login", user_login))
    user_app.add_handler(CommandHandler("menu", user_menu))
    user_app.add_handler(CallbackQueryHandler(user_callback))

    await admin_app.initialize()
    await user_app.initialize()

    await admin_app.start()
    await user_app.start()

    await admin_app.bot.initialize()
    await user_app.bot.initialize()

    print("Admin bot started")
    print("User bot started")

    await asyncio.gather(
        admin_app.updater.start_polling(),
        user_app.updater.start_polling()
    )

    await asyncio.Event().wait()


if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())








