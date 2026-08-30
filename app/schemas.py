from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    source: str = "manual"
    source_job_id: str | None = None
    source_url: str | None = None
    company_name: str = Field(min_length=1)
    job_title: str = Field(min_length=1)
    job_type: str = "full_time"
    employment_type: str | None = None
    recruitment_type: str | None = None
    location_raw: str = ""
    title_location: str | None = None
    structured_location: str | None = None
    office_location: str | None = None
    jd_location: str | None = None
    normalized_location: str | None = None
    location_conflict: bool = False
    location_conflict_reason: str | None = None
    salary_raw: str | None = None
    experience_raw: str | None = None
    education_requirement: str | None = None
    major_requirement: str | None = None
    language_requirement: str | None = None
    description: str = ""
    responsibilities: str | None = None
    requirements: str | None = None
    benefits_raw: str | None = None
    published_at: datetime | None = None
    company_quality: str | None = None
    is_sample: bool = False


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_name: str
    job_title: str
    city: str | None
    workplace_status: str
    application_status: str
    is_sample: bool
    created_at: datetime


class EvidenceCreate(BaseModel):
    company_name: str = Field(min_length=1)
    job_id: int | None = None
    source_platform: str = "other"
    source_url: str | None = None
    source_title: str | None = None
    source_author_type: str | None = None
    published_at: datetime | None = None
    city: str | None = None
    department: str | None = None
    role_name: str | None = None
    employment_type: str | None = None
    evidence_text: str = Field(min_length=1)
    evidence_category: str = "other"
    evidence_value: str | None = None
    sentiment: str = "neutral"
    source_confidence: str | None = None
    verification_status: str = "unverified"
    user_notes: str | None = None


class EvidenceApiSubmission(BaseModel):
    source_platform: str = "other"
    source_url: str | None = None
    source_title: str | None = None
    published_at: datetime | None = None
    page_text: str = Field(min_length=1)
    company_name: str | None = None
    job_id: int | None = None
    city: str | None = None
    department: str | None = None
    role_name: str | None = None
    employment_type: str | None = None
    evidence_category: str | None = None
    evidence_value: str | None = None
    sentiment: str | None = None
    verification_status: str | None = None
    source_author_type: str | None = None
    user_notes: str | None = None
    save_confirmed: bool = False


class RawCollectedJob(BaseModel):
    source_name: str
    source_type: str
    source_job_id: str | None = None
    source_url: str | None = None
    company_name: str
    job_title: str
    location_raw: str = ""
    job_type: str = "full_time"
    description_raw: str = ""
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict | list | str = Field(default_factory=dict)
    source_location_payload: dict | list | str | None = None
    source_confidence: str = "medium"
    department: str | None = None
    employment_type: str | None = None
