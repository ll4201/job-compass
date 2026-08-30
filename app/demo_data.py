"""Synthetic, privacy-safe seed data for the public portfolio build."""

import hashlib
import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AssessmentHistory,
    CandidateWorkflow,
    CollectionRun,
    ExternalEvidence,
    Job,
    JobAssessment,
    JobSourceConfig,
    RawCollectedJobRecord,
    utcnow,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _explanation(*, evidence: str, missing: list[str], internship: bool = False) -> str:
    states = {
        "salary": "not_disclosed" if "薪资" in missing else "confirmed",
        "working_schedule": "not_disclosed" if "工作时间" in missing else "confirmed",
        "five_insurances": "not_disclosed" if "五险一金" in missing else "confirmed",
        "location": "not_disclosed" if "办公地点" in missing else "confirmed",
    }
    return _json(
        {
            "framework": "internship" if internship else "full_time",
            "information_states": states,
            "opportunity_breakdown": {
                "career_growth": {
                    "label": "成长空间",
                    "score": 17,
                    "max_score": 20,
                    "positive_evidence": [evidence],
                    "negative_evidence": [],
                },
                "role_scope": {
                    "label": "职责质量",
                    "score": 16,
                    "max_score": 20,
                    "positive_evidence": ["参与真实业务项目并与多团队协作"],
                    "negative_evidence": [],
                },
                "employment_quality": {
                    "label": "工作质量",
                    "score": 12 if missing else 17,
                    "max_score": 20,
                    "positive_evidence": [] if missing else ["JD 明确披露基本制度"],
                    "negative_evidence": [],
                },
            },
            "dimensions": [
                {
                    "name": "方向匹配",
                    "score": 24,
                    "max_score": 30,
                    "items": [{"label": "目标方向关键词", "points": 8, "quote": evidence}],
                },
                {
                    "name": "职业价值",
                    "score": 20,
                    "max_score": 25,
                    "items": [
                        {
                            "label": "跨团队项目责任",
                            "points": 6,
                            "quote": "与产品、工程和市场团队协作推进项目",
                        }
                    ],
                },
            ],
            "penalty_details": [],
            "final_calculation": {"formula": "各维度加权得分 − 明确风险项"},
            "application_strategy": {
                "career_match": {"career_match_reason": "方向与可迁移能力基本一致。"},
                "career_value": {"career_value_reason": "职责包含真实项目与跨团队协作。"},
                "employer_acceptance": {"employer_acceptance_reason": "仍需招聘方验证项目经验。"},
                "personal_preference": {"personal_preference_reason": "符合公开 Demo 候选人画像。"},
            },
        }
    )


