from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import Job
from app.settings import DEMO_DATABASE, ROOT, settings
from scripts.build_static_bundle import BUNDLE_PATH, CSS_SOURCES, STATIC_DIR


def test_demo_database_is_isolated() -> None:
    assert settings.demo_mode is True
    assert DEMO_DATABASE == (ROOT / "data" / "demo.db").resolve()
    assert "jobs.db" not in settings.database_url


def test_demo_pages_and_mutation_guard() -> None:
    with TestClient(app, follow_redirects=False) as client:
        pages = ("/", "/jobs/1", "/calibration", "/application-outcomes")
        for path in pages:
            response = client.get(path)
            assert response.status_code == 200
            assert response.text.count('rel="stylesheet"') == 1
            assert "/static/app.css?v=" in response.text
            assert "/static/favicon.svg?v=" in response.text

        stylesheet = client.get("/static/app.css")
        assert stylesheet.status_code == 200
        assert stylesheet.headers["content-type"].startswith("text/css")
        assert stylesheet.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert stylesheet.headers["x-content-type-options"] == "nosniff"
        assert client.get("/static/favicon.svg").status_code == 200
        legacy_favicon = client.get("/favicon.ico")
        assert legacy_favicon.status_code == 307
        assert legacy_favicon.headers["location"].startswith("/static/favicon.svg?v=")

        with SessionLocal() as db:
            before = db.scalar(select(func.count(Job.id)))
        assert client.post("/jobs/1/delete").status_code == 303
        assert client.post("/api/v1/jobs", json={}).status_code == 403
        with SessionLocal() as db:
            after = db.scalar(select(func.count(Job.id)))
        assert before == after == 8


def test_css_bundle_matches_sources() -> None:
    bundle = BUNDLE_PATH.read_text(encoding="utf-8")
    for name in CSS_SOURCES:
        assert f"/* {name} */" in bundle
        assert (STATIC_DIR / name).read_text(encoding="utf-8").strip() in bundle
