"""Export the existing public Demo database to a browser-safe static snapshot.

This is a one-time/maintenance tool only.  The generated site does not run
Python, SQLite, or this script in production.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "demo.db"
DEFAULT_OUTPUT = ROOT / "site" / "data" / "demo_jobs.json"

JOB_FIELDS = (
    "id",
    "company_name",
    "job_title",
    "role_direction",
    "job_type",
    "employment_type",
    "location_raw",
    "title_location",
    "structured_location",
    "office_location",
    "jd_location",
    "normalized_location",
    "location_conflict",
    "location_conflict_reason",
    "city",
    "district",
    "workplace_status",
    "salary_raw",
    "experience_raw",
    "education_requirement",
    "major_requirement",
    "language_requirement",
    "description",
    "responsibilities",
    "requirements",
    "benefits_raw",
    "working_schedule",
    "five_insurances_housing_fund",
    "paid_leave",
    "statutory_holiday_status",
    "overtime_risk",
    "internship_conversion",
    "travel_requirement",
    "published_at",
    "first_seen_at",
    "is_new",
    "freshness_status",
    "availability_status",
    "closure_reason",
    "is_active",
    "travel_level",
    "resume_output_potential",
    "conversion_level",
)

ASSESSMENT_FIELDS = (
    "hard_filter_status",
    "hard_filter_reasons",
    "role_match_score",
    "compensation_benefits_score",
    "entry_level_score",
    "english_overseas_score",
    "technical_project_score",
    "career_growth_score",
    "company_quality_score",
    "penalty_score",
    "total_score",
    "fit_score",
    "opportunity_score",
    "information_completeness",
    "risk_level",
    "application_recommendation",
    "seniority_level",
    "role_direction_match",
    "seniority_match",
    "experience_match",
    "career_match_score",
    "career_match_level",
    "career_value_score",
    "career_value_level",
    "eligibility_score",
    "direction_fit_score",
    "life_quality_score",
    "freshness_score",
    "compensation_score",
    "overall_priority_score",
    "support_role_type",
    "needs_confirmation",
    "resume_type",
    "job_age_days",
    "date_source",
    "employer_acceptance_score",
    "employer_acceptance_level",
    "personal_preference_score",
    "personal_preference_level",
    "final_strategy",
    "decision_reason",
    "action_type",
    "action_priority",
    "profile_version",
    "company_type",
    "opportunity_breakdown_json",
    "grade",
    "recommendation",
    "strengths",
    "risks",
    "missing_information",
    "interview_questions",
    "suggested_resume_track",
    "assessment_version",
    "travel_level",
    "travel_penalty",
    "explanation_json",
    "assessed_at",
)

HISTORY_FIELDS = (
    "assessment_version",
    "assessed_at",
    "total_score",
    "fit_score",
    "opportunity_score",
    "information_completeness",
    "risk_level",
    "application_recommendation",
    "career_match_score",
    "career_value_score",
    "eligibility_score",
    "direction_fit_score",
    "life_quality_score",
    "freshness_score",
    "compensation_score",
    "overall_priority_score",
    "employer_acceptance_score",
    "personal_preference_score",
    "final_strategy",
    "decision_reason",
    "grade",
)

EVIDENCE_FIELDS = (
    "source_platform",
    "source_title",
    "published_at",
    "city",
    "department",
    "role_name",
    "employment_type",
    "evidence_text",
    "evidence_category",
    "evidence_value",
    "sentiment",
    "source_confidence",
    "relevance_level",
    "verification_status",
    "is_outdated",
)

JSON_FIELDS = {
    "hard_filter_reasons",
    "opportunity_breakdown_json",
    "strengths",
    "risks",
    "missing_information",
    "interview_questions",
    "explanation_json",
}

BOOLEAN_FIELDS = {
    "location_conflict",
    "is_new",
    "is_active",
    "needs_confirmation",
    "is_outdated",
}

ACTION_COPY = {
    "priority_apply": {
        "type": "apply_now",
        "label": "立即定制并投递",
        "priority": "urgent",
        "next_steps": ["使用定制简历", "优先补强与岗位方向最相关的项目", "24 小时内完成投递"],
    },
    "targeted_apply": {
        "type": "tailor_then_apply",
        "label": "定制后投递",
        "priority": "high",
        "next_steps": ["针对岗位职责调整简历关键词", "突出可迁移能力与相关项目", "完成定制后投递"],
    },
    "low_cost_try": {
        "type": "low_cost_apply",
        "label": "低成本尝试",
        "priority": "medium",
        "next_steps": ["使用通用简历快速投递", "不投入过多定制时间", "通过反馈验证岗位方向"],
    },
    "hold": {
        "type": "clarify_then_decide",
        "label": "补充信息后决定",
        "priority": "medium",
        "next_steps": ["确认缺失的核心信息", "更新评估依据", "信息充分后再决定是否投递"],
    },
    "skip": {
        "type": "archive",
        "label": "归档 / 跳过",
        "priority": "none",
        "next_steps": ["保留决策依据", "不投入简历定制时间"],
    },
}


def parse_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def clean_value(name: str, value: Any) -> Any:
    if name in JSON_FIELDS:
        fallback: Any = {} if name.endswith("_json") else []
        return parse_json(value, fallback)
    if name in BOOLEAN_FIELDS and value is not None:
        return bool(value)
    return value


def select_fields(row: sqlite3.Row, fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: clean_value(name, row[name]) for name in fields}


def effective_strategy(job: dict[str, Any], assessment: dict[str, Any]) -> str:
    if not job["is_active"] or job["availability_status"] == "closed":
        return "skip"
    if job["workplace_status"] in {"non_shenzhen", "remote_outside_shenzhen"}:
        return "skip"
    if job["workplace_status"] in {"needs_confirmation", "unconfirmed"}:
        return "hold"
    if assessment["hard_filter_status"] == "excluded" or assessment["risk_level"] == "critical":
        return "skip"
    return assessment["final_strategy"] or "hold"


def export_snapshot(database: Path, output: Path) -> None:
    database_uri = f"file:{database.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row

    jobs: list[dict[str, Any]] = []
    for row in connection.execute(
        """
        SELECT jobs.*, job_assessments.*
        FROM jobs
        JOIN job_assessments ON job_assessments.job_id = jobs.id
        ORDER BY jobs.id
        """
    ):
        job = select_fields(row, JOB_FIELDS)
        assessment = select_fields(row, ASSESSMENT_FIELDS)
        strategy = effective_strategy(job, assessment)
        action = dict(ACTION_COPY[strategy])
        if assessment["suggested_resume_track"]:
            action["resume_track"] = assessment["suggested_resume_track"]

        history = [
            select_fields(item, HISTORY_FIELDS)
            for item in connection.execute(
                "SELECT * FROM assessment_history WHERE job_id = ? ORDER BY assessed_at DESC",
                (job["id"],),
            )
        ]
        evidence = [
            select_fields(item, EVIDENCE_FIELDS)
            for item in connection.execute(
                "SELECT * FROM external_evidence WHERE job_id = ? ORDER BY published_at DESC",
                (job["id"],),
            )
        ]
        workflow = connection.execute(
            "SELECT status FROM candidate_workflows WHERE job_id = ?",
            (job["id"],),
        ).fetchone()

        jobs.append(
            {
                **job,
                "assessment": assessment,
                "effective_strategy": strategy,
                "action": action,
                "assessment_history": history,
                "evidence": evidence,
                "candidate_status": workflow["status"] if workflow else "new",
            }
        )

    snapshot = {
        "schema_version": 1,
        "description": "Public Job Compass portfolio demo snapshot",
        "jobs": jobs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Exported {len(jobs)} public sample jobs to {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    export_snapshot(args.database, args.output)


if __name__ == "__main__":
    main()
