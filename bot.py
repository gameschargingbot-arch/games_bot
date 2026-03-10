import os
import asyncio
import psycopg2
import hashlib
import pandas as pd
import sys
from datetime import datetime
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    ContextTypes, ConversationHandler, filters
)

# Fix for potential encoding issues in some environments
if sys.version_info >= (3, 7):
    sys.stdout.reconfigure(encoding='utf-8')

# ======================================
# CONFIG & ENV
# ======================================
load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
USER_TOKEN = os.getenv("USER_BOT_TOKEN")
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode()

cipher_suite = Fernet(FERNET_KEY)

# Conversation States
(ADMIN_MAIN, ADD_CHOICE, ADD_CAT, ADD_SUB, ADD_CODES,
 USER_MGMT_MENU, ADD_USER_ID, REMOVE_USER_ID,
 USER_MAIN, USER_SELECT_CAT, USER_SELECT_SUB) = range(11)

# ======================================
# CORE HELPERS
# ======================================
def get_connection():
    """Thread-safe database connection for Neon/Postgres."""
    safe_url = DB_URL
    if "sslmode=require" not in safe_url:
        safe_url += "?sslmode=require"
    return psycopg2.connect(safe_url)


def hash_id(tg_id: int) -> str:
    """Creates a deterministic, non-reversible hash of the Telegram ID."""
    return hashlib.sha256(str(tg_id).encode()).hexdigest()

def get_role_by_id(tg_id: int):
    h_id = hash_id(tg_id)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE hashed_id = %s", (h_id,))
            res = cur.fetchone()
            return res[0] if res else None
    except Exception as e:
        print(f"DB Error: {e}")
        return None

# ======================================
# KEYBOARDS
# ======================================
def kb_admin_main():
    return ReplyKeyboardMarkup([
        ['📊 الاحصائيات', '➕ اضافة اكواد'], 
        ['👤 إدارة المستخدمين', '📥 تصدير Excel']
    ], resize_keyboard=True)

def kb_user_main():
    return ReplyKeyboardMarkup([['📂 عرض الأقسام']], resize_keyboard=True)

def kb_user_mgmt():
    return ReplyKeyboardMarkup([
        ['➕ إضافة مستخدم ID', '❌ حذف مستخدم'], 
        ['⬅️ عودة']
    ], resize_keyboard=True)

# ======================================
# SHARED AUTH & START
# ======================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    role = get_role_by_id(tg_id)

    if role == "admin":
        await update.message.reply_text(
            f"👑 أهلاً بك أيها المسؤول\nالمعرف الخاص بك: `{tg_id}`", 
            reply_markup=kb_admin_main(),
            parse_mode="Markdown"
        )
        return ADMIN_MAIN
    elif role == "user":
        await update.message.reply_text(
            "👋 أهلاً بك في متجر الأكواد الرقمي.", 
            reply_markup=kb_user_main()
        )
        return USER_MAIN
    else:
        await update.message.reply_text(
            f"❌ الوصول مرفوض.\nرقم الـ ID الخاص بك غير مسجل: `{tg_id}`\nتواصل مع الإدارة للتفعيل.", 
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

# ======================================
# ADMIN: LOGIC & MANAGEMENT
# ======================================
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 الاحصائيات':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM code WHERE is_active=TRUE")
            active = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM code WHERE is_active=FALSE")
            used = cur.fetchone()[0]
            await update.message.reply_text(f"📊 **تقرير النظام**\n\n✅ الأكواد المتوفرة: {active}\n❌ الأكواد المباعة: {used}", parse_mode="Markdown")
    
    elif text == '➕ اضافة اكواد':
        kb = [['بدون قسم فرعي', 'مع قسم فرعي'], ['⬅️ عودة']]
        await update.message.reply_text("كيف تود تصنيف الأكواد الجديدة؟", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return ADD_CHOICE

    elif text == '👤 إدارة المستخدمين':
        await update.message.reply_text("إدارة صلاحيات الوصول بالـ ID:", reply_markup=kb_user_mgmt())
        return USER_MGMT_MENU

    elif text == '📥 تصدير Excel':
        await update.message.reply_text("⌛ جاري توليد ملف البيانات...")
        with get_connection() as conn:
            df = pd.read_sql("SELECT name as 'القسم', code as 'الكود', is_active as 'متاح' FROM code", conn)
        df['الكود'] = df['الكود'].apply(lambda x: cipher_suite.decrypt(x.encode()).decode() if x else "N/A")
        file_name = f"export_{datetime.now().strftime('%Y%m%d')}.xlsx"
        df.to_excel(file_name, index=False)
        await update.message.reply_document(document=open(file_name, "rb"), caption="سجل الأكواد الكامل")
    
    return ADMIN_MAIN

async def save_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_codes = update.message.text.split('\n')
    main_cat = context.user_data['main_cat']
    sub_cat = context.user_data.get('sub_cat')
    
    with get_connection() as conn, conn.cursor() as cur:
        # Parent creation/lookup
        cur.execute("""
            INSERT INTO code (name, is_active) 
            SELECT %s, TRUE WHERE NOT EXISTS 
            (SELECT 1 FROM code WHERE name=%s AND parent_id IS NULL) 
            RETURNING id
        """, (main_cat, main_cat))
        res = cur.fetchone()
        
        if not res:
            cur.execute("SELECT id FROM code WHERE name=%s AND parent_id IS NULL", (main_cat,))
            parent_id = cur.fetchone()[0]
        else:
            parent_id = res[0]

        target_name = sub_cat if sub_cat else main_cat
        final_parent = parent_id if sub_cat else None

        for c in raw_codes:
            if c.strip():
                enc = cipher_suite.encrypt(c.strip().encode()).decode()
                cur.execute("INSERT INTO code (name, code, is_active, parent_id) VALUES (%s, %s, TRUE, %s)", 
                            (target_name, enc, final_parent))
        conn.commit()
    
    await update.message.reply_text(f"✅ تم بنجاح إضافة {len(raw_codes)} كود إلى قسم {target_name}", reply_markup=kb_admin_main())
    return ADMIN_MAIN

# ======================================
# USER: BROWSING & REDEMPTION
# ======================================
async def user_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📂 عرض الأقسام':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT name FROM code WHERE parent_id IS NULL")
            cats = [[r[0]] for r in cur.fetchall()]
        
        if not cats:
            await update.message.reply_text("📭 المتجر فارغ حالياً.")
            return USER_MAIN
        
        cats.append(['⬅️ عودة'])
        await update.message.reply_text("اختر القسم المطلوب:", reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True))
        return USER_SELECT_CAT
    return USER_MAIN

async def handle_cat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat_name = update.message.text
    if cat_name == '⬅️ عودة':
        await update.message.reply_text("القائمة الرئيسية", reply_markup=kb_user_main())
        return USER_MAIN

    with get_connection() as conn, conn.cursor() as cur:
        # Check if there are sub-categories (children)
        cur.execute("""
            SELECT DISTINCT name FROM code 
            WHERE parent_id = (SELECT id FROM code WHERE name=%s AND parent_id IS NULL)
        """, (cat_name,))
        subs = [[r[0]] for r in cur.fetchall()]
        
        if subs:
            subs.append(['⬅️ عودة'])
            await update.message.reply_text(f"📂 قسم {cat_name}: اختر النوع", reply_markup=ReplyKeyboardMarkup(subs, resize_keyboard=True))
            return USER_SELECT_SUB
        else:
            # Direct code pull for top-level categories
            return await redeem_code_logic(update, cat_name)

async def redeem_code_logic(update: Update, target_name):
    """Securely pulls one code using SQL row locking."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE code SET is_active = FALSE, used_at = NOW() 
            WHERE id = (
                SELECT id FROM code 
                WHERE name=%s AND is_active=TRUE 
                LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            RETURNING code
        """, (target_name,))
        result = cur.fetchone()
        conn.commit()

    if result:
        decrypted = cipher_suite.decrypt(result[0].encode()).decode()
        await update.message.reply_text(
            f"✅ كود {target_name} الخاص بك جاهز:\n\n`{decrypted}`", 
            parse_mode="Markdown", 
            reply_markup=kb_user_main()
        )
    else:
        await update.message.reply_text(f"❌ نعتذر، نفدت الكمية في قسم {target_name}.", reply_markup=kb_user_main())
    return USER_MAIN

