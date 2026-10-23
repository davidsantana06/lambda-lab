from datetime import datetime
from pydantic import BaseModel
from typing import Any, Literal, Optional

ExecutionStatus = Literal["pending", "running", "completed", "failed", "timed_out"]


class Algorithm(BaseModel):
    id: Optional[int] = None
    name: str
    description: str
    source_code: str
    entry_point: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AlgorithmValidation(BaseModel):
    valid: bool
    line: Optional[int] = None
    column: Optional[int] = None
    message: Optional[str] = None


class Execution(BaseModel):
    id: Optional[int] = None
    algorithm_id: int
    arguments: dict[str, Any]
    status: ExecutionStatus
    result: Optional[Any] = None
    stdout: Optional[str] = None
    error: Optional[str] = None
    duration_in_ms: Optional[float] = None
    elapsed_in_ms: Optional[float] = None
    peak_memory_in_kb: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
