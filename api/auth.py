'''FastAPI 认证依赖项'''

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from repositories.user_repository import SqliteUserRepository
from repositories.sqlite_task_repository import SqliteTaskRepository
from repositories.task_repository import task_repository
from services.auth_service import decode_access_token
from core.user_records import UserRecord

_security = HTTPBearer(auto_error=False)


def get_user_repository() -> SqliteUserRepository:
    if not isinstance(task_repository, SqliteTaskRepository):
        raise RuntimeError("用户仓储需要 SqliteTaskRepository")
    return SqliteUserRepository(task_repository)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> UserRecord:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌缺少用户标识",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_repo = get_user_repository()
    user = user_repo.get_by_user_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )
    return user