# ======================================
# MAIN ASYNC RUNNER (DUAL LISTEN)
# ======================================

async def main():
    # Application instances
    admin_app = ApplicationBuilder().token(ADMIN_TOKEN).build()
    user_app = ApplicationBuilder().token(USER_TOKEN).build()

    # --- Admin Conversation ---
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ADMIN_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (
                c.user_data.update({'mode': 'sub' if 'مع' in u.message.text else 'single'}),
                u.message.reply_text("أدخل اسم القسم الرئيسي (مثلاً Gaming):", reply_markup=ReplyKeyboardRemove())
            )[-1] if 'عودة' not in u.message.text else ADMIN_MAIN)],
            ADD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (
                c.user_data.update({'main_cat': u.message.text}),
                u.message.reply_text("أدخل القسم الفرعي (مثلاً PUBG):") if c.user_data['mode']=='sub' else u.message.reply_text("أرسل الأكواد الآن:")
            )[-1] or (ADD_SUB if c.user_data['mode']=='sub' else ADD_CODES))],
            ADD_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (
                c.user_data.update({'sub_cat': u.message.text}),
                u.message.reply_text("أرسل قائمة الأكواد:")
            )[-1] or ADD_CODES)],
            ADD_CODES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_codes)],
            USER_MGMT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (
                (u.message.reply_text("أدخل رقم الـ Telegram ID للمستخدم:") or (ADD_USER_ID if 'إضافة' in u.message.text else REMOVE_USER_ID))
                if 'عودة' not in u.message.text else (u.message.reply_text("الرئيسية", reply_markup=kb_admin_main()) or ADMIN_MAIN)
            ))],
            ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (
                get_connection().cursor().execute("INSERT INTO users (hashed_id, role) VALUES (%s, 'user')",(hash_id(u.message.text),)),
                u.message.reply_text("✅ تمت الإضافة بنجاح.", reply_markup=kb_user_mgmt())
            )[-1] or USER_MGMT_MENU)],
            REMOVE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (
                get_connection().cursor().execute("DELETE FROM users WHERE hashed_id=%s AND role='user'",(hash_id(u.message.text),)),
                u.message.reply_text("🗑️ تم الحذف.", reply_markup=kb_user_mgmt())
            )[-1] or USER_MGMT_MENU)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # --- User Conversation ---
    user_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            USER_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_main_menu)],
            USER_SELECT_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cat_selection)],
            USER_SELECT_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: redeem_code_logic(u, u.message.text))],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    admin_app.add_handler(admin_conv)
    user_app.add_handler(user_conv)

    await admin_app.initialize()
    await user_app.initialize()
    await admin_app.start()
    await user_app.start()

    print("🚀 All systems online. Listening on both Admin and User ports.")
    await asyncio.gather(admin_app.updater.start_polling(), user_app.updater.start_polling())
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
