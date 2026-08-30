from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Job


APPLICATION_STAGES = {"applied", "assessment", "interview_1", "interview_2", "offer", "rejected"}
INTERVIEW_STAGES = {"interview_1", "interview_2", "offer"}
INTERVIEW_OUTCOMES = {"interview_failed", "offer"}

COMPANY_TYPE_LABELS = {
    "mature_large_company": "成熟大型企业",
    "multinational_company": "跨国企业",
    "growth_company": "成长型企业",
    "startup": "初创企业",
    "unknown": "企业类型待确认",
}

FEEDBACK_LABELS = {
    "no_response": "暂无回复",
    "rejected_cv": "简历未通过",
    "interview_failed": "面试未通过",
    "offer": "Offer",
    "pending": "结果未记录",
}


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _reached_stages(job: Job) -> set[str]:
    stages = {job.candidate_workflow.status} if job.candidate_workflow else set()
    stages.update(item.to_status for item in job.workflow_history)
    return stages


def _job_outcome(job: Job) -> dict[str, Any]:
    feedback = job.application_feedback
    stages = _reached_stages(job)
    result = feedback.interview_result if feedback else None
    applied = bool(
        (feedback and feedback.applied is True)
        or stages.intersection(APPLICATION_STAGES)
        or result
    )
    interviewed = bool(stages.intersection(INTERVIEW_STAGES) or result in INTERVIEW_OUTCOMES)
    offered = bool("offer" in stages or result == "offer")
    return {
        "applied": applied,
        "interviewed": interviewed,
        "offered": offered,
        "feedback_result": result if result in FEEDBACK_LABELS else None,
    }


def _empty_group(key: str, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "applications": 0,
        "interviews": 0,
        "offers": 0,
        "no_response": 0,
        "rejected_cv": 0,
        "interview_failed": 0,
        "pending": 0,
    }


def _finalize_group(group: dict[str, Any]) -> dict[str, Any]:
    applications = group["applications"]
    group["interview_rate"] = _rate(group["interviews"], applications)
    group["offer_rate"] = _rate(group["offers"], applications)
    return group


def build_application_outcomes(db: Session) -> dict[str, Any]:
    """Build read-only application outcome analytics from workflow and feedback data."""
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.is_sample.is_(False))
            .options(
                joinedload(Job.assessment),
                joinedload(Job.candidate_workflow),
                joinedload(Job.workflow_history),
                joinedload(Job.application_feedback),
            )
            .order_by(Job.id)
        ).unique()
    )

    role_groups: dict[str, dict[str, Any]] = defaultdict(dict)
    company_groups: dict[str, dict[str, Any]] = defaultdict(dict)
    result_counts = {key: 0 for key in FEEDBACK_LABELS}
    application_count = interview_count = offer_count = 0
    not_applied_count = 0

    for job in jobs:
        outcome = _job_outcome(job)
        feedback = job.application_feedback
        if feedback and feedback.applied is False and not outcome["applied"]:
            not_applied_count += 1
        if not outcome["applied"]:
            continue

        application_count += 1
        interview_count += int(outcome["interviewed"])
        offer_count += int(outcome["offered"])
        result_key = outcome["feedback_result"] or "pending"
        result_counts[result_key] += 1

        role_key = (job.role_direction or "unknown").strip() or "unknown"
        if not role_groups[role_key]:
            role_groups[role_key] = _empty_group(
                role_key, "岗位方向待确认" if role_key == "unknown" else role_key
            )

        company_key = (
            (job.assessment.company_type if job.assessment else None) or "unknown"
        ).strip()
        if not company_groups[company_key]:
            company_groups[company_key] = _empty_group(
                company_key, COMPANY_TYPE_LABELS.get(company_key, company_key)
            )

        for group in (role_groups[role_key], company_groups[company_key]):
            group["applications"] += 1
            group["interviews"] += int(outcome["interviewed"])
            group["offers"] += int(outcome["offered"])
            if result_key != "offer":
                group[result_key] += 1

    role_rows = sorted(
        (_finalize_group(group) for group in role_groups.values()),
        key=lambda item: (-item["applications"], item["label"]),
    )
    company_rows = sorted(
        (_finalize_group(group) for group in company_groups.values()),
        key=lambda item: (-item["applications"], item["label"]),
    )
    feedback_rows = [
        {"key": key, "label": FEEDBACK_LABELS[key], "count": result_counts[key]}
        for key in FEEDBACK_LABELS
    ]

    return {
        "total_jobs": len(jobs),
        "application_count": application_count,
        "interview_count": interview_count,
        "offer_count": offer_count,
        "not_applied_count": not_applied_count,
        "interview_rate": _rate(interview_count, application_count),
        "offer_rate": _rate(offer_count, application_count),
        "role_rows": role_rows,
        "company_rows": company_rows,
        "feedback_rows": feedback_rows,
    }
