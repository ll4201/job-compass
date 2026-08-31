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
    "source",
    "source_count",
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
    "is_sample",
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
    "is_sample",
    "needs_confirmation",
    "is_outdated",
}

ACTION_LABELS = {
    "apply_now": "立即定制并投递",
    "tailor_then_apply": "定制简历后投递",
    "low_cost_apply": "低成本快速投递",
    "clarify_then_decide": "核实关键信息后决定",
    "archive_no_action": "归档，暂不行动",
}

RESUME_PROFILES = {
    "technical_product": {
        "label": "技术产品 / 项目版",
        "title_keywords": [
            "product",
            "solution",
            "technical support",
            "project coordinator",
            "产品",
            "解决方案",
            "技术支持",
            "项目",
        ],
        "evidence_keywords": [
            "engineering",
            "technical",
            "product",
            "project",
            "cross-functional",
            "工程",
            "技术",
            "产品",
            "项目",
            "跨部门",
        ],
        "emphasis": ["工程技术基础", "项目实践", "数据分析", "跨团队沟通"],
    },
    "overseas_business": {
        "label": "海外业务 / 市场版",
        "title_keywords": [
            "overseas",
            "international",
            "customer success",
            "marketing",
            "海外",
            "国际",
            "客户成功",
            "市场",
        ],
        "evidence_keywords": [
            "global",
            "english",
            "market",
            "customer",
            "data analysis",
            "全球",
            "英语",
            "市场",
            "客户",
            "数据分析",
        ],
        "emphasis": ["英语沟通", "跨文化协作", "海外市场理解", "数据分析"],
    },
    "general_entry": {
        "label": "通用应届 / 管培版",
        "title_keywords": ["graduate", "trainee", "entry level", "管培", "校招", "应届"],
        "evidence_keywords": ["learning", "leadership", "communication", "学习能力", "沟通", "团队协作"],
        "emphasis": ["学习能力", "项目实践", "团队协作", "沟通能力"],
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
    if job["is_sample"] or job["availability_status"] == "closed":
        return "skip"
    if job["availability_status"] == "possibly_closed" or not job["is_active"]:
        return "hold"
    if job["availability_status"] != "active":
        return "skip"
    if job["location_conflict"] or job["workplace_status"] in {
        "needs_confirmation",
        "multiple_locations",
        "optional_unconfirmed",
    }:
        return "hold"
    if job["workplace_status"] == "non_shenzhen":
        return "skip"
    if assessment["hard_filter_status"] == "excluded" or assessment["risk_level"] == "critical":
        return "skip"
    if assessment["hard_filter_status"] == "pending_confirmation":
        return "hold"
    return assessment["final_strategy"] or "unassessed"


def effective_action(job: dict[str, Any], strategy: str) -> str:
    if job["is_sample"] or job["availability_status"] == "closed":
        return "archive_no_action"
    if job["availability_status"] != "active" or not job["is_active"]:
        return "clarify_then_decide"
    return {
        "priority_apply": "apply_now",
        "targeted_apply": "tailor_then_apply",
        "stretch_apply": "low_cost_apply",
        "low_cost_try": "low_cost_apply",
        "hold": "clarify_then_decide",
        "skip": "archive_no_action",
    }.get(strategy, "archive_no_action")


def resume_match(job: dict[str, Any], strategy: str, action_type: str) -> dict[str, str]:
    if action_type == "archive_no_action" or strategy == "skip":
        return {
            "profile": "not_applicable",
            "label": "无需准备简历",
            "focus": "无需准备简历",
        }
    title = str(job.get("job_title") or "").casefold()
    combined = " ".join(
        str(job.get(key) or "")
        for key in ("job_title", "role_direction", "description", "responsibilities", "requirements")
    ).casefold()
    candidates: list[tuple[float, int, str]] = []
    for order, (name, values) in enumerate(RESUME_PROFILES.items()):
        title_hits = sum(str(keyword).casefold() in title for keyword in values["title_keywords"])
        evidence_hits = sum(
            str(keyword).casefold() in combined for keyword in values["evidence_keywords"]
        )
        match_score = 20 + min(50, title_hits * 30) + min(25, evidence_hits * 5)
        if strategy == "hold":
            match_score -= 5
        candidates.append((float(match_score), -order, name))
    best_score, _order, profile_name = max(candidates)
    if best_score <= 35:
        profile_name = "general_entry"
    profile = RESUME_PROFILES[profile_name]
    return {
        "profile": profile_name,
        "label": str(profile["label"]),
        "focus": "；".join(str(value) for value in profile["emphasis"]),
    }


def build_action(job: dict[str, Any], assessment: dict[str, Any], strategy: str) -> dict[str, Any]:
    action_type = effective_action(job, strategy)
    if strategy == "priority_apply":
        priority = "urgent"
        next_steps = [
            "确认岗位仍在招聘并复核硬性要求",
            "按JD定制简历首屏、项目经历和关键词",
            "准备简短求职动机并完成投递",
            "将Candidate Status更新为applied",
        ]
    elif strategy == "targeted_apply":
        priority = "high"
        acceptance = float(assessment["employer_acceptance_score"] or 0)
        next_steps = [
            "重点补强招聘方可能质疑的直接经验与岗位关键词"
            if acceptance < 60
            else "用最相关项目证明能力可以迁移到岗位",
            "选择2至3段最相关项目并改写为成果导向表述",
            "完成一次针对性简历检查后投递",
            "将Candidate Status更新为applied",
        ]
    elif strategy in {"low_cost_try", "stretch_apply"}:
        priority = "medium"
        next_steps = [
            "使用最接近岗位方向的现有简历版本",
            "明确呈现可迁移能力并诚实处理经验差距"
            if strategy == "stretch_apply"
            else "只调整标题、摘要和核心关键词",
            "控制准备时间并投递验证经验门槛"
            if strategy == "stretch_apply"
            else "控制准备时间并直接投递验证市场反馈",
            "记录是否获得回复",
        ]
    elif strategy == "hold":
        career_match = float(assessment["career_match_score"] or 0)
        preference = float(assessment["personal_preference_score"] or 0)
        priority = "high" if career_match >= 65 and preference >= 65 else "medium"
        if assessment["career_match_level"] == "conflicting" or career_match < 35:
            clarification = "先确认地点、资历或个人硬限制是否真实冲突"
        elif assessment["employer_acceptance_level"] in {"low", "uncertain"} or float(
            assessment["employer_acceptance_score"] or 0
        ) < 45:
            clarification = "先核实经验年限、学历和应届生资格是否为硬性要求"
        else:
            clarification = "先补充工作地点、职责范围、招聘状态和关键待遇信息"
        next_steps = [
            clarification,
            "优先通过JD原页、招聘方或面试沟通获取确认",
            "确认后重新选择投递或归档，不重写基础评分",
        ]
    else:
        priority = "none"
        next_steps = ["记录跳过原因", "不投入简历定制时间", "仅在岗位条件发生实质变化时重新评估"]
    resume = resume_match(job, strategy, action_type)
    return {
        "type": action_type,
        "label": ACTION_LABELS[action_type],
        "priority": priority,
        "next_steps": next_steps,
        "recommended_resume_profile": resume["profile"],
        "recommended_resume_label": resume["label"],
        "resume_focus": resume["focus"],
    }


def collection_summary(connection: sqlite3.Connection) -> dict[str, Any] | None:
    run = connection.execute(
        """
        SELECT collection_runs.*, job_source_configs.source_name
        FROM collection_runs
        LEFT JOIN job_source_configs ON job_source_configs.source_id = collection_runs.source_id
        ORDER BY collection_runs.started_at DESC
        LIMIT 1
        """
    ).fetchone()
    if run is None:
        return None
    recommendations = dict(
        connection.execute(
            """
            SELECT job_assessments.application_recommendation, COUNT(*) AS total
            FROM raw_collected_jobs
            JOIN job_assessments ON job_assessments.job_id = raw_collected_jobs.imported_job_id
            WHERE raw_collected_jobs.collection_run_id = ?
            GROUP BY job_assessments.application_recommendation
            """,
            (run["id"],),
        ).fetchall()
    )
    return {
        "source_name": run["source_name"] or run["source_id"] or "未知来源",
        "status": run["status"],
        "dry_run": bool(run["dry_run"]),
        "new_count": run["imported_count"],
        "priority_apply": recommendations.get("priority_apply", 0),
        "apply": recommendations.get("apply", 0),
        "try": recommendations.get("try", 0),
        "hold": recommendations.get("hold_for_info", 0),
        "filtered": run["filtered_count"],
        "failed_sources": 1 if run["status"] == "failed" else 0,
    }


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
        action = build_action(job, assessment, strategy)

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
        source_ids = [
            item["source_id"]
            for item in connection.execute(
                "SELECT source_id FROM job_sources WHERE job_id = ? ORDER BY id",
                (job["id"],),
            )
            if item["source_id"]
        ]

        jobs.append(
            {
                **job,
                "assessment": assessment,
                "effective_strategy": strategy,
                "action": action,
                "assessment_history": history,
                "evidence": evidence,
                "source_ids": source_ids,
                "candidate_status": workflow["status"] if workflow else "new",
            }
        )

    snapshot = {
        "schema_version": 1,
        "description": "Public Job Compass portfolio demo snapshot",
        "sources": [
            dict(item)
            for item in connection.execute(
                "SELECT source_id, source_name FROM job_source_configs ORDER BY source_name"
            )
        ],
        "collection_summary": collection_summary(connection),
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
