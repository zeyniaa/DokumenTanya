from typing import Literal

from pydantic import BaseModel, Field


class ConversationInput(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=5)


class MessageInput(BaseModel):
    question: str = Field(min_length=1, max_length=3000)
    request_id: str = Field(min_length=8, max_length=100)


class CorrectionInput(BaseModel):
    expected_version_id: str
    text: str = Field(min_length=1, max_length=20000)


class CalculationInput(BaseModel):
    version_id: str
    table_id: str
    column: int = Field(ge=0)
    operation: Literal["sum", "average", "min", "max", "count"]


class Claim(BaseModel):
    text: str = Field(max_length=5000)
    source_ids: list[str] = Field(max_length=12)


class GeneratedAnswer(BaseModel):
    answer_status: Literal["answered", "insufficient_evidence"]
    claims: list[Claim] = Field(max_length=20)
