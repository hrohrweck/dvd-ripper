#!/bin/bash
# Reset DVD Ripper admin password - SQL approach (bypasses bcrypt issues)

NEW_PASSWORD="${1:-admin123}"
CONTAINER="${CONTAINER_NAME:-dvd-archive}"

echo "Resetting admin password using SQL approach..."

# Generate bcrypt hash using openssl or python3 on host
# bcrypt hash for 'admin123' = \$2b\$12\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I8O
echo "Generating password hash..."

HASH=$(python3 -c "
import bcrypt
password = '$NEW_PASSWORD'.encode('utf-8')[:72]
hashed = bcrypt.hashpw(password, bcrypt.gensalt())
print(hashed.decode('utf-8').replace('\$', '\$\$'))
" 2>/dev/null || echo "")

if [ -z "$HASH" ]; then
    echo "Python bcrypt not available on host, trying container..."
    HASH=$(docker exec "$CONTAINER" python3 -c "
import bcrypt
password = '$NEW_PASSWORD'.encode('utf-8')[:72]
hashed = bcrypt.hashpw(password, bcrypt.gensalt())
print(hashed.decode('utf-8'))
" 2>/dev/null)
fi

if [ -z "$HASH" ]; then
    echo "❌ Could not generate hash. Using pre-computed hash for 'admin123'..."
    # Pre-computed bcrypt hash for 'admin123'
    HASH='\$2b\$12\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I8O'
    NEW_PASSWORD='admin123'
fi

echo "Updating database..."

docker exec "$CONTAINER" sqlite3 /app/data/dvdrip.db << EOF
UPDATE users SET hashed_password = '$HASH' WHERE username = 'admin';
SELECT 'Password updated for user: ' || username FROM users WHERE username = 'admin';
EOF

if [ $? -eq 0 ]; then
    echo "✅ Password for 'admin' has been reset to: $NEW_PASSWORD"
else
    echo "❌ Failed to update password"
fi
