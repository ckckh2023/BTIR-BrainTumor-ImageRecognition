'''JWT 认证与密码哈希服务'''

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from core.settings import SETTINGS, UNSAFE_DEFAULT_JWT_SECRET

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
MINIMUM_JWT_SECRET_BYTES = 32
SUPPORTED_JWT_ALGORITHM = "HS256"


def validate_auth_configuration() -> None:
    '''在 API 启动前拒绝不安全或无法工作的 JWT 配置'''
    secret = SETTINGS.jwt_secret_key
    if not secret or secret == UNSAFE_DEFAULT_JWT_SECRET:
        raise RuntimeError(
            "必须通过 BTIR_JWT_SECRET_KEY 配置随机 JWT 密钥，不能使用空值或示例值"
        )
    if len(secret.encode("utf-8")) < MINIMUM_JWT_SECRET_BYTES:
        raise RuntimeError(
            f"BTIR_JWT_SECRET_KEY 至少需要 {MINIMUM_JWT_SECRET_BYTES} 字节"
        )
    if SETTINGS.jwt_algorithm != SUPPORTED_JWT_ALGORITHM:
        raise RuntimeError(
            f"BTIR_JWT_ALGORITHM 仅支持 {SUPPORTED_JWT_ALGORITHM}"
        )


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except (TypeError, ValueError):
        return False


def create_access_token(data: dict[str, object], expires_delta: timedelta | None = None) -> str:
    validate_auth_configuration()
    to_encode = data.copy()
    issued_at = datetime.now(timezone.utc)
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=SETTINGS.jwt_expiration_hours)
    )
    to_encode.update({"iat": issued_at, "exp": expire})
    return jwt.encode(to_encode, SETTINGS.jwt_secret_key, algorithm=SETTINGS.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, object] | None:
    validate_auth_configuration()
    try:
        payload = jwt.decode(token, SETTINGS.jwt_secret_key, algorithms=[SETTINGS.jwt_algorithm])
        return payload
    except JWTError:
        return None
