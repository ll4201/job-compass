from collections.abc import Generator
from datetime import datetime
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import settings

Path("data").mkdir(exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    from app import models  # noqa: F401

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    job_migrations = {
        "is_sample": "BOOLEAN NOT NULL DEFAULT 0",
        "manual_grade": "VARCHAR(1)",
        "manual_score": "FLOAT",
        "manual_decision": "VARCHAR(30)",
        "manual_comment": "TEXT",
        "reviewed_by_user": "BOOLEAN NOT NULL DEFAULT 0",
        "reviewed_at": "DATETIME",
        "calibration_status": "VARCHAR(30) NOT NULL DEFAULT 'unreviewed'",
        "travel_level": "VARCHAR(30) NOT NULL DEFAULT 'unknown'",
        "resume_output_potential": "VARCHAR(20) NOT NULL DEFAULT 'unclear'",
        "conversion_level": "VARCHAR(30)",
        "last_checked_at": "DATETIME",
        "last_verified_at": "DATETIME",
        "closure_reason": "TEXT",
        "viewed_at": "DATETIME",
        "is_new": "BOOLEAN NOT NULL DEFAULT 0",
        "source_count": "INTEGER NOT NULL DEFAULT 1",
        "freshness_status": "VARCHAR(30) NOT NULL DEFAULT 'existing'",
        "availability_status": "VARCHAR(30) NOT NULL DEFAULT 'active'",
        "missing_run_count": "INTEGER NOT NULL DEFAULT 0",
        "title_location": "VARCHAR(255)",
        "structured_location": "VARCHAR(255)",
        "office_location": "VARCHAR(500)",
        "jd_location": "VARCHAR(255)",
        "normalized_location": "VARCHAR(255)",
        "location_conflict": "BOOLEAN NOT NULL DEFAULT 0",
        "location_conflict_reason": "TEXT",
    }
    assessment_migrations = {
        "travel_level": "VARCHAR(30) NOT NULL DEFAULT 'unknown'",
        "travel_penalty": "FLOAT NOT NULL DEFAULT 0",
        "scoring_config_hash": "VARCHAR(64)",
        "explanation_json": "TEXT NOT NULL DEFAULT '{}'",
        "fit_score": "FLOAT",
        "opportunity_score": "FLOAT",
        "information_completeness": "FLOAT",
        "risk_level": "VARCHAR(20)",
        "application_recommendation": "VARCHAR(30)",
        "company_type": "VARCHAR(30)",
        "opportunity_breakdown_json": "TEXT NOT NULL DEFAULT '{}'",
        "seniority_level": "VARCHAR(30)",
        "role_direction_match": "VARCHAR(20)",
        "seniority_match": "VARCHAR(20)",
        "experience_match": "VARCHAR(20)",
        "career_match_score": "FLOAT",
        "career_match_level": "VARCHAR(30)",
        "career_value_score": "FLOAT",
        "career_value_level": "VARCHAR(30)",
        "eligibility_score": "FLOAT",
        "direction_fit_score": "FLOAT",
        "life_quality_score": "FLOAT",
        "freshness_score": "FLOAT",
        "compensation_score": "FLOAT",
        "overall_priority_score": "FLOAT",
        "support_role_type": "VARCHAR(40)",
        "needs_confirmation": "BOOLEAN",
        "resume_type": "VARCHAR(30)",
        "job_age_days": "INTEGER",
        "date_source": "VARCHAR(20)",
        "employer_acceptance_score": "FLOAT",
        "employer_acceptance_level": "VARCHAR(30)",
        "personal_preference_score": "FLOAT",
        "personal_preference_level": "VARCHAR(30)",
        "final_strategy": "VARCHAR(30)",
        "decision_reason": "TEXT",
        "action_type": "VARCHAR(40)",
        "action_priority": "VARCHAR(20)",
        "profile_version": "VARCHAR(50)",
    }
    history_migrations = {
        "fit_score": "FLOAT",
        "opportunity_score": "FLOAT",
        "information_completeness": "FLOAT",
        "risk_level": "VARCHAR(20)",
        "application_recommendation": "VARCHAR(30)",
        "seniority_level": "VARCHAR(30)",
        "role_direction_match": "VARCHAR(20)",
        "seniority_match": "VARCHAR(20)",
        "experience_match": "VARCHAR(20)",
        "career_match_score": "FLOAT",
        "career_match_level": "VARCHAR(30)",
        "career_value_score": "FLOAT",
        "career_value_level": "VARCHAR(30)",
        "eligibility_score": "FLOAT",
        "direction_fit_score": "FLOAT",
        "life_quality_score": "FLOAT",
        "freshness_score": "FLOAT",
        "compensation_score": "FLOAT",
        "overall_priority_score": "FLOAT",
        "support_role_type": "VARCHAR(40)",
        "needs_confirmation": "BOOLEAN",
        "resume_type": "VARCHAR(30)",
        "job_age_days": "INTEGER",
        "date_source": "VARCHAR(20)",
        "employer_acceptance_score": "FLOAT",
        "employer_acceptance_level": "VARCHAR(30)",
        "personal_preference_score": "FLOAT",
        "personal_preference_level": "VARCHAR(30)",
        "final_strategy": "VARCHAR(30)",
        "decision_reason": "TEXT",
    }
    source_link_migrations = {
        "source_id": "VARCHAR(100)",
        "first_seen_at": "DATETIME",
        "last_seen_at": "DATETIME",
        "last_checked_at": "DATETIME",
        "last_verified_at": "DATETIME",
        "closure_reason": "TEXT",
        "is_primary": "BOOLEAN NOT NULL DEFAULT 0",
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        "missing_run_count": "INTEGER NOT NULL DEFAULT 0",
        "availability_status": "VARCHAR(30) NOT NULL DEFAULT 'active'",
    }
    raw_job_migrations = {
        "job_title": "VARCHAR(500)",
        "raw_location": "TEXT",
        "source_location_payload": "TEXT",
        "normalized_location": "TEXT",
        "location_reason": "TEXT",
    }
    candidate_company_migrations = {
        "industry": "VARCHAR(120)",
    }
    existing_job_columns = (
        {column["name"] for column in inspector.get_columns("jobs")}
        if "jobs" in existing_tables
        else set()
    )
    existing_assessment_columns = (
        {column["name"] for column in inspector.get_columns("job_assessments")}
        if "job_assessments" in existing_tables
        else set()
    )
    existing_history_columns = (
        {column["name"] for column in inspector.get_columns("assessment_history")}
        if "assessment_history" in existing_tables
        else set()
    )
    existing_source_link_columns = (
        {column["name"] for column in inspector.get_columns("job_sources")}
        if "job_sources" in existing_tables
        else set()
    )
    existing_raw_job_columns = (
        {column["name"] for column in inspector.get_columns("raw_collected_jobs")}
        if "raw_collected_jobs" in existing_tables
        else set()
    )
    existing_candidate_company_columns = (
        {column["name"] for column in inspector.get_columns("candidate_companies")}
        if "candidate_companies" in existing_tables
        else set()
    )
    pending = bool(
        (set(job_migrations) - existing_job_columns)
        or (set(assessment_migrations) - existing_assessment_columns)
        or (set(history_migrations) - existing_history_columns)
        or (set(source_link_migrations) - existing_source_link_columns)
        or (set(raw_job_migrations) - existing_raw_job_columns)
        or (set(candidate_company_migrations) - existing_candidate_company_columns)
        or ("jobs" in existing_tables and "assessment_history" not in existing_tables)
        or (
            "jobs" in existing_tables
            and {
                "external_evidence",
                "evidence_analyses",
                "evidence_adjustment_history",
                "job_source_configs",
                "candidate_companies",
                "collection_runs",
                "raw_collected_jobs",
                "candidate_workflows",
                "candidate_workflow_history",
                "application_feedback",
            }
            - existing_tables
        )
    )
    if pending:
        _backup_before_migration()
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for name, definition in job_migrations.items():
            if name not in existing_job_columns and "jobs" in existing_tables:
                connection.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {definition}"))
        for name, definition in assessment_migrations.items():
            if name not in existing_assessment_columns and "job_assessments" in existing_tables:
                connection.execute(
                    text(f"ALTER TABLE job_assessments ADD COLUMN {name} {definition}")
                )
        for name, definition in history_migrations.items():
            if name not in existing_history_columns and "assessment_history" in existing_tables:
                connection.execute(
                    text(f"ALTER TABLE assessment_history ADD COLUMN {name} {definition}")
                )
        for name, definition in source_link_migrations.items():
            if name not in existing_source_link_columns and "job_sources" in existing_tables:
                connection.execute(text(f"ALTER TABLE job_sources ADD COLUMN {name} {definition}"))
        for name, definition in raw_job_migrations.items():
            if name not in existing_raw_job_columns and "raw_collected_jobs" in existing_tables:
                connection.execute(
                    text(f"ALTER TABLE raw_collected_jobs ADD COLUMN {name} {definition}")
                )
        for name, definition in candidate_company_migrations.items():
            if name not in existing_candidate_company_columns and "candidate_companies" in existing_tables:
                connection.execute(
                    text(f"ALTER TABLE candidate_companies ADD COLUMN {name} {definition}")
                )


def _backup_before_migration() -> Path | None:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    database_path = Path(settings.database_url.removeprefix(prefix))
    if not database_path.exists() or database_path.name == ":memory:":
        return None
    backup_dir = database_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = (
        backup_dir / f"{database_path.stem}-auto-pre-migration-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    )
    source = sqlite3.connect(database_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup_path
