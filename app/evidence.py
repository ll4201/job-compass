import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import load_config
from app.models import (
    EvidenceAdjustmentHistory,
    EvidenceAnalysis,
    ExternalEvidence,
    Job,
    utcnow,
)
from app.schemas import EvidenceCreate

SOURCE_PLATFORMS = {
    "xiaohongshu",
    "maimai",
    "zhihu",
    "nowcoder",
    "glassdoor",
    "linkedin",
    "company_official",
    "recruiter_communication",
    "interview",
    "friend_referral",
    "other",
}
EVIDENCE_CATEGORIES = {
    "work_schedule",
    "overtime",
    "weekend_policy",
    "salary",
    "internship_pay",
    "bonus",
    "five_insurances_housing_fund",
    "paid_leave",
    "benefits",
    "internship_conversion",
    "training",
    "management",
    "team_culture",
    "career_growth",
    "layoffs_or_stability",
    "contract_type",
    "overseas_travel",
    "interview_process",
    "other",
}
VERIFICATION_STATUSES = {
    "official_confirmed",
    "interview_confirmed",
    "multiple_reports",
    "employee_reported",
    "conflicting_reports",
    "unverified",
    "outdated_report",
}
CONFIDENCE_LEVELS = {"high", "medium_high", "medium", "medium_low", "low"}
SENTIMENTS = {"positive", "neutral", "negative", "mixed"}

CATEGORY_KEYWORDS = {
    "weekend_policy": ["双休", "单休", "大小周", "周末"],
    "overtime": ["加班", "下班", "996", "995", "调休"],
    "work_schedule": ["工作时间", "上班时间", "弹性", "打卡"],
    "salary": ["薪资", "月薪", "年薪", "工资"],
    "internship_pay": ["实习薪资", "日薪", "元/天", "元每天"],
    "bonus": ["奖金", "年终奖", "十三薪", "十四薪"],
    "five_insurances_housing_fund": ["五险一金", "公积金", "社保"],
    "paid_leave": ["年假", "带薪假", "病假"],
    "benefits": ["福利", "餐补", "交通补贴", "商业保险"],
    "internship_conversion": ["转正", "留用", "HC"],
    "training": ["培训", "导师", "mentor"],
    "management": ["管理", "领导", "汇报"],
    "team_culture": ["团队", "氛围", "文化"],
    "career_growth": ["晋升", "成长", "发展空间"],
    "layoffs_or_stability": ["裁员", "稳定", "业务收缩", "经营风险"],
    "contract_type": ["合同", "派遣", "外包", "主体签署"],
    "overseas_travel": ["海外出差", "出差", "驻外"],
    "interview_process": ["面试", "笔试", "面经"],
}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def parse_external_share(text: str, title: str | None = None) -> dict[str, Any]:
    """Conservative parser: extracted values are a preview, never persisted automatically."""
    clean = text.replace("\r\n", "\n").strip()

    def labeled(labels: list[str]) -> str | None:
        match = re.search(
            rf"(?:{'|'.join(map(re.escape, labels))})\s*[：:]\s*([^\n]+)", clean, re.I
        )
        return match.group(1).strip() if match else None

    company = labeled(["公司", "公司名称", "企业", "Company"])
    city = labeled(["城市", "地点", "工作地点", "Location"])
    if not city and "深圳" in clean:
        city = "深圳"
    department = labeled(["部门", "团队", "事业部", "Department"])
    role = labeled(["岗位", "职位", "职务", "Role", "Position"])
    employment = labeled(["用工类型", "岗位类型", "Employment"])
    if not employment:
        if "实习" in clean or "intern" in clean.casefold():
            employment = "internship"
        elif any(word in clean for word in ("正式岗", "全职", "社招", "校招")):
            employment = "full_time"
    detected = [
        category for category, words in CATEGORY_KEYWORDS.items() if any(w in clean for w in words)
    ]
    category = detected[0] if len(detected) == 1 else "other"
    negative_words = ("单休", "大小周", "经常加班", "无公积金", "裁员", "不稳定", "外包")
    positive_words = ("双休", "五险一金", "有导师", "转正机会", "氛围好", "带薪年假")
    has_negative = any(word in clean for word in negative_words)
    has_positive = any(word in clean for word in positive_words)
    sentiment = (
        "mixed"
        if has_negative and has_positive
        else "negative"
        if has_negative
        else "positive"
        if has_positive
        else "neutral"
    )
    return {
        "company_name": company,
        "city": city,
        "department": department,
        "role_name": role,
        "employment_type": employment,
        "evidence_category": category,
        "detected_categories": detected,
        "sentiment": sentiment,
        "source_title": title,
        "evidence_text": clean,
    }