def _job(spec: dict[str, object]) -> Job:
    title = str(spec["title"])
    company = str(spec["company"])
    missing = list(spec.get("missing", []))
    strategy = str(spec["strategy"])
    active = bool(spec.get("active", True))
    location = str(spec.get("location", "深圳"))
    description = str(spec["description"])
    job = Job(
        source="demo",
        source_job_id=f"demo-{spec['key']}",
        source_url=None,
        company_name=company,
        job_title=title,
        role_direction=str(spec.get("role", "产品")),
        job_type=str(spec.get("job_type", "full_time")),
        employment_type="实习" if spec.get("job_type") == "internship" else "全职",
        location_raw=location,
        structured_location=location,
        jd_location=location,
        normalized_location=location,
        city=location,
        workplace_status=str(spec.get("workplace_status", "confirmed_shenzhen")),
        salary_raw=None if "薪资" in missing else str(spec.get("salary", "15k–22k · 13薪（示例）")),
        experience_raw=str(spec.get("experience", "0–2年 / 优秀应届生可申请")),
        education_requirement="本科及以上",
        description=description,
        responsibilities="参与需求分析、项目推进、数据复盘和跨团队协作。",
        requirements="具备结构化分析、沟通协作和快速学习能力。",
        benefits_raw=None if "五险一金" in missing else "双休、五险一金、带薪年假（示例）",
        working_schedule="not_disclosed" if "工作时间" in missing else "confirmed_yes",
        five_insurances_housing_fund=(
            "not_disclosed" if "五险一金" in missing else "confirmed_yes"
        ),
        paid_leave="not_disclosed" if missing else "confirmed_yes",
        statutory_holiday_status="not_disclosed" if missing else "confirmed_yes",
        overtime_risk="not_disclosed",
        internship_conversion=(
            str(spec.get("conversion", "not_disclosed"))
            if spec.get("job_type") == "internship"
            else "not_applicable"
        ),
        published_at=utcnow() - timedelta(days=int(spec.get("age", 4))),
        first_seen_at=utcnow() - timedelta(days=int(spec.get("age", 4))),
        last_seen_at=utcnow(),
        last_verified_at=utcnow(),
        freshness_status="new" if int(spec.get("age", 4)) <= 7 else "existing",
        availability_status="active" if active else "closed",
        closure_reason=None if active else "示例岗位已下线，用于展示失效岗位管理",
        is_active=active,
        is_sample=False,
        is_new=bool(spec.get("new", True)),
        travel_level="none",
        resume_output_potential="high" if strategy in {"priority_apply", "targeted_apply"} else "medium",
        conversion_level=str(spec.get("conversion_level", "not_applicable")),
        content_hash=hashlib.sha256(f"{company}|{title}|{description}".encode()).hexdigest(),
        application_status="待评估",
    )
    fit = float(spec["fit"])
    opportunity = float(spec["opportunity"])
    completeness = float(spec["completeness"])
    grade = str(spec["grade"])
    recommendation = str(spec["recommendation"])
    risk = str(spec.get("risk", "low"))
    evidence = str(spec["evidence"])
    hard_filter = str(spec.get("hard_filter", "passed"))
    action_by_strategy = {
        "priority_apply": "apply_now",
        "targeted_apply": "tailor_then_apply",
        "stretch_apply": "low_cost_apply",
        "low_cost_try": "low_cost_apply",
        "hold": "clarify_then_decide",
        "skip": "archive_no_action",
    }
    job.assessment = JobAssessment(
        hard_filter_status=hard_filter,
        hard_filter_reasons=_json(list(spec.get("hard_reasons", []))),
        total_score=float(spec.get("total", fit)),
        fit_score=fit,
        opportunity_score=opportunity,
        information_completeness=completeness,
        risk_level=risk,
        application_recommendation=recommendation,
        seniority_level="internship" if spec.get("job_type") == "internship" else "entry",
        role_direction_match="high" if fit >= 75 else "medium" if fit >= 50 else "low",
        seniority_match="high" if fit >= 65 else "medium",
        experience_match=str(spec.get("experience_match", "high")),
        career_match_score=fit,
        career_match_level="highly_aligned" if fit >= 85 else "aligned" if fit >= 65 else "adjacent",
        career_value_score=float(spec.get("career_value", opportunity)),
        career_value_level="high" if opportunity >= 75 else "medium",
        eligibility_score=float(spec.get("eligibility", fit)),
        direction_fit_score=fit,
        life_quality_score=None if "工作时间" in missing else float(spec.get("life_quality", 78)),
        freshness_score=88 if int(spec.get("age", 4)) <= 7 else 55,
        compensation_score=None if "薪资" in missing else float(spec.get("compensation", 76)),
        overall_priority_score=float(spec.get("priority", (fit + opportunity) / 2)),
        support_role_type="not_support_role",
        needs_confirmation=bool(missing) or strategy == "hold",
        resume_type="technical_product",
        job_age_days=int(spec.get("age", 4)),
        date_source="published_at",
        employer_acceptance_score=float(spec.get("acceptance", 72)),
        employer_acceptance_level="high" if float(spec.get("acceptance", 72)) >= 70 else "uncertain",
        personal_preference_score=float(spec.get("preference", fit)),
        personal_preference_level="high_alignment" if fit >= 80 else "medium_alignment",
        final_strategy=strategy,
        decision_reason=str(spec["reason"]),
        action_type=action_by_strategy[strategy],
        action_priority="urgent" if strategy == "priority_apply" else "high" if strategy == "targeted_apply" else "medium",
        profile_version="public-demo-profile-v1",
        company_type="established",
        opportunity_breakdown_json=_json({}),
        grade=grade,
        recommendation=str(spec["reason"]),
        strengths=_json(["方向相关", "具备可迁移能力"]),
        risks=_json(list(spec.get("risks", []))),
        missing_information=_json(missing),
        interview_questions=_json([f"请确认：{item}" for item in missing]),
        suggested_resume_track="技术产品 / 项目版",
        assessment_version="public-demo-v1",
        travel_level="none",
        explanation_json=_explanation(
            evidence=evidence,
            missing=missing,
            internship=spec.get("job_type") == "internship",
        ),
    )
    return job


