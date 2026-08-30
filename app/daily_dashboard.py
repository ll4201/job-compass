from typing import Any

from app.application_action import recommend_application_action
from app.career_path_match import load_candidate_profile
from app.models import Job
from app.job_policy import effective_action_type, effective_final_strategy, is_effectively_active
from app.resume_profile_match import load_resume_profiles, resume_profile_match


ACTION_TYPES = (
    "apply_now",
    "tailor_then_apply",
    "low_cost_apply",
    "clarify_then_decide",
)


def empty_daily_actions() -> dict[str, Any]:
    """Return a new, template-safe dashboard structure for every request."""
    return {
        "apply_now": [],
        "tailor_then_apply": [],
        "low_cost_apply": [],
        "clarify_then_decide_count": 0,
    }


def daily_action_summary(daily_actions: dict[str, Any]) -> dict[str, int]:
    """Expose stable counts independently from the dashboard item lists."""
    return {
        "apply_now": len(daily_actions.get("apply_now", [])),
        "tailor_then_apply": len(daily_actions.get("tailor_then_apply", [])),
        "low_cost_apply": len(daily_actions.get("low_cost_apply", [])),
        "clarify_then_decide": int(daily_actions.get("clarify_then_decide_count", 0)),
    }


def _job_data(job: Job) -> dict[str, Any]:
    return {column.name: getattr(job, column.name) for column in Job.__table__.columns}


def build_daily_action_dashboard(jobs: list[Job]) -> dict[str, Any]:
    """Build a request-only action view without mutating jobs or assessments."""
    if not jobs:
        return empty_daily_actions()
    candidate_profile = load_candidate_profile()
    resume_profiles = load_resume_profiles()
    groups: dict[str, list[dict[str, Any]]] = {value: [] for value in ACTION_TYPES}
    for job in jobs:
        if not is_effectively_active(job):
            continue
        assessment = job.assessment
        safe_strategy = effective_final_strategy(job)
        safe_action = effective_action_type(job)
        if assessment is None or safe_action not in groups:
            continue
        required = (
            assessment.final_strategy,
            assessment.career_match_level,
            assessment.career_match_score,
            assessment.employer_acceptance_level,
            assessment.employer_acceptance_score,
            assessment.personal_preference_level,
            assessment.personal_preference_score,
        )
        if any(value is None for value in required):
            continue
        action = recommend_application_action(
            final_strategy=safe_strategy,
            career_match_level=str(assessment.career_match_level),
            career_match_score=float(assessment.career_match_score),
            employer_acceptance_level=str(assessment.employer_acceptance_level),
            employer_acceptance_score=float(assessment.employer_acceptance_score),
            personal_preference_level=str(assessment.personal_preference_level),
            personal_preference_score=float(assessment.personal_preference_score),
            profile=candidate_profile,
        )
        resume = resume_profile_match(
            _job_data(job),
            safe_strategy,
            safe_action,
            resume_profiles,
        )
        profile_values = resume_profiles["profiles"].get(
            resume.recommended_resume_profile, {}
        )
        groups[safe_action].append(
            {
                "job": job,
                "action_priority": action.action_priority,
                "recommended_resume_profile": resume.recommended_resume_profile,
                "recommended_resume_label": profile_values.get(
                    "label", resume.recommended_resume_profile
                ),
                "resume_focus": resume.resume_focus,
                "next_steps": action.next_steps,
                "action_reason": action.action_reason,
            }
        )
    dashboard = empty_daily_actions()
    dashboard.update(
        {
            "apply_now": groups["apply_now"],
            "tailor_then_apply": groups["tailor_then_apply"],
            "low_cost_apply": groups["low_cost_apply"],
            "clarify_then_decide_count": len(groups["clarify_then_decide"]),
        }
    )
    return dashboard
