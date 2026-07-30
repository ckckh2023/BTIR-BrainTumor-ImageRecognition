'''用户记录模型'''

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str
    username: str
    email: str
    hashed_password: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
