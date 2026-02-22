#!/bin/bash
# Reset DVD Ripper admin password - Fixed version

NEW_PASSWORD="${1:-admin123}"
CONTAINER="${CONTAINER_NAME:-dvd-archive}"

echo "Resetting admin password in container '$CONTAINER'..."

docker exec -it "$CONTAINER" python3 -c "
import sys
sys.path.insert(0, '/app')

from app.database import get_session_context, User, engine
from sqlmodel import select, Session
import bcrypt

NEW_PASSWORD = '$NEW_PASSWORD'

# Truncate to 72 bytes for bcrypt
if isinstance(NEW_PASSWORD, str):
    NEW_PASSWORD = NEW_PASSWORD.encode('utf-8')
NEW_PASSWORD = NEW_PASSWORD[:72]

# Hash directly with bcrypt
hashed = bcrypt.hashpw(NEW_PASSWORD, bcrypt.gensalt())
hashed_str = hashed.decode('utf-8')

with get_session_context() as session:
    user = session.exec(select(User).where(User.username == 'admin')).first()
    if user:
        user.hashed_password = hashed_str
        session.add(user)
        session.commit()
        print(f'✅ Password for \"admin\" has been reset to: $1')
    else:
        # Check if any users exist
        all_users = session.exec(select(User)).all()
        if all_users:
            print('Available users:')
            for u in all_users:
                print(f'  - {u.username}')
        else:
            print('⚠️  No users found in database. System is in first-run mode.')
            print('   Access the web UI and complete the setup wizard.')
"
