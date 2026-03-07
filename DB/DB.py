import psycopg2
from psycopg2 import Error
from dotenv import load_dotenv
import os
# Get this string from your Neon.tech dashboard
# It will look like: postgresql://user:password@ep-cool-name.neon.tech/dbname?sslmode=require

load_dotenv()

NEON_CONNECTION_STRING = os.getenv("NEON_DB_URL")

def create_tables():
    try:
        # 1. Connect to the Neon database
        print("Connecting to Neon database...")
        connection = psycopg2.connect(NEON_CONNECTION_STRING)
        cursor = connection.cursor()

        # 2. SQL to create the 'users' table
        # We use SERIAL for auto-incrementing IDs and UNIQUE for usernames
        create_users_table_query = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            pass VARCHAR(255) NOT NULL,
            role VARCHAR(20) DEFAULT 'user'
        );
        """

        # 3. SQL to create the 'code' table
        create_code_table_query = """
        CREATE TABLE IF NOT EXISTS code (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            code VARCHAR(100) NOT NULL,
            status BOOLEAN DEFAULT TRUE,
            used_at TIMESTAMP
        );
        """

        # 4. Execute the SQL commands
        cursor.execute(create_users_table_query)
        cursor.execute(create_code_table_query)

        # 5. Commit (save) the changes to the database
        connection.commit()
        print("✅ Tables 'users' and 'code' created successfully!")

    except Error as e:
        print(f"❌ Error while connecting to PostgreSQL: {e}")
        
    finally:
        # 6. Always close the connection when you're done
        if connection:
            cursor.close()
            connection.close()
            print("Database connection is closed.")

if __name__ == "__main__":
    create_tables()