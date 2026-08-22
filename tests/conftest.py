import pytest
from app.database import create_db_and_tables
from app.seed import seed

@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    create_db_and_tables()
    seed()
    yield
