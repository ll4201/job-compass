from sqlalchemy.orm import Session

from app.models import (
    ApplicationFeedback,
    CandidateWorkflow,
    CandidateWorkflowHistory,
    Job,
)

WORKFLOW_STATUSES = (
    "new",
    "reviewing",
    "saved",
    "preparing",
    "applied",
    "assessment",
    "interview_1",
    "interview_2",
    "offer",
    "rejected",
    "withdrawn",
)

NOT_APPLIED_REASONS = (
    "experience_gap",
    "degree_requirement",
    "career_direction",
    "salary_issue",
    "location_issue",
    "company_not_interested",
    "other",
)

INTERVIEW_RESULTS = ("no_response", "rejected_cv", "interview_failed", "offer")


def workflow_status(job: Job) -> str:
    return job.candidate_workflow.status if job.candidate_workflow else "new"


def update_workflow_status(db: Session, job: Job, status: str) -> CandidateWorkflow:
    if status not in WORKFLOW_STATUSES:
        raise ValueError("无效的 Candidate Workflow 状态")
    workflow = job.candidate_workflow
    previous = workflow.status if workflow else "new"
    if workflow is None:
        workflow = CandidateWorkflow(job=job, status="new")
        db.add(workflow)
    if previous != status:
        db.add(
            CandidateWorkflowHistory(
                job=job,
                from_status=previous,
                to_status=status,
            )
        )
        workflow.status = status
    return workflow


def save_application_feedback(
    db: Session,
    job: Job,
    *,
    applied: bool | None,
    not_applied_reason: str | None,
    interview_result: str | None,
    notes: str | None,
) -> ApplicationFeedback:
    if not_applied_reason and not_applied_reason not in NOT_APPLIED_REASONS:
        raise ValueError("无效的未投递原因")
    if interview_result and interview_result not in INTERVIEW_RESULTS:
        raise ValueError("无效的面试结果")
    if applied is True:
        not_applied_reason = None
    feedback = job.application_feedback
    if feedback is None:
        feedback = ApplicationFeedback(job=job)
        db.add(feedback)
    feedback.applied = applied
    feedback.not_applied_reason = not_applied_reason
    feedback.interview_result = interview_result
    feedback.notes = notes.strip() if notes and notes.strip() else None
    return feedback
