from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from jose import jwt
from fastapi.concurrency import run_in_threadpool
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


async def async_verify_password(plain_password: str, hashed_password: str) -> bool:
    return await run_in_threadpool(verify_password, plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


async def async_get_password_hash(password: str) -> str:
    return await run_in_threadpool(get_password_hash, password)


def create_access_token(
    subject: str, 
    temple_id: str | None = None, 
    role: str = "STAFF", 
    username: str = "",
    security_version: int | None = None,
    user_status: str | None = None,
    force_password_change: bool = False
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "iat": now,
        "sub": str(subject), 
        "role": role, 
        "username": username,
        "user_status": user_status,
        "security_version": security_version,
        "force_password_change": force_password_change
    }
    if temple_id:
        to_encode["temple_id"] = str(temple_id)
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.ALGORITHM)