DEMO_SPECS: list[dict[str, object]] = [
    {
        "key": "apm",
        "company": "星图科技（示例）",
        "title": "助理产品经理",
        "role": "产品",
        "description": "负责用户需求分析、产品方案设计、数据复盘，并与工程和市场团队推进产品迭代。本岗位为完全虚构的 Demo JD。",
        "evidence": "负责用户需求分析并推动产品迭代",
        "strategy": "priority_apply",
        "recommendation": "priority_apply",
        "reason": "方向、资历与职责质量均匹配，建议优先定制并投递。",
        "fit": 91,
        "opportunity": 88,
        "completeness": 92,
        "grade": "A",
    },
    {
        "key": "project",
        "company": "远帆智能（示例）",
        "title": "国际项目协调专员",
        "role": "项目",
        "description": "协调海外客户需求、项目排期和交付风险，推动跨部门问题闭环。本岗位为完全虚构的 Demo JD。",
        "evidence": "协调海外客户需求、项目排期和交付风险",
        "strategy": "targeted_apply",
        "recommendation": "apply",
        "reason": "项目方向匹配，但需要在简历中强化交付与跨文化协作证据。",
        "fit": 82,
        "opportunity": 80,
        "completeness": 86,
        "grade": "A",
        "acceptance": 62,
    },
    {
        "key": "customer-success",
        "company": "云阶软件（示例）",
        "title": "客户成功专员",
        "role": "客户成功",
        "description": "服务企业客户，分析使用数据并协同产品团队解决 adoption 问题。本岗位为完全虚构的 Demo JD。",
        "evidence": "分析客户使用数据并协同产品团队解决问题",
        "strategy": "low_cost_try",
        "recommendation": "try",
        "reason": "属于相邻方向，可控制准备成本尝试并用反馈验证匹配度。",
        "fit": 67,
        "opportunity": 71,
        "completeness": 83,
        "grade": "B",
    },
    {
        "key": "solution",
        "company": "澄芯电子（示例）",
        "title": "解决方案助理",
        "role": "技术支持",
        "description": "协助客户需求澄清、方案文档和技术沟通；办公地点与出差频率需后续确认。本岗位为完全虚构的 Demo JD。",
        "evidence": "协助客户需求澄清、方案文档和技术沟通",
        "strategy": "hold",
        "recommendation": "hold_for_info",
        "reason": "方向有吸引力，但地点与工作节奏信息不足，先人工确认。",
        "fit": 79,
        "opportunity": 78,
        "completeness": 48,
        "grade": "B",
        "missing": ["办公地点", "工作时间"],
        "workplace_status": "needs_confirmation",
        "risk": "medium",
    },
    {
        "key": "operations",
        "company": "青屿品牌（示例）",
        "title": "海外产品运营",
        "role": "海外运营",
        "description": "JD 仅说明协助海外产品运营和数据整理，关键职责、薪资及制度未披露。本岗位为完全虚构的 Demo JD。",
        "evidence": "协助海外产品运营和数据整理",
        "strategy": "hold",
        "recommendation": "hold_for_info",
        "reason": "缺少影响投递决策的核心信息；缺失不作为负面证据，进入人工确认。",
        "fit": 70,
        "opportunity": 64,
        "completeness": 32,
        "grade": "B",
        "missing": ["薪资", "工作时间", "五险一金", "职责边界"],
        "risk": "unknown",
    },
    {
        "key": "non-shenzhen",
        "company": "北辰数据（示例）",
        "title": "产品运营专员（上海）",
        "role": "产品运营",
        "location": "上海",
        "workplace_status": "non_shenzhen",
        "description": "工作地点明确为上海，需要长期现场办公。本岗位为完全虚构的 Demo JD。",
        "evidence": "工作地点：上海，需长期现场办公",
        "strategy": "skip",
        "recommendation": "do_not_apply",
        "reason": "明确不满足 Demo 候选人的目标地点约束，因此排除。",
        "fit": 28,
        "opportunity": 72,
        "completeness": 90,
        "grade": "D",
        "risk": "critical",
        "hard_filter": "excluded",
        "hard_reasons": ["非目标地点：上海"],
    },
    {
        "key": "closed",
        "company": "澜桥咨询（示例）",
        "title": "初级商业分析师",
        "role": "商业分析",
        "description": "使用数据支持业务决策并制作分析报告；该示例记录已标记失效。本岗位为完全虚构的 Demo JD。",
        "evidence": "使用数据支持业务决策",
        "strategy": "targeted_apply",
        "recommendation": "apply",
        "reason": "历史评估有一定匹配，但岗位已失效，不再进入行动中心。",
        "fit": 76,
        "opportunity": 74,
        "completeness": 81,
        "grade": "B",
        "active": False,
        "age": 35,
    },
    {
        "key": "internship",
        "company": "跃迁机器人（示例）",
        "title": "产品策略实习生",
        "role": "产品",
        "job_type": "internship",
        "description": "参与机器人产品调研、竞品分析、需求整理和项目复盘，每周至少四天。本岗位为完全虚构的 Demo JD。",
        "evidence": "参与产品调研、竞品分析、需求整理和项目复盘",
        "strategy": "priority_apply",
        "recommendation": "priority_apply",
        "reason": "高质量实习使用独立框架评估；职责产出与转正讨论价值较高。",
        "fit": 88,
        "opportunity": 91,
        "completeness": 84,
        "grade": "A",
        "conversion": "possible",
        "conversion_level": "medium",
    },
]


