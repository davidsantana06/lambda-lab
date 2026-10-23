from sqlmodel import SQLModel, Session, create_engine
import os


# Not DATABASE_URL: Chainlit reads that one to enable its PostgreSQL chat history.
engine = create_engine(
    os.environ["CACHE_DATABASE_URL"],
    connect_args={"check_same_thread": False},
)


def create_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
