import psycopg2
import hashlib
from config import DB_URL

def get_connection():
    safe_url = DB_URL
    if "sslmode=require" not in safe_url:
        safe_url += "?sslmode=require"
    return psycopg2.connect(safe_url)

def hash_id(tg_id: int) -> str:
    return hashlib.sha256(str(tg_id).encode()).hexdigest()

def get_role_by_id(tg_id: int):
    h_id = hash_id(tg_id)

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT role FROM users WHERE hashed_id = %s",
                (h_id,)
            )

            res = cur.fetchone()
            return res[0] if res else None
    except Exception:
        return None