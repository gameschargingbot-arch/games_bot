from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters
from auth import start_auth
from admin_handlers import admin_menu_handler
from user_handlers import user_main_handler
from config import *

conv = ConversationHandler(

    entry_points=[CommandHandler("start", start_auth)],

    states={

        ADMIN_MAIN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)
        ],

        USER_MAIN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, user_main_handler)
        ],

    },

    fallbacks=[CommandHandler("start", start_auth)]

)