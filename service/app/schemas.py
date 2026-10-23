from datetime import datetime
from sqlalchemy import JSON
from sqlmodel import Field, SQLModel
from typing import Any, Literal, Optional

ExecutionStatus = Literal["pending", "running", "completed", "failed", "timed_out"]


class AlgorithmBase(SQLModel):
    name: str
    description: str
    source_code: str
    entry_point: str = "solve"


class AlgorithmCreate(AlgorithmBase):
    pass


class AlgorithmValidate(SQLModel):
    source_code: str
    entry_point: str = "solve"


class AlgorithmValidation(SQLModel):
    valid: bool
    line: Optional[int] = None
    column: Optional[int] = None
    message: Optional[str] = None


class AlgorithmSearch(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ExecutionBase(SQLModel):
    algorithm_id: int = Field(foreign_key="algorithm.id")
    arguments: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    status: str = "pending"
    result: Optional[Any] = Field(default=None, sa_type=JSON)
    stdout: Optional[str] = None
    error: Optional[str] = None
    duration_in_ms: Optional[float] = None
    peak_memory_in_kb: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ExecutionCreate(SQLModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExecutionSearch(SQLModel):
    status: Optional[ExecutionStatus] = None
    algorithm_id: Optional[int] = None


class ExecutionRead(ExecutionBase):
    id: int
    elapsed_in_ms: Optional[float] = None
    created_at: Optional[datetime] = None
