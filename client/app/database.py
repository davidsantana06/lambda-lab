from sqlmodel import SQLModel, Session, create_engine
import os


# DATABASE_URL não serve: o Chainlit a usa para ligar o histórico em PostgreSQL.
engine = create_engine(
    os.environ["CACHE_DATABASE_URL"],
    connect_args={"check_same_thread": False},
)


def create_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
