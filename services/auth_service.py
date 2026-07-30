'''JWT 认证与密码哈希服务'''

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from core.settings import SETTINGS

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict[str, object], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=SETTINGS.jwt_expiration_hours)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SETTINGS.jwt_secret_key, algorithm=SETTINGS.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, object] | None:
    try:
        payload = jwt.decode(token, SETTINGS.jwt_secret_key, algorithms=[SETTINGS.jwt_algorithm])
        return payload
    except JWTError:
        return None
