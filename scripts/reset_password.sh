#!/bin/bash
# Reset DVD Ripper admin password

NEW_PASSWORD="${1:-admin123}"
CONTAINER="${CONTAINER_NAME:-dvd-archive}"

echo "Resetting admin password in container '$CONTAINER'..."

docker exec -it "$CONTAINER" python3 -c "
from app.database import get_session_context
from app.auth import get_password_hash
from sqlmodel import select
from app.database import User

NEW_PASSWORD = '$NEW_PASSWORD'

with get_session_context() as session:
    user = session.exec(select(User).where(User.username == 'admin')).first()
    if user:
        user.hashed_password = get_password_hash(NEW_PASSWORD)
        session.add(user)
        session.commit()
        print(f'✅ Password for \"admin\" has been reset to: {NEW_PASSWORD}')
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
