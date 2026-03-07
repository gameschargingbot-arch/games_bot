import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv
import os

load_dotenv()
NEON_CONNECTION_STRING = os.getenv("NEON_DB_URL")

def get_connection():
    return psycopg2.connect(NEON_CONNECTION_STRING)

# ==========================================
# USER MANAGEMENT
# ==========================================

def create_user(username, password, role="user"):
    # Note: In a real app, hash the password before saving!
    sql = "INSERT INTO users (username, pass, role) VALUES (%s, %s, %s)"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (username, password, role))
            conn.commit()

def change_password(username, new_password):
    sql = "UPDATE users SET pass = %s WHERE username = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (new_password, username))
            conn.commit()

def delete_user(username):
    sql = "DELETE FROM users WHERE username = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (username,))
            conn.commit()

# ==========================================
# CODE MANAGEMENT & TIME FILTERS
# ==========================================

def get_all_codes():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM code")
            return cur.fetchall()

def get_active_codes():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM code WHERE is_active = TRUE")
            return cur.fetchall()

def get_unactive_codes():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM code WHERE is_active = FALSE")
            return cur.fetchall()

def get_used_today():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM code WHERE used_at >= CURRENT_DATE")
            return cur.fetchall()

def get_used_last_week():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM code WHERE used_at >= CURRENT_DATE - INTERVAL '1 week'")
            return cur.fetchall()

def get_used_last_month():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM code WHERE used_at >= CURRENT_DATE - INTERVAL '1 month'")
            return cur.fetchall()

def get_used_last_year():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM code WHERE used_at >= CURRENT_DATE - INTERVAL '1 year'")
            return cur.fetchall()

# ==========================================
# CONCURRENT-SAFE CODE RETRIEVAL
# ==========================================

def get_code():
    """
    Safely grabs 1 active code, marks it as inactive, sets the timestamp, 
    and returns it. Uses row-level locking to prevent duplicates.
    """
    sql = """
        UPDATE code 
        SET is_active = FALSE, used_at = NOW() 
        WHERE id = (
            SELECT id FROM code 
            WHERE is_active = TRUE 
            LIMIT 1 
            FOR UPDATE SKIP LOCKED
        ) 
        RETURNING code;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            result = cur.fetchone()
            conn.commit()
            
            # Return the code if we found one, otherwise None
            return result[0] if result else None

# ==========================================
# BULK INSERT CODES
# ==========================================

def add_codes(name_group, codes_string):
    """
    Takes a string of codes separated by newlines and inserts them all at once.
    """
    # Split the string by newlines and remove any empty lines/spaces
    raw_codes = codes_string.strip().split('\n')
    clean_codes = [code.strip() for code in raw_codes if code.strip()]
    
    # Prepare the data as a list of tuples: (name, code, is_active)
    data_to_insert = [(name_group, code, True) for code in clean_codes]
    
    sql = "INSERT INTO code (name, code, is_active) VALUES (%s, %s, %s)"
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # execute_batch is much faster than running a loop of inserts
            execute_batch(cur, sql, data_to_insert)
            conn.commit()
            print(f"Successfully added {len(clean_codes)} codes to the database.")