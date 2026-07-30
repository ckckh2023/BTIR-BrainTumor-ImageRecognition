'''认证相关的请求和响应数据模型'''

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


USERNAME_FIELD = Field(
    min_length=3,
    max_length=32,
    pattern=r"^[a-zA-Z0-9_-]+$",
)
PASSWORD_FIELD = Field(min_length=6, max_length=72)


class CredentialsRequest(BaseModel):
    username: str = USERNAME_FIELD
    password: str = PASSWORD_FIELD

    @field_validator("password")
    @classmethod
    def validate_bcrypt_password_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码的 UTF-8 编码不能超过 72 字节")
        return value


class RegisterRequest(CredentialsRequest):
    pass


class LoginRequest(CredentialsRequest):
    pass


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    is_active: bool
    created_at: str
