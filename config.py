import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

BOT_TOKEN = os.getenv("USER_BOT_TOKEN")
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode()

cipher_suite = Fernet(FERNET_KEY)

(
ADMIN_MAIN, ADD_CHOICE, ADD_CAT, ADD_SUB, ADD_CODES,
USER_MGMT_MENU, ADD_USER_ID, REMOVE_USER_ID,
USER_MAIN, USER_SELECT_CAT, USER_SELECT_SUB,
ADMIN_STATS_CAT, ADMIN_STATS_SUB
) = range(13)