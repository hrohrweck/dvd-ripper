#!/usr/bin/env python3
"""
Direct password reset for DVD Ripper.
Run from host or inside container.
"""

import sqlite3
import bcrypt
import sys
import os

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "./storage/data/dvdrip.db"
NEW_PASSWORD = sys.argv[2] if len(sys.argv) > 2 else "admin123"

def main():
    # If running in container, use container path
    if os.path.exists("/app/data/dvdrip.db"):
        db_path = "/app/data/dvdrip.db"
    else:
        db_path = DB_PATH
        # Try to find the database in docker volume
        if not os.path.exists(db_path):
            db_path = "./config/data/dvdrip.db"
        if not os.path.exists(db_path):
            # Use docker to copy the db out
            print("Database not found locally, trying to access via docker...")
            os.system("docker exec dvd-archive cat /app/data/dvdrip.db > /tmp/dvdrip.db 2>/dev/null")
            db_path = "/tmp/dvdrip.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        print("Make sure the container is running and the database exists.")
        sys.exit(1)
    
    print(f"Using database: {db_path}")
    
    # Hash the password
    password_bytes = NEW_PASSWORD.encode('utf-8')[:72]
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    hashed_str = hashed.decode('utf-8')
    
    print(f"Generated hash: {hashed_str}")
    
    # Connect and update
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if users table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone():
        print("❌ 'users' table not found in database")
        conn.close()
        sys.exit(1)
    
    # List current users
    cursor.execute("SELECT username FROM users")
    users = cursor.fetchall()
    print(f"\nCurrent users: {[u[0] for u in users]}")
    
    # Update password
    cursor.execute("UPDATE users SET hashed_password = ? WHERE username = 'admin'", (hashed_str,))
    
    if cursor.rowcount > 0:
        conn.commit()
        print(f"✅ Password for 'admin' has been reset to: {NEW_PASSWORD}")
    else:
        print("⚠️  No 'admin' user found. Creating one...")
        from datetime import datetime
        cursor.execute(
            "INSERT INTO users (username, hashed_password, is_active, created_at) VALUES (?, ?, ?, ?)",
            ("admin", hashed_str, 1, datetime.utcnow().isoformat())
        )
        conn.commit()
        print(f"✅ Created new 'admin' user with password: {NEW_PASSWORD}")
    
    conn.close()
    
    # If we used a temp file, copy it back to container
    if db_path == "/tmp/dvdrip.db":
        print("\nCopying updated database back to container...")
        os.system("docker cp /tmp/dvdrip.db dvd-archive:/app/data/dvdrip.db")
        os.system("docker exec dvd-archive chmod 666 /app/data/dvdrip.db")
        print("✅ Database updated in container")

if __name__ == "__main__":
    main()
