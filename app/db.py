from collections.abc import Generator
from os import getenv

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = getenv("DATABASE_URL", "sqlite:///./iker_care.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def apply_lightweight_migrations() -> None:
    """Agrega columnas nuevas sin borrar ni recrear la base existente."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "medications" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("medications")}
        if "frequency" not in columns:
            connection.execute(text("ALTER TABLE medications ADD COLUMN frequency VARCHAR(120)"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
