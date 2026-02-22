"""Authentication utilities."""
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.database import User, get_session_context
from app.config import get_settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash using bcrypt directly.
    
    bcrypt has a 72 byte limit, so we truncate longer passwords.
    """
    # bcrypt has a 72 byte limit
    plain_password = plain_password[:72]
    
    # Ensure we're working with bytes
    if isinstance(plain_password, str):
        plain_password = plain_password.encode('utf-8')
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode('utf-8')
    
    return bcrypt.checkpw(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password using bcrypt directly.
    
    bcrypt has a 72 byte limit, so we truncate longer passwords.
    """
    # bcrypt has a 72 byte limit
    password = password[:72]
    
    # Ensure we're working with bytes
    if isinstance(password, str):
        password = password.encode('utf-8')
    
    return bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')


def get_user_by_username(session: Session, username: str) -> Optional[User]:
    """Get user by username."""
    statement = select(User).where(User.username == username)
    return session.exec(statement).first()


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    """Authenticate user."""
    user = get_user_by_username(session, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    settings = get_settings()
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return payload
    except JWTError:
        return None


def create_default_admin(password: str) -> User:
    """Create default admin user."""
    with get_session_context() as session:
        # Check if admin already exists
        existing = get_user_by_username(session, "admin")
        if existing:
            return existing
        
        user = User(
            username="admin",
            hashed_password=get_password_hash(password),
            is_active=True
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def is_first_run() -> bool:
    """Check if this is the first run (no users exist)."""
    with get_session_context() as session:
        statement = select(User)
        result = session.exec(statement).first()
        return result is None
