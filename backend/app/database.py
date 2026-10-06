from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    """无迁移框架下的幂等补丁：create_all 负责新表，缺失的列在这里补。"""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    table_cols = {
        "ingredients": {
            "reserved_qty": "ALTER TABLE ingredients ADD COLUMN reserved_qty FLOAT NOT NULL DEFAULT 0.0",
        },
    }
    with engine.begin() as conn:
        for table, columns in table_cols.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(ddl))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
