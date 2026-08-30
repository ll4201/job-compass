from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "source_job_id", name="uq_source_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100), default="manual")
    source_job_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    job_title: Mapped[str] = mapped_column(String(255), index=True)
    role_direction: Mapped[str | None] = mapped_column(String(100), index=True)
    job_type: Mapped[str] = mapped_column(String(50), default="full_time", index=True)
    employment_type: Mapped[str | None] = mapped_column(String(100))
    recruitment_type: Mapped[str | None] = mapped_column(String(100))
    location_raw: Mapped[str] = mapped_column(String(255), default="")
    title_location: Mapped[str | None] = mapped_column(String(255), index=True)
    structured_location: Mapped[str | None] = mapped_column(String(255))
    office_location: Mapped[str | None] = mapped_column(String(500))
    jd_location: Mapped[str | None] = mapped_column(String(255))
    normalized_location: Mapped[str | None] = mapped_column(String(255), index=True)
    location_conflict: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    location_conflict_reason: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    district: Mapped[str | None] = mapped_column(String(100))
    workplace_status: Mapped[str] = mapped_column(String(50), default="unconfirmed")
    salary_raw: Mapped[str | None] = mapped_column(String(255))
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_period: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(10), default="CNY")
    experience_raw: Mapped[str | None] = mapped_column(String(255))
    experience_min: Mapped[float | None] = mapped_column(Float)
    experience_max: Mapped[float | None] = mapped_column(Float)
    education_requirement: Mapped[str | None] = mapped_column(String(255))
    major_requirement: Mapped[str | None] = mapped_column(Text)
    language_requirement: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    responsibilities: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    benefits_raw: Mapped[str | None] = mapped_column(Text)
    working_schedule: Mapped[str] = mapped_column(String(50), default="not_disclosed")
    five_insurances_housing_fund: Mapped[str] = mapped_column(String(50), default="not_disclosed")
    paid_leave: Mapped[str] = mapped_column(String(50), default="not_disclosed")
    statutory_holiday_status: Mapped[str] = mapped_column(String(50), default="not_disclosed")
    overtime_risk: Mapped[str] = mapped_column(String(50), default="not_disclosed")
    contract_entity_status: Mapped[str] = mapped_column(String(50), default="not_disclosed")
    internship_conversion: Mapped[str] = mapped_column(String(50), default="not_disclosed")
    travel_requirement: Mapped[str] = mapped_column(String(100), default="not_disclosed")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_reason: Mapped[str | None] = mapped_column(Text)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_new: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    freshness_status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    availability_status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    missing_run_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    manual_grade: Mapped[str | None] = mapped_column(String(1), index=True)
    manual_score: Mapped[float | None] = mapped_column(Float)
    manual_decision: Mapped[str | None] = mapped_column(String(30), index=True)
    manual_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calibration_status: Mapped[str] = mapped_column(String(30), default="unreviewed", index=True)
    travel_level: Mapped[str] = mapped_column(String(30), default="unknown", index=True)
    resume_output_potential: Mapped[str] = mapped_column(String(20), default="unclear")
    conversion_level: Mapped[str | None] = mapped_column(String(30))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    application_status: Mapped[str] = mapped_column(String(50), default="待评估", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    assessment: Mapped["JobAssessment | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    assessment_history: Mapped[list["AssessmentHistory"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="AssessmentHistory.assessed_at.desc()",
    )
    sources: Mapped[list["JobSource"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    external_evidence: Mapped[list["ExternalEvidence"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    evidence_analysis: Mapped["EvidenceAnalysis | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    evidence_adjustment_history: Mapped[list["EvidenceAdjustmentHistory"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    candidate_workflow: Mapped["CandidateWorkflow | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    workflow_history: Mapped[list["CandidateWorkflowHistory"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="CandidateWorkflowHistory.changed_at.desc()",
    )
    application_feedback: Mapped["ApplicationFeedback | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class JobSource(Base):
    __tablename__ = "job_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    source_id: Mapped[str | None] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(100))
    source_job_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_reason: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    missing_run_count: Mapped[int] = mapped_column(Integer, default=0)
    availability_status: Mapped[str] = mapped_column(String(30), default="active")
    job: Mapped[Job] = relationship(back_populates="sources")


class JobSourceConfig(Base):
    __tablename__ = "job_source_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    base_url: Mapped[str | None] = mapped_column(Text)
    board_token: Mapped[str | None] = mapped_column(String(255))
    slug: Mapped[str | None] = mapped_column(String(255))
    tenant: Mapped[str | None] = mapped_column(String(255))
    site: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(30), default="zh_CN")
    listing_url: Mapped[str | None] = mapped_column(Text)
    detail_url_pattern: Mapped[str | None] = mapped_column(Text)
    request_method: Mapped[str] = mapped_column(String(10), default="GET")
    headers_json: Mapped[str] = mapped_column(Text, default="{}")
    pagination_json: Mapped[str] = mapped_column(Text, default="{}")
    selectors_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    collection_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    max_pages: Mapped[int] = mapped_column(Integer, default=5)
    request_interval_seconds: Mapped[float] = mapped_column(Float, default=1.0)
    missing_run_threshold: Mapped[int] = mapped_column(Integer, default=3)
    inactive_days_threshold: Mapped[int] = mapped_column(Integer, default=14)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_status: Mapped[str | None] = mapped_column(String(30))
    last_error: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    runs: Mapped[list["CollectionRun"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class CandidateCompany(Base):
    __tablename__ = "candidate_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(120), index=True)
    official_website: Mapped[str | None] = mapped_column(Text)
    careers_url: Mapped[str | None] = mapped_column(Text)
    detected_ats: Mapped[str] = mapped_column(String(30), default="unknown", index=True)
    discovery_source: Mapped[str] = mapped_column(String(100), default="manual")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    monitoring_status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    user_priority: Mapped[int] = mapped_column(Integer, default=50)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("job_source_configs.source_id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    shenzhen_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    filtered_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[JobSourceConfig] = relationship(back_populates="runs")
    raw_jobs: Mapped[list["RawCollectedJobRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RawCollectedJobRecord(Base):
    __tablename__ = "raw_collected_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(100), index=True)
    source_job_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[str] = mapped_column(Text, default="{}")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    job_title: Mapped[str | None] = mapped_column(String(500))
    raw_location: Mapped[str | None] = mapped_column(Text)
    source_location_payload: Mapped[str | None] = mapped_column(Text)
    normalized_location: Mapped[str | None] = mapped_column(Text)
    normalized_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    location_status: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    location_reason: Mapped[str | None] = mapped_column(Text)
    imported_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    error_message: Mapped[str | None] = mapped_column(Text)
    run: Mapped[CollectionRun] = relationship(back_populates="raw_jobs")


class JobAssessment(Base):
    __tablename__ = "job_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    hard_filter_status: Mapped[str] = mapped_column(String(50))
    hard_filter_reasons: Mapped[str] = mapped_column(Text, default="[]")
    role_match_score: Mapped[float] = mapped_column(Float, default=0)
    compensation_benefits_score: Mapped[float] = mapped_column(Float, default=0)
    entry_level_score: Mapped[float] = mapped_column(Float, default=0)
    english_overseas_score: Mapped[float] = mapped_column(Float, default=0)
    technical_project_score: Mapped[float] = mapped_column(Float, default=0)
    career_growth_score: Mapped[float] = mapped_column(Float, default=0)
    company_quality_score: Mapped[float] = mapped_column(Float, default=0)
    penalty_score: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    fit_score: Mapped[float | None] = mapped_column(Float, index=True)
    opportunity_score: Mapped[float | None] = mapped_column(Float, index=True)
    information_completeness: Mapped[float | None] = mapped_column(Float, index=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)
    application_recommendation: Mapped[str | None] = mapped_column(String(30), index=True)
    seniority_level: Mapped[str | None] = mapped_column(String(30), index=True)
    role_direction_match: Mapped[str | None] = mapped_column(String(20), index=True)
    seniority_match: Mapped[str | None] = mapped_column(String(20), index=True)
    experience_match: Mapped[str | None] = mapped_column(String(20), index=True)
    career_match_score: Mapped[float | None] = mapped_column(Float, index=True)
    career_match_level: Mapped[str | None] = mapped_column(String(30), index=True)
    career_value_score: Mapped[float | None] = mapped_column(Float, index=True)
    career_value_level: Mapped[str | None] = mapped_column(String(30), index=True)
    eligibility_score: Mapped[float | None] = mapped_column(Float, index=True)
    direction_fit_score: Mapped[float | None] = mapped_column(Float, index=True)
    life_quality_score: Mapped[float | None] = mapped_column(Float, index=True)
    freshness_score: Mapped[float | None] = mapped_column(Float, index=True)
    compensation_score: Mapped[float | None] = mapped_column(Float, index=True)
    overall_priority_score: Mapped[float | None] = mapped_column(Float, index=True)
    support_role_type: Mapped[str | None] = mapped_column(String(40), index=True)
    needs_confirmation: Mapped[bool | None] = mapped_column(Boolean, index=True)
    resume_type: Mapped[str | None] = mapped_column(String(30), index=True)
    job_age_days: Mapped[int | None] = mapped_column(Integer)
    date_source: Mapped[str | None] = mapped_column(String(20))
    employer_acceptance_score: Mapped[float | None] = mapped_column(Float, index=True)
    employer_acceptance_level: Mapped[str | None] = mapped_column(String(30), index=True)
    personal_preference_score: Mapped[float | None] = mapped_column(Float, index=True)
    personal_preference_level: Mapped[str | None] = mapped_column(String(30), index=True)
    final_strategy: Mapped[str | None] = mapped_column(String(30), index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    action_type: Mapped[str | None] = mapped_column(String(40), index=True)
    action_priority: Mapped[str | None] = mapped_column(String(20), index=True)
    profile_version: Mapped[str | None] = mapped_column(String(50))
    company_type: Mapped[str | None] = mapped_column(String(30), index=True)
    opportunity_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    grade: Mapped[str] = mapped_column(String(1), index=True)
    recommendation: Mapped[str] = mapped_column(Text)
    strengths: Mapped[str] = mapped_column(Text, default="[]")
    risks: Mapped[str] = mapped_column(Text, default="[]")
    missing_information: Mapped[str] = mapped_column(Text, default="[]")
    interview_questions: Mapped[str] = mapped_column(Text, default="[]")
    suggested_resume_track: Mapped[str] = mapped_column(String(100))
    assessment_version: Mapped[str] = mapped_column(String(50), default="rules-v1")
    travel_level: Mapped[str] = mapped_column(String(30), default="unknown")
    travel_penalty: Mapped[float] = mapped_column(Float, default=0)
    scoring_config_hash: Mapped[str | None] = mapped_column(String(64))
    explanation_json: Mapped[str] = mapped_column(Text, default="{}")
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job: Mapped[Job] = relationship(back_populates="assessment")


class AssessmentHistory(Base):
    __tablename__ = "assessment_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    assessment_version: Mapped[str] = mapped_column(String(50))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    total_score: Mapped[float] = mapped_column(Float)
    fit_score: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    information_completeness: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    application_recommendation: Mapped[str | None] = mapped_column(String(30))
    seniority_level: Mapped[str | None] = mapped_column(String(30))
    role_direction_match: Mapped[str | None] = mapped_column(String(20))
    seniority_match: Mapped[str | None] = mapped_column(String(20))
    experience_match: Mapped[str | None] = mapped_column(String(20))
    career_match_score: Mapped[float | None] = mapped_column(Float)
    career_match_level: Mapped[str | None] = mapped_column(String(30))
    career_value_score: Mapped[float | None] = mapped_column(Float)
    career_value_level: Mapped[str | None] = mapped_column(String(30))
    eligibility_score: Mapped[float | None] = mapped_column(Float)
    direction_fit_score: Mapped[float | None] = mapped_column(Float)
    life_quality_score: Mapped[float | None] = mapped_column(Float)
    freshness_score: Mapped[float | None] = mapped_column(Float)
    compensation_score: Mapped[float | None] = mapped_column(Float)
    overall_priority_score: Mapped[float | None] = mapped_column(Float)
    support_role_type: Mapped[str | None] = mapped_column(String(40))
    needs_confirmation: Mapped[bool | None] = mapped_column(Boolean)
    resume_type: Mapped[str | None] = mapped_column(String(30))
    job_age_days: Mapped[int | None] = mapped_column(Integer)
    date_source: Mapped[str | None] = mapped_column(String(20))
    employer_acceptance_score: Mapped[float | None] = mapped_column(Float)
    employer_acceptance_level: Mapped[str | None] = mapped_column(String(30))
    personal_preference_score: Mapped[float | None] = mapped_column(Float)
    personal_preference_level: Mapped[str | None] = mapped_column(String(30))
    final_strategy: Mapped[str | None] = mapped_column(String(30))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str] = mapped_column(String(1))
    penalty_score: Mapped[float] = mapped_column(Float, default=0)
    travel_level: Mapped[str] = mapped_column(String(30), default="unknown")
    travel_penalty: Mapped[float] = mapped_column(Float, default=0)
    scoring_config_hash: Mapped[str | None] = mapped_column(String(64))
    job: Mapped[Job] = relationship(back_populates="assessment_history")


class CandidateWorkflow(Base):
    __tablename__ = "candidate_workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    job: Mapped[Job] = relationship(back_populates="candidate_workflow")


class CandidateWorkflowHistory(Base):
    __tablename__ = "candidate_workflow_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job: Mapped[Job] = relationship(back_populates="workflow_history")


class ApplicationFeedback(Base):
    __tablename__ = "application_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
    applied: Mapped[bool | None] = mapped_column(Boolean)
    not_applied_reason: Mapped[str | None] = mapped_column(String(40), index=True)
    interview_result: Mapped[str | None] = mapped_column(String(30), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    job: Mapped[Job] = relationship(back_populates="application_feedback")


class ExternalEvidence(Base):
    __tablename__ = "external_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_platform: Mapped[str] = mapped_column(String(50), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_title: Mapped[str | None] = mapped_column(String(500))
    source_author_type: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    department: Mapped[str | None] = mapped_column(String(255), index=True)
    role_name: Mapped[str | None] = mapped_column(String(255), index=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), index=True)
    evidence_text: Mapped[str] = mapped_column(Text)
    evidence_category: Mapped[str] = mapped_column(String(60), index=True)
    evidence_value: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(String(30), default="neutral")
    source_confidence: Mapped[str] = mapped_column(String(30), default="low", index=True)
    relevance_level: Mapped[str] = mapped_column(String(30), default="low", index=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="unverified", index=True)
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    user_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    job: Mapped[Job | None] = relationship(back_populates="external_evidence")


class EvidenceAnalysis(Base):
    __tablename__ = "evidence_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
    evidence_completeness_boost: Mapped[float] = mapped_column(Float, default=0)
    evidence_opportunity_adjustment: Mapped[float] = mapped_column(Float, default=0)
    evidence_risk_adjustment: Mapped[int] = mapped_column(Integer, default=0)
    evidence_confidence: Mapped[str] = mapped_column(String(30), default="none")
    evidence_summary: Mapped[str] = mapped_column(Text, default="")
    adjusted_information_completeness: Mapped[float | None] = mapped_column(Float)
    adjusted_opportunity_score: Mapped[float | None] = mapped_column(Float)
    adjusted_risk_level: Mapped[str | None] = mapped_column(String(20))
    interview_questions_json: Mapped[str] = mapped_column(Text, default="[]")
    explanation_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_signature: Mapped[str | None] = mapped_column(String(64))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job: Mapped[Job] = relationship(back_populates="evidence_analysis")


class EvidenceAdjustmentHistory(Base):
    __tablename__ = "evidence_adjustment_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    base_fit_score: Mapped[float | None] = mapped_column(Float)
    base_opportunity_score: Mapped[float | None] = mapped_column(Float)
    base_information_completeness: Mapped[float | None] = mapped_column(Float)
    base_risk_level: Mapped[str | None] = mapped_column(String(20))
    evidence_completeness_boost: Mapped[float] = mapped_column(Float, default=0)
    evidence_opportunity_adjustment: Mapped[float] = mapped_column(Float, default=0)
    evidence_risk_adjustment: Mapped[int] = mapped_column(Integer, default=0)
    evidence_confidence: Mapped[str] = mapped_column(String(30), default="none")
    evidence_summary: Mapped[str] = mapped_column(Text, default="")
    explanation_json: Mapped[str] = mapped_column(Text, default="{}")
    job: Mapped[Job] = relationship(back_populates="evidence_adjustment_history")
