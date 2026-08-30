from typing import Any

from sqlalchemy.sql import Select

from app.models import Job
from app.qualification import detect_seniority, has_early_career_title


ACTIVE_AVAILABILITY = "active"


def is_effectively_active(job: Job | Any) -> bool:
    """Return whether a job is eligible for current recommendations and ranking."""
    return bool(
        not bool(getattr(job, "is_sample", False))
        and getattr(job, "availability_status", None) == ACTIVE_AVAILABILITY
        and bool(getattr(job, "is_active", False))
    )


def apply_effective_job_filters(
    statement: Select,
    *,
    include_inactive: bool = False,
    include_test: bool = False,
) -> Select:
    """Apply the shared P0 selection policy to a SQLAlchemy statement."""
    if not include_test:
        statement = statement.where(Job.is_sample.is_(False))
    if not include_inactive:
        statement = statement.where(
            Job.availability_status == ACTIVE_AVAILABILITY,
            Job.is_active.is_(True),
        )
    return statement


def effective_final_strategy(job: Job) -> str:
    """Expose a safe display strategy without changing the stored assessment."""
    if job.is_sample:
        return "skip"
    if job.availability_status == "closed":
        return "skip"
    if job.availability_status == "possibly_closed" or not job.is_active:
        return "hold"
    if job.availability_status != ACTIVE_AVAILABILITY:
        return "skip"
    if job.assessment is None:
        return "unassessed"
    stored = job.assessment.final_strategy or "unassessed"
    if job.location_conflict or job.workplace_status in {
        "needs_confirmation",
        "multiple_locations",
        "optional_unconfirmed",
    }:
        return "hold"
    if job.workplace_status == "non_shenzhen":
        return "skip"
    if job.assessment.hard_filter_status == "excluded" or job.assessment.risk_level == "critical":
        return "skip"
    if job.assessment.hard_filter_status == "pending_confirmation":
        return "hold"
    text = " ".join(
        value
        for value in (
            job.description,
            job.responsibilities,
            job.requirements,
            job.experience_raw,
        )
        if value
    )
    qualification = detect_seniority(
        job.job_title,
        text,
        job_type=job.job_type,
        role_direction=job.role_direction,
        experience_min=job.experience_min,
    )
    if qualification.seniority_level in {
        "senior",
        "lead",
        "senior_manager",
        "director",
        "head",
        "executive",
    }:
        return "skip"
    years = qualification.experience_years
    if years is not None and years >= 5:
        return "stretch_apply" if has_early_career_title(job.job_title) else "skip"
    if years is not None and years > 2 and stored in {"priority_apply", "targeted_apply"}:
        return "stretch_apply"
    if years is not None and years > 1 and stored == "priority_apply":
        return "targeted_apply"
    return stored


def effective_action_type(job: Job) -> str:
    """Expose a safe action for historical views without altering stored values."""
    if job.is_sample or job.availability_status == "closed":
        return "archive_no_action"
    if not is_effectively_active(job):
        return "clarify_then_decide"
    strategy = effective_final_strategy(job)
    safe_actions = {
        "priority_apply": "apply_now",
        "targeted_apply": "tailor_then_apply",
        "stretch_apply": "low_cost_apply",
        "low_cost_try": "low_cost_apply",
        "hold": "clarify_then_decide",
        "skip": "archive_no_action",
    }
    return safe_actions.get(strategy, "archive_no_action")