def _is_outdated(published_at: datetime | None, years: int) -> bool:
    if not published_at:
        return False
    now = datetime.now(timezone.utc)
    value = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
    return (now - value).days > years * 365


def calculate_relevance(job: Job | None, values: dict[str, Any]) -> str:
    if not job or _clean(job.company_name) != _clean(values.get("company_name")):
        return "low"
    score = 2
    city = _clean(values.get("city"))
    if city and city == _clean(job.city or job.location_raw):
        score += 2
    department = _clean(values.get("department"))
    job_department = _clean(getattr(job, "department", None))
    job_context = _clean(f"{job.description} {job.responsibilities or ''}")
    if department and (
        (job_department and (department in job_department or job_department in department))
        or department in job_context
    ):
        score += 2
    role = _clean(values.get("role_name"))
    if role and SequenceMatcher(None, role, _clean(job.job_title)).ratio() >= 0.45:
        score += 2
    employment = values.get("employment_type")
    if employment and employment == job.job_type:
        score += 1
    published = values.get("published_at")
    if published and not _is_outdated(
        published, load_config("evidence_rules.yaml")["limits"]["outdated_years"]
    ):
        score += 1
    return (
        "very_high" if score >= 8 else "high" if score >= 6 else "medium" if score >= 4 else "low"
    )


def resolve_confidence(values: dict[str, Any], *, outdated: bool) -> str:
    rules = load_config("evidence_rules.yaml")
    requested = values.get("source_confidence")
    confidence = (
        requested
        if requested in CONFIDENCE_LEVELS
        else rules["verification_confidence"].get(
            values.get("verification_status"),
            rules["platform_defaults"].get(values.get("source_platform"), "low"),
        )
    )
    if outdated:
        order = ["low", "medium_low", "medium", "medium_high", "high"]
        confidence = order[max(0, order.index(confidence) - 2)]
    return confidence


def create_evidence(db: Session, payload: EvidenceCreate | dict[str, Any]) -> ExternalEvidence:
    values = (
        payload.model_dump()
        if isinstance(payload, EvidenceCreate)
        else EvidenceCreate.model_validate(payload).model_dump()
    )
    if values["source_platform"] not in SOURCE_PLATFORMS:
        raise ValueError("不支持的来源平台")
    if values["evidence_category"] not in EVIDENCE_CATEGORIES:
        raise ValueError("不支持的证据类别")
    if values["verification_status"] == "unverified":
        if values["source_platform"] in {"interview", "recruiter_communication"}:
            values["verification_status"] = "interview_confirmed"
        elif values["source_platform"] == "company_official":
            values["verification_status"] = "official_confirmed"
    if values["verification_status"] not in VERIFICATION_STATUSES:
        raise ValueError("不支持的核实状态")
    if values["sentiment"] not in SENTIMENTS:
        raise ValueError("不支持的情绪标签")
    job = db.get(Job, values.get("job_id")) if values.get("job_id") else None
    outdated = _is_outdated(
        values.get("published_at"), load_config("evidence_rules.yaml")["limits"]["outdated_years"]
    )
    values["is_outdated"] = outdated
    values["source_confidence"] = resolve_confidence(values, outdated=outdated)
    values["relevance_level"] = calculate_relevance(job, values)
    if outdated and values["verification_status"] == "unverified":
        values["verification_status"] = "outdated_report"
    evidence = ExternalEvidence(**values)
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def update_evidence(
    db: Session, evidence: ExternalEvidence, payload: EvidenceCreate | dict[str, Any]
) -> ExternalEvidence:
    values = (
        payload.model_dump()
        if isinstance(payload, EvidenceCreate)
        else EvidenceCreate.model_validate(payload).model_dump()
    )
    if values["source_platform"] not in SOURCE_PLATFORMS:
        raise ValueError("不支持的来源平台")
    if values["evidence_category"] not in EVIDENCE_CATEGORIES:
        raise ValueError("不支持的证据类别")
    if values["verification_status"] == "unverified":
        if values["source_platform"] in {"interview", "recruiter_communication"}:
            values["verification_status"] = "interview_confirmed"
        elif values["source_platform"] == "company_official":
            values["verification_status"] = "official_confirmed"
    if values["verification_status"] not in VERIFICATION_STATUSES:
        raise ValueError("不支持的核实状态")
    job = db.get(Job, values.get("job_id")) if values.get("job_id") else None
    outdated = _is_outdated(
        values.get("published_at"),
        load_config("evidence_rules.yaml")["limits"]["outdated_years"],
    )
    values["is_outdated"] = outdated
    values["source_confidence"] = resolve_confidence(values, outdated=outdated)
    values["relevance_level"] = calculate_relevance(job, values)
    for key, value in values.items():
        setattr(evidence, key, value)
    evidence.updated_at = utcnow()
    db.commit()
    db.refresh(evidence)
    return evidence


