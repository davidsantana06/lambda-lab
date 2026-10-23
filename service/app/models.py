from datetime import datetime
from sqlalchemy import func
from sqlmodel import Field
from typing import Optional

from schemas import AlgorithmBase, ExecutionBase


class Algorithm(AlgorithmBase, table=True):
    __tablename__ = "algorithm"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={"server_default": func.now()},
    )


class Execution(ExecutionBase, table=True):
    __tablename__ = "execution"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={"server_default": func.now()},
    )