def seed_demo_data(db: Session) -> int:
    """Seed once; never imports or derives anything from the private project database."""
    if db.scalar(select(func.count(Job.id))) != 0:
        return 0

    source = JobSourceConfig(
        source_id="demo-static",
        source_name="Synthetic Demo Dataset",
        source_type="manual",
        company_name="Demo only",
        enabled=False,
        notes="Static synthetic records; network collection is disabled in Demo Mode.",
    )
    db.add(source)
    jobs = [_job(spec) for spec in DEMO_SPECS]
    db.add_all(jobs)
    db.flush()

    for index, job in enumerate(jobs):
        assessment = job.assessment
        db.add(
            AssessmentHistory(
                job_id=job.id,
                assessment_version="public-demo-baseline",
                assessed_at=assessment.assessed_at - timedelta(days=7),
                total_score=max(0, assessment.total_score - 3),
                fit_score=max(0, (assessment.fit_score or 0) - 2),
                opportunity_score=max(0, (assessment.opportunity_score or 0) - 2),
                information_completeness=assessment.information_completeness,
                risk_level=assessment.risk_level,
                application_recommendation=assessment.application_recommendation,
                final_strategy=assessment.final_strategy,
                grade=assessment.grade,
                penalty_score=assessment.penalty_score,
                travel_level=assessment.travel_level,
                travel_penalty=assessment.travel_penalty,
            )
        )
        if index in {0, 3}:
            db.add(CandidateWorkflow(job_id=job.id, status="saved"))

    db.add(
        ExternalEvidence(
            job_id=jobs[0].id,
            company_name=jobs[0].company_name,
            source_platform="demo_note",
            source_title="招聘页补充说明（虚构示例）",
            evidence_text="团队会让新人参与一次完整的需求评审和迭代复盘。",
            evidence_category="career_growth",
            evidence_value="新人可参与完整产品迭代闭环",
            sentiment="positive",
            source_confidence="medium",
            relevance_level="high",
            verification_status="demo_only",
            user_notes="仅用于展示 evidence 结构，不对应真实企业或员工。",
        )
    )

    run = CollectionRun(
        source_id=source.source_id,
        started_at=utcnow() - timedelta(hours=2),
        finished_at=utcnow() - timedelta(hours=2) + timedelta(seconds=1),
        status="demo",
        discovered_count=10,
        shenzhen_count=8,
        imported_count=len(jobs),
        duplicate_count=1,
        filtered_count=1,
        failed_count=0,
        dry_run=True,
        config_hash="synthetic-demo",
    )
    db.add(run)
    db.flush()
    for job in jobs:
        db.add(
            RawCollectedJobRecord(
                collection_run_id=run.id,
                source_id=source.source_id,
                source_job_id=job.source_job_id,
                raw_payload="{}",
                raw_text="Synthetic public-demo record",
                job_title=job.job_title,
                raw_location=job.location_raw,
                normalized_location=job.normalized_location,
                normalized_status="imported",
                location_status=job.workplace_status,
                imported_job_id=job.id,
            )
        )
    db.commit()
    return len(jobs)
