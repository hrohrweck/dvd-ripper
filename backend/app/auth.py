"""Authentication utilities."""
from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.database import User, get_session_context
from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password."""
    return pwd_context.hash(password)


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
