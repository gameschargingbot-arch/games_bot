import os
import time
import psycopg2
from urllib.parse import urlparse
from dotenv import load_dotenv
import sys

sys.stdout.reconfigure(encoding='utf-8')

# 1. Load the URL from your .env file
load_dotenv()
DB_URL = os.getenv("NEON_DB_URL")

def test_connection():
    print("🔍 Starting Database Connection Test...\n")

    if not DB_URL:
        print("❌ ERROR: NEON_DB_URL is completely missing from your .env file!")
        return

    # 2. Print a safe version of the URL to ensure it's loaded correctly
    try:
        parsed = urlparse(DB_URL)
        safe_url = f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}{parsed.path}?{parsed.query}"
        print(f"🔗 Target: {safe_url}\n")
    except Exception:
        print("⚠️ Could not parse the URL. It might be formatted incorrectly.")

    # 3. Enforce SSL (Neon strictly rejects connections without it)
    final_url = DB_URL
  

    # 4. Attempt connection with retry logic
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            print(f"⏳ Attempt {attempt}/{retries} - Knocking on Neon's door...")
            
            # connect_timeout prevents it from hanging forever
            conn = psycopg2.connect(final_url, connect_timeout=10)
            
            print("✅ CONNECTION SUCCESSFUL!")
            
            # Run a tiny query to prove we have access
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            print(f"🎉 Database Version: {version}\n")
            
            cur.close()
            conn.close()
            print("🔌 Test complete. Everything is working perfectly.")
            return

        except psycopg2.OperationalError as e:
            print(f"❌ Attempt {attempt} Failed:")
            print(f"   {str(e).strip()}")
            
            if attempt < retries:
                print("💤 Waiting 3 seconds (in case Neon is waking up)...\n")
                time.sleep(3)
            else:
                print("\n🛑 ALL ATTEMPTS FAILED.")
                print("Check if your password is correct, and ensure you copied the whole string.")

if __name__ == "__main__":
    test_connection()