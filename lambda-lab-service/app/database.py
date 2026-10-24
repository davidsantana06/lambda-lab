from collections.abc import Iterator
from sqlalchemy import JSON
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import TypeCompiler
from sqlmodel import SQLModel, Session, create_engine
from typing import Any
import os


engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"check_same_thread": False},
)


# No SQLite, JSON tem afinidade numérica e converte inteiros grandes em float.
@compiles(JSON, "sqlite")
def compile_json_as_text(type_: JSON, compiler: TypeCompiler, **kwargs: Any) -> str:
    return "TEXT"


def create_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
