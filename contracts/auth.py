'''认证相关的请求和响应数据模型'''

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, field_validator

from core.user_records import UserRole


USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
USERNAME_PATTERN = re.compile(r"^[\u4e00-\u9fffa-zA-Z0-9_-]+$")
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 72


def _validate_password(value: str) -> str:
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        raise ValueError("密码长度应为 6 至 72 个字符")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("密码的 UTF-8 编码不能超过 72 字节")
    return value


class CredentialsRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_MIN_LENGTH <= len(value) <= USERNAME_MAX_LENGTH:
            raise ValueError("用户名长度应为 3 至 32 个字符")
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("用户名仅支持中文、字母、数字、下划线和连字符")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class RegisterRequest(CredentialsRequest):
    pass


class LoginRequest(CredentialsRequest):
    pass


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("current_password", "new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: UserRole
    must_change_password: bool


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    created_at: str


class AdminUserSummaryResponse(BaseModel):
    user_id: str
    username: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class AdminUserListResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    items: list[AdminUserSummaryResponse]
    total: int
    limit: int
    offset: int


class AdminPasswordResetRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class AdminPasswordResetResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    user_id: str
    username: str
    token_revoked: bool = True
    must_change_password: bool = True


class AdminAuditEventResponse(BaseModel):
    operation: str
    timestamp: datetime
    actor_user_id: str | None = None
    target_user_id: str | None = None
    task_id: str | None = None
    outcome: str | None = None
    source_ip: str | None = None


class AdminAuditListResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    items: list[AdminAuditEventResponse]
    total: int
    limit: int
    offset: int
    invalid_lines: int = 0
