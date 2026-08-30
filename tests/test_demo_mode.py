from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import Job
from app.settings import DEMO_DATABASE, ROOT, settings


def test_demo_database_is_isolated() -> None:
    assert settings.demo_mode is True
    assert DEMO_DATABASE == (ROOT / "data" / "demo.db").resolve()
    assert "jobs.db" not in settings.database_url


def test_demo_pages_and_mutation_guard() -> None:
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/").status_code == 200
        assert client.get("/jobs/1").status_code == 200
        with SessionLocal() as db:
            before = db.scalar(select(func.count(Job.id)))
        assert client.post("/jobs/1/delete").status_code == 303
        assert client.post("/api/v1/jobs", json={}).status_code == 403
        with SessionLocal() as db:
            after = db.scalar(select(func.count(Job.id)))
        assert before == after == 8
