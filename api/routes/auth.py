'''用户注册与登录接口'''

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError

from contracts.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UserInfoResponse,
)
from api.auth import get_current_user, get_user_repository
from core.user_records import UserRecord, normalize_username
from core.settings import SETTINGS
from repositories.user_repository import UsernameAlreadyExistsError
from services.auth_service import create_access_token, hash_password, verify_password
from services.audit_service import append_audit_event
from services.auth_rate_limit import (
    AuthRateLimitExceededError,
    clear_auth_rate_limit,
    consume_auth_rate_limit,
)

router = APIRouter(prefix="/auth", tags=["认证"])


def _client_identity(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _consume_rate_limit(
    scope: str,
    identity: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    try:
        consume_auth_rate_limit(
            scope,
            identity,
            limit=limit,
            window_seconds=window_seconds,
        )
    except AuthRateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="认证尝试过于频繁，请稍后再试",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证限流服务暂不可用",
        ) from exc


def _clear_login_user_limit(username: str) -> None:
    try:
        clear_auth_rate_limit("login-user", normalize_username(username))
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证限流服务暂不可用",
        ) from exc


def _append_auth_audit_event(
    operation: str,
    http_request: Request,
    *,
    actor_user_id: str | None = None,
    target_user_id: str | None = None,
    outcome: str | None = None,
) -> None:
    append_audit_event(
        operation=operation,
        timestamp=datetime.now(timezone.utc),
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        outcome=outcome,
        source_ip=_client_identity(http_request),
        audit_dir=SETTINGS.task_archive_dir,
    )


def _build_auth_response(user: UserRecord) -> AuthResponse:
    token = create_access_token(
        data={"sub": user.user_id, "ver": user.token_version}
    )
    return AuthResponse(
        access_token=token,
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, http_request: Request) -> AuthResponse:
    if not SETTINGS.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户注册当前已关闭，请联系管理员",
        )
    _consume_rate_limit(
        "register-ip",
        _client_identity(http_request),
        limit=SETTINGS.auth_registration_ip_attempts,
        window_seconds=SETTINGS.auth_registration_window_seconds,
    )
    user_repo = get_user_repository()
    hashed = hash_password(request.password)
    try:
        user = user_repo.create_user(
            username=request.username,
            hashed_password=hashed,
        )
    except UsernameAlreadyExistsError as exc:
        _append_auth_audit_event(
            "user_registration_failed",
            http_request,
            outcome="username_conflict",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    _append_auth_audit_event(
        "user_registered",
        http_request,
        actor_user_id=user.user_id,
        target_user_id=user.user_id,
        outcome="success",
    )
    return _build_auth_response(user)


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest, http_request: Request) -> AuthResponse:
    username_identity = normalize_username(request.username)
    _consume_rate_limit(
        "login-user",
        username_identity,
        limit=SETTINGS.auth_login_user_attempts,
        window_seconds=SETTINGS.auth_login_window_seconds,
    )
    _consume_rate_limit(
        "login-ip",
        _client_identity(http_request),
        limit=SETTINGS.auth_login_ip_attempts,
        window_seconds=SETTINGS.auth_login_window_seconds,
    )
    user_repo = get_user_repository()
    user = user_repo.get_by_username(request.username)
    if user is None:
        # 对不存在的用户名也执行一次昂贵哈希，减小通过响应耗时枚举用户的差异。
        hash_password(request.password)
        password_valid = False
    else:
        password_valid = verify_password(request.password, user.hashed_password)
    if not password_valid:
        _append_auth_audit_event(
            "auth_login_failed",
            http_request,
            target_user_id=user.user_id if user is not None else None,
            outcome="invalid_credentials",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        _append_auth_audit_event(
            "auth_login_failed",
            http_request,
            target_user_id=user.user_id,
            outcome="user_disabled",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

    _clear_login_user_limit(request.username)
    _append_auth_audit_event(
        "auth_login_succeeded",
        http_request,
        actor_user_id=user.user_id,
        target_user_id=user.user_id,
        outcome="success",
    )
    return _build_auth_response(user)


@router.get("/me", response_model=UserInfoResponse)
def get_current_user_info(current_user: UserRecord = Depends(get_current_user)) -> UserInfoResponse:
    return UserInfoResponse(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role,
        is_active=current_user.is_active,
        must_change_password=current_user.must_change_password,
        created_at=current_user.created_at.isoformat(),
    )


@router.post("/change-password", response_model=AuthResponse)
def change_password(
    request: ChangePasswordRequest,
    http_request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> AuthResponse:
    if not verify_password(request.current_password, current_user.hashed_password):
        _append_auth_audit_event(
            "password_change_failed",
            http_request,
            actor_user_id=current_user.user_id,
            target_user_id=current_user.user_id,
            outcome="invalid_current_password",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码错误",
        )
    if request.current_password == request.new_password:
        _append_auth_audit_event(
            "password_change_failed",
            http_request,
            actor_user_id=current_user.user_id,
            target_user_id=current_user.user_id,
            outcome="password_reused",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与当前密码相同",
        )
    user_repo = get_user_repository()
    updated = user_repo.update_password(
        current_user.username,
        hash_password(request.new_password),
        must_change_password=False,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    _append_auth_audit_event(
        "password_changed",
        http_request,
        actor_user_id=updated.user_id,
        target_user_id=updated.user_id,
        outcome="success",
    )
    return _build_auth_response(updated)
