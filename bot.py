from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from conversation import conv
from keep_alive import keep_alive


def main():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(conv)

    print("🚀 Bot running")

    app.run_polling()


if __name__ == "__main__":

    keep_alive()

    main()