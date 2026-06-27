"""Shared test fixtures for the DVD ripper backend."""
import os
import sys
from contextlib import contextmanager

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

# Ensure the backend app is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database as database_module  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def test_engine():
    """Replace the production SQLite engine with an in-memory test engine."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Point the app at the test engine.
    original_engine = database_module.engine
    database_module.engine = engine

    # Create all tables.
    SQLModel.metadata.create_all(engine)

    yield engine

    # Restore the original engine after tests.
    database_module.engine = original_engine


@pytest.fixture
def db_session(test_engine):
    """Provide a clean database session for a test."""
    with Session(test_engine) as session:
        yield session
        session.rollback()
