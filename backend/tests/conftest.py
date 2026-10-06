import os

# 必须在导入 app.* 之前：默认配置指向 postgres，测试一律用内存 SQLite。
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.seed import seed_if_empty


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSession()
    seed_if_empty(db)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    def _get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    # 不用 with：避免触发 lifespan 里对真实 engine 的 ensure_schema。
    yield TestClient(app)
    app.dependency_overrides.clear()
