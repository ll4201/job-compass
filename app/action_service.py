from typing import Any

from app.application_action import ApplicationAction, recommend_application_action
from app.career_path_match import load_candidate_profile
from app.models import JobAssessment


def reassess_application_action(
    assessment: JobAssessment, profile: dict[str, Any] | None = None
) -> ApplicationAction:
    """Persist only action identity; never recalculate V3 or personal strategy fields."""
    profile = profile or load_candidate_profile()
    required = {
        "final_strategy": assessment.final_strategy,
        "career_match_level": assessment.career_match_level,
        "career_match_score": assessment.career_match_score,
        "employer_acceptance_level": assessment.employer_acceptance_level,
        "employer_acceptance_score": assessment.employer_acceptance_score,
        "personal_preference_level": assessment.personal_preference_level,
        "personal_preference_score": assessment.personal_preference_score,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError(f"assessment 缺少正式个人策略字段：{', '.join(missing)}")
    action = recommend_application_action(
        final_strategy=str(assessment.final_strategy),
        career_match_level=str(assessment.career_match_level),
        career_match_score=float(assessment.career_match_score),
        employer_acceptance_level=str(assessment.employer_acceptance_level),
        employer_acceptance_score=float(assessment.employer_acceptance_score),
        personal_preference_level=str(assessment.personal_preference_level),
        personal_preference_score=float(assessment.personal_preference_score),
        profile=profile,
    )
    assessment.action_type = action.action_type
    assessment.action_priority = action.action_priority
    assessment.profile_version = str(profile["profile_version"])
    return action
