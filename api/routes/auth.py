'''用户注册与登录接口'''

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from contracts.auth import AuthResponse, LoginRequest, RegisterRequest, UserInfoResponse
from api.auth import get_current_user, get_user_repository
from core.user_records import UserRecord
from core.settings import SETTINGS
from repositories.user_repository import UsernameAlreadyExistsError
from services.auth_service import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest) -> AuthResponse:
    if not SETTINGS.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户注册当前已关闭，请联系管理员",
        )
    user_repo = get_user_repository()
    hashed = hash_password(request.password)
    try:
        user = user_repo.create_user(
            username=request.username,
            hashed_password=hashed,
        )
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    token = create_access_token(data={"sub": user.user_id})
    return AuthResponse(
        access_token=token,
        user_id=user.user_id,
        username=user.username,
    )


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest) -> AuthResponse:
    user_repo = get_user_repository()
    user = user_repo.get_by_username(request.username)
    if user is None:
        # 对不存在的用户名也执行一次昂贵哈希，减小通过响应耗时枚举用户的差异。
        hash_password(request.password)
        password_valid = False
    else:
        password_valid = verify_password(request.password, user.hashed_password)
    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

    token = create_access_token(data={"sub": user.user_id})
    return AuthResponse(
        access_token=token,
        user_id=user.user_id,
        username=user.username,
    )


@router.get("/me", response_model=UserInfoResponse)
def get_current_user_info(current_user: UserRecord = Depends(get_current_user)) -> UserInfoResponse:
    return UserInfoResponse(
        user_id=current_user.user_id,
        username=current_user.username,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat(),
    )
