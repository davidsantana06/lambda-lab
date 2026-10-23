from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, col, select

from database import get_session
from models import Algorithm, Execution
from schemas import (
    AlgorithmCreate,
    AlgorithmSearch,
    AlgorithmValidate,
    AlgorithmValidation,
    ExecutionCreate,
    ExecutionRead,
    ExecutionSearch,
)
from services import monitor_execution, run_execution, validate_source_code

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "algorithm"}


@router.post("/algorithms/validate", response_model=AlgorithmValidation)
def validate_algorithm(payload: AlgorithmValidate):
    return validate_source_code(payload.source_code, payload.entry_point)


@router.post("/algorithms", response_model=Algorithm, status_code=201)
def create_algorithm(payload: AlgorithmCreate, session: Session = Depends(get_session)):
    validation = validate_source_code(payload.source_code, payload.entry_point)
    if not validation.valid:
        raise HTTPException(status_code=400, detail=validation.model_dump())
    algorithm = Algorithm.model_validate(payload)
    session.add(algorithm)
    session.commit()
    session.refresh(algorithm)
    return algorithm


@router.get("/algorithms", response_model=list[Algorithm])
def list_algorithms(
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    return session.exec(select(Algorithm).offset(offset).limit(limit)).all()


@router.get("/algorithms/search", response_model=list[Algorithm])
def search_algorithms(
    filters: AlgorithmSearch = Depends(),
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    statement = select(Algorithm)
    if filters.name is not None:
        statement = statement.where(col(Algorithm.name).ilike(f"%{filters.name}%"))
    if filters.description is not None:
        statement = statement.where(
            col(Algorithm.description).ilike(f"%{filters.description}%")
        )
    return session.exec(statement.offset(offset).limit(limit)).all()


@router.get("/algorithms/{algorithm_id}", response_model=Algorithm)
def get_algorithm(algorithm_id: int, session: Session = Depends(get_session)):
    algorithm = session.get(Algorithm, algorithm_id)
    if not algorithm:
        raise HTTPException(status_code=404, detail="algorithm not found")
    return algorithm


@router.post(
    "/algorithms/{algorithm_id}/executions",
    response_model=Execution,
    status_code=202,
)
def create_execution(
    algorithm_id: int,
    payload: ExecutionCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    algorithm = session.get(Algorithm, algorithm_id)
    if not algorithm:
        raise HTTPException(status_code=404, detail="algorithm not found")
    execution = Execution(algorithm_id=algorithm_id, arguments=payload.arguments)
    session.add(execution)
    session.commit()
    session.refresh(execution)
    background_tasks.add_task(run_execution, execution.id)
    return execution


@router.get("/executions", response_model=list[Execution])
def list_executions(
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    return session.exec(select(Execution).offset(offset).limit(limit)).all()


@router.get("/executions/search", response_model=list[Execution])
def search_executions(
    filters: ExecutionSearch = Depends(),
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    statement = select(Execution)
    if filters.status is not None:
        statement = statement.where(Execution.status == filters.status)
    if filters.algorithm_id is not None:
        statement = statement.where(Execution.algorithm_id == filters.algorithm_id)
    return session.exec(statement.offset(offset).limit(limit)).all()


@router.get("/executions/{execution_id}", response_model=ExecutionRead)
def get_execution(execution_id: int, session: Session = Depends(get_session)):
    execution = session.get(Execution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="execution not found")
    return monitor_execution(execution)