def find_evidence_duplicates(db: Session, values: dict[str, Any]) -> list[ExternalEvidence]:
    clauses = []
    if values.get("source_url"):
        clauses.append(ExternalEvidence.source_url == values["source_url"])
    if values.get("company_name"):
        clauses.append(ExternalEvidence.company_name == values["company_name"])
    candidates = (
        list(db.scalars(select(ExternalEvidence).where(or_(*clauses))).all()) if clauses else []
    )
    text = _clean(values.get("evidence_text") or values.get("page_text"))
    return [
        item
        for item in candidates
        if (values.get("source_url") and item.source_url == values.get("source_url"))
        or (text and SequenceMatcher(None, text, _clean(item.evidence_text)).ratio() >= 0.9)
    ]


def evidence_signature(items: list[ExternalEvidence]) -> str:
    payload = "|".join(
        f"{item.id}:{item.updated_at.isoformat()}"
        for item in sorted(items, key=lambda value: value.id)
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _independent_key(item: ExternalEvidence) -> str:
    return (
        item.source_url
        or f"{item.source_platform}:{item.source_title or item.id}:{item.source_author_type or 'anonymous'}"
    )


def analyze_evidence(job: Job, items: list[ExternalEvidence]) -> dict[str, Any]:
    rules = load_config("evidence_rules.yaml")
    groups: dict[str, list[ExternalEvidence]] = defaultdict(list)
    for item in items:
        groups[item.evidence_category].append(item)
    completeness = 0.0
    opportunity = 0.0
    risk = 0
    conflicts: list[str] = []
    consistent: list[str] = []
    ignored: list[str] = []
    questions: list[str] = []
    confidence_scores: list[float] = []
    details: dict[str, Any] = {}
    for category, category_items in groups.items():
        independent = {_independent_key(item) for item in category_items}
        sentiments = {
            item.sentiment for item in category_items if item.sentiment in {"positive", "negative"}
        }
        values = {_clean(item.evidence_value) for item in category_items if item.evidence_value}
        conflict = len(sentiments) > 1 or len(values) > 1
        weights = [
            rules["confidence_weights"][item.source_confidence]
            * rules["relevance_weights"][item.relevance_level]
            for item in category_items
            if not item.is_outdated
        ]
        official = any(
            item.verification_status in {"official_confirmed", "interview_confirmed"}
            for item in category_items
        )
        strong = official or (
            len(independent) >= 2 and len(weights) >= 2 and sum(weights) / len(weights) >= 0.4
        )
        details[category] = {
            "sources": len(independent),
            "conflict": conflict,
            "strong": strong,
            "average_weight": round(sum(weights) / len(weights), 2) if weights else 0,
        }
        confidence_scores.extend(weights)
        if conflict:
            conflicts.append(category)
            questions.append(
                rules["category_questions"].get(category, rules["conflict_question_prefix"])
            )
            continue
        if not strong:
            ignored.append(category)
            question = rules["category_questions"].get(category)
            if question:
                questions.append(question)
            continue
        consistent.append(category)
        completeness += 3
        dominant = (
            "negative"
            if any(item.sentiment == "negative" for item in category_items)
            else "positive"
            if any(item.sentiment == "positive" for item in category_items)
            else "neutral"
        )
        if dominant == "positive" and category in rules["positive_categories"]:
            opportunity += 1.5
        elif dominant == "negative":
            opportunity -= 1.5
            if category in rules["risk_categories"]:
                risk = 1
        elif category in {"salary", "internship_pay", "bonus", "benefits"}:
            completeness += 1
    limits = rules["limits"]
    completeness = min(float(limits["completeness_boost"]), completeness)
    opportunity = max(
        -float(limits["opportunity_adjustment"]),
        min(float(limits["opportunity_adjustment"]), opportunity),
    )
    risk = max(-int(limits["risk_steps"]), min(int(limits["risk_steps"]), risk))
    average = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
    confidence = (
        "high"
        if average >= 0.75
        else "medium"
        if average >= 0.45 or (consistent and average >= 0.35)
        else "low"
        if items
        else "none"
    )
    base = job.assessment
    base_completeness = base.information_completeness if base else None
    base_opportunity = base.opportunity_score if base else None
    risk_order = ["low", "medium", "high", "critical"]
    base_risk = base.risk_level if base and base.risk_level in risk_order else "low"
    adjusted_risk = risk_order[min(len(risk_order) - 1, max(0, risk_order.index(base_risk) + risk))]
    summary = f"共 {len(items)} 条证据；{len(consistent)} 类形成一致支持，{len(conflicts)} 类存在冲突，{len(ignored)} 类证据尚不足。"
    return {
        "evidence_completeness_boost": round(completeness, 1),
        "evidence_opportunity_adjustment": round(opportunity, 1),
        "evidence_risk_adjustment": risk,
        "evidence_confidence": confidence,
        "evidence_summary": summary,
        "adjusted_information_completeness": min(100, (base_completeness or 0) + completeness)
        if base_completeness is not None
        else None,
        "adjusted_opportunity_score": max(0, min(100, (base_opportunity or 0) + opportunity))
        if base_opportunity is not None
        else None,
        "adjusted_risk_level": adjusted_risk,
        "interview_questions": list(dict.fromkeys(questions)),
        "explanation": {
            "consistent_categories": consistent,
            "conflicting_categories": conflicts,
            "insufficient_categories": ignored,
            "category_details": details,
            "limits": limits,
        },
        "evidence_signature": evidence_signature(items),
    }


def apply_evidence_analysis(db: Session, job: Job, result: dict[str, Any]) -> EvidenceAnalysis:
    conflicts = set(result["explanation"]["conflicting_categories"])
    consistent = set(result["explanation"]["consistent_categories"])
    for item in job.external_evidence:
        if item.is_outdated or item.verification_status in {
            "official_confirmed",
            "interview_confirmed",
        }:
            continue
        if item.evidence_category in conflicts:
            item.verification_status = "conflicting_reports"
            item.source_confidence = "low"
        elif item.evidence_category in consistent:
            item.verification_status = "multiple_reports"
            item.source_confidence = "medium_high"
    db.flush()
    result["evidence_signature"] = evidence_signature(job.external_evidence)
    base = job.assessment
    db.add(
        EvidenceAdjustmentHistory(
            job_id=job.id,
            base_fit_score=base.fit_score if base else None,
            base_opportunity_score=base.opportunity_score if base else None,
            base_information_completeness=base.information_completeness if base else None,
            base_risk_level=base.risk_level if base else None,
            evidence_completeness_boost=result["evidence_completeness_boost"],
            evidence_opportunity_adjustment=result["evidence_opportunity_adjustment"],
            evidence_risk_adjustment=result["evidence_risk_adjustment"],
            evidence_confidence=result["evidence_confidence"],
            evidence_summary=result["evidence_summary"],
            explanation_json=json.dumps(result["explanation"], ensure_ascii=False),
        )
    )
    values = {
        key: result[key]
        for key in (
            "evidence_completeness_boost",
            "evidence_opportunity_adjustment",
            "evidence_risk_adjustment",
            "evidence_confidence",
            "evidence_summary",
            "adjusted_information_completeness",
            "adjusted_opportunity_score",
            "adjusted_risk_level",
            "evidence_signature",
        )
    }
    values["interview_questions_json"] = json.dumps(
        result["interview_questions"], ensure_ascii=False
    )
    values["explanation_json"] = json.dumps(result["explanation"], ensure_ascii=False)
    if job.evidence_analysis is None:
        job.evidence_analysis = EvidenceAnalysis(**values)
    else:
        for key, value in values.items():
            setattr(job.evidence_analysis, key, value)
        job.evidence_analysis.applied_at = utcnow()
    db.commit()
    return job.evidence_analysis


def company_evidence_summary(items: list[ExternalEvidence]) -> dict[str, Any]:
    grouped: dict[str, list[ExternalEvidence]] = defaultdict(list)
    for item in items:
        grouped[item.evidence_category].append(item)
    consistent, conflicts, questions = [], [], []
    rules = load_config("evidence_rules.yaml")
    for category, values in grouped.items():
        sentiments = {
            item.sentiment for item in values if item.sentiment in {"positive", "negative"}
        }
        evidence_values = {_clean(item.evidence_value) for item in values if item.evidence_value}
        if len(sentiments) > 1 or len(evidence_values) > 1:
            conflicts.append(category)
            questions.append(
                rules["category_questions"].get(category, rules["conflict_question_prefix"])
            )
        elif len({_independent_key(item) for item in values}) >= 2:
            consistent.append(category)
    return {
        "consistent": consistent,
        "conflicts": conflicts,
        "questions": list(dict.fromkeys(questions)),
    }
