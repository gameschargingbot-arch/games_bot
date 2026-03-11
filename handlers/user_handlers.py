from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from db import get_connection
from keyboards import kb_user_main
from config import *
from config import cipher_suite


async def user_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.text == '📂 عرض الأقسام':

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT name FROM code WHERE parent_id IS NULL")
            cats = [[r[0]] for r in cur.fetchall()]

        if not cats:
            return USER_MAIN

        cats.append(['⬅️ عودة'])

        await update.message.reply_text(
            "اختر القسم:",
            reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True)
        )

        return USER_SELECT_CAT

    return USER_MAIN


async def user_cat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):

    cat_name = update.message.text

    if cat_name == '⬅️ عودة':

        await update.message.reply_text(
            "الرئيسية",
            reply_markup=kb_user_main()
        )

        return USER_MAIN

    with get_connection() as conn, conn.cursor() as cur:

        cur.execute(
            "SELECT DISTINCT name FROM code WHERE parent_id=(SELECT id FROM code WHERE name=%s AND parent_id IS NULL LIMIT 1)",
            (cat_name,)
        )

        subs = [[r[0]] for r in cur.fetchall()]

        if subs:

            subs.append(['⬅️ عودة'])

            await update.message.reply_text(
                f"قسم {cat_name}:",
                reply_markup=ReplyKeyboardMarkup(subs, resize_keyboard=True)
            )

            return USER_SELECT_SUB

        return await redeem_code(update, cat_name)


async def redeem_code(update, target):

    with get_connection() as conn, conn.cursor() as cur:

        cur.execute(
            "UPDATE code SET is_active=FALSE, used_at=NOW() WHERE id=(SELECT id FROM code WHERE name=%s AND is_active=TRUE LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING code",
            (target,)
        )

        res = cur.fetchone()

        conn.commit()

    if res:

        code = cipher_suite.decrypt(res[0].encode()).decode()

        await update.message.reply_text(
            f"✅ كود {target}:\n`{code}`",
            parse_mode="Markdown",
            reply_markup=kb_user_main()
        )

    else:

        await update.message.reply_text(
            "❌ نفدت الكمية.",
            reply_markup=kb_user_main()
        )

    return USER_MAIN