"""Validated public shape for the supplementary model analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupplementaryAnalysisContent(BaseModel):
    """The only model-generated content that may be saved for frontend display."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=1200)
    observations: list[str] = Field(min_length=1, max_length=5)
    consistency: Literal["consistent", "inconclusive", "conflicting"]
    uncertainties: list[str] = Field(default_factory=list, max_length=5)
    follow_up: str = Field(min_length=1, max_length=500)

    @field_validator("observations", "uncertainties")
    @classmethod
    def validate_text_items(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() or len(item) > 400 for item in value):
            raise ValueError("分析列表项必须是 1 到 400 个字符的非空字符串")
        return value
