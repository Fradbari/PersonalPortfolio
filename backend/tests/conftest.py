"""Pytest configuration for transaction tests."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Category, CategoryMap, CategoryPending, Account, ImportBatch, Transaction


@pytest.fixture
def test_db():
    """Create an in-memory test database with all tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_session_factory(test_db):
    """Create a session factory for the test database."""
    return sessionmaker(bind=test_db, future=True)
