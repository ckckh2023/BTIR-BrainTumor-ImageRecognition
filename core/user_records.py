'''用户记录模型'''

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


def normalize_username(username: str) -> str:
    '''生成用于唯一约束和账号查找的用户名规范值'''
    return username.casefold()


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str
    username: str
    hashed_password: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    must_change_password: bool = False
    token_version: int = 0
    created_at: datetime
    updated_at: datetime
