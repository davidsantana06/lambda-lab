from datetime import datetime
from sqlalchemy import JSON, func
from sqlmodel import Field, SQLModel
from typing import Optional


class CachedAnswer(SQLModel, table=True):
    __tablename__ = "cached_answer"

    id: Optional[int] = Field(default=None, primary_key=True)
    question: str
    answer: str
    embedding: list[float] = Field(sa_type=JSON)
    embedding_model: str
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={"server_default": func.now()},
    )
