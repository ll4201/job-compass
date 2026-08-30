import csv
import io
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.analyzers import RuleBasedJobAnalyzer
from app.action_service import reassess_application_action
from app.application_strategy import (
    decide_shadow_application_strategy,
    evaluate_career_value,
    evaluate_employer_acceptance,
)
from app.career_path_match import career_path_match
from app.config import load_config
from app.models import AssessmentHistory, ExternalEvidence, Job, JobAssessment, JobSource, utcnow
from app.normalizer import normalize_job, normalized_text
from app.personal_preference import decide_final_shadow_strategy, evaluate_personal_preference
from app.schemas import JobCreate
from app.source_management import discover_company

JSON_FIELDS = {
    "hard_filter_reasons",
    "strengths",
    "risks",
    "missing_information",
    "interview_questions",
    "explanation_json",
    "opportunity_breakdown_json",
}


def _same_text(a: Job, data: dict[str, Any]) -> bool:
    same_keys = (
        normalized_text(a.company_name).casefold()
        == normalized_text(data["company_name"]).casefold()
        and normalized_text(a.job_title).casefold() == normalized_text(data["job_title"]).casefold()
        and a.city == data.get("city")
    )
    similarity = SequenceMatcher(
        None, normalized_text(a.description), normalized_text(data.get("description"))
    ).ratio()
    return same_keys and similarity >= 0.88


def find_duplicate(db: Session, data: dict[str, Any]) -> Job | None:
    if data.get("source_job_id"):
        match = db.scalar(
            select(Job).where(
                Job.source == data["source"], Job.source_job_id == data["source_job_id"]
            )
        )
        if match:
            return match
    match = db.scalar(select(Job).where(Job.content_hash == data["content_hash"]))
    if match:
        return match
    candidates = db.scalars(
        select(Job).where(
            or_(Job.company_name == data["company_name"], Job.job_title == data["job_title"])
        )
    ).all()
    return next((job for job in candidates if _same_text(job, data)), None)


def create_or_merge_job(db: Session, payload: JobCreate | dict[str, Any]) -> tuple[Job, bool]:
    raw = (
        payload.model_dump()
        if isinstance(payload, JobCreate)
        else JobCreate.model_validate(payload).model_dump()
    )
    data = normalize_job(raw)
    duplicate = find_duplicate(db, data)
    if duplicate:
        discover_company(
            db,
            duplicate.company_name,
            discovery_source=data.get("source") or "manual",
            careers_url=data.get("source_url"),
        )
        if data.get("is_sample"):
            duplicate.is_sample = True
        exists = any(
            s.source == data["source"] and s.source_url == data.get("source_url")
            for s in duplicate.sources
        )
        if not exists:
            duplicate.sources.append(
                JobSource(
                    source_id=data.get("source"),
                    source=data["source"],
                    source_job_id=data.get("source_job_id"),
                    source_url=data.get("source_url"),
                )
            )
        duplicate.source_count = len(duplicate.sources)
        db.commit()
        return duplicate, False
    allowed = {column.name for column in Job.__table__.columns}
    job = Job(**{k: v for k, v in data.items() if k in allowed})
    job.sources.append(
        JobSource(
            source_id=job.source,
            source=job.source,
            source_job_id=job.source_job_id,
            source_url=job.source_url,
            is_primary=True,
        )
    )
    db.add(job)
    db.flush()
    discover_company(
        db,
        job.company_name,
        discovery_source=job.source,
        careers_url=job.source_url,
    )
    result = evaluate_application_strategy(data, RuleBasedJobAnalyzer().analyze(data).values)
    job.assessment = JobAssessment(**_prepare_assessment(job, result))
    reassess_application_action(job.assessment)
    db.commit()
    db.refresh(job)
    return job, True


def import_csv(db: Session, content: bytes, *, is_sample: bool = False) -> dict[str, int]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    created = merged = errors = 0
    for row in reader:
        try:
            values = {k: (v or None) for k, v in row.items()}
            values["is_sample"] = is_sample
            _, is_new = create_or_merge_job(db, values)
            created += int(is_new)
            merged += int(not is_new)
        except (ValueError, TypeError):
            db.rollback()
            errors += 1
    return {"created": created, "merged": merged, "errors": errors}


def export_csv(jobs: list[Job]) -> str:
    output = io.StringIO()
    fields = [
        "company_name",
        "job_title",
        "city",
        "job_type",
        "salary_raw",
        "source",
        "source_url",
        "total_score",
        "grade",
        "recommendation",
        "risks",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for job in jobs:
        a = job.assessment
        writer.writerow(
            {
                "company_name": job.company_name,
                "job_title": job.job_title,
                "city": job.city,
                "job_type": job.job_type,
                "salary_raw": job.salary_raw,
                "source": job.source,
                "source_url": job.source_url,
                "total_score": a.total_score if a else "",
                "grade": a.grade if a else "",
                "recommendation": a.recommendation if a else "",
                "risks": "；".join(json.loads(a.risks)) if a else "",
            }
        )
    return output.getvalue()


def _prepare_assessment(job: Job, result: dict[str, Any]) -> dict[str, Any]:
    job.travel_level = str(result.pop("travel_level", "unknown"))
    job.resume_output_potential = str(result.pop("resume_output_potential", "unclear"))
    conversion = result.pop("conversion_level", None)
    job.conversion_level = str(conversion) if conversion else None
    for key in JSON_FIELDS:
        result[key] = json.dumps(result[key], ensure_ascii=False)
    return result


def evaluate_application_strategy(
    job_data: dict[str, Any], v3_result: dict[str, Any]
) -> dict[str, Any]:
    """Add the calibrated personal strategy without changing the V3 judgment."""
    result = dict(v3_result)
    career_match = career_path_match(job_data)
    career_value = evaluate_career_value(job_data, career_match)
    employer_acceptance = evaluate_employer_acceptance(job_data)
    previous = decide_shadow_application_strategy(
        job_data, result, career_value, employer_acceptance
    )
    personal_preference = evaluate_personal_preference(job_data)
    final = decide_final_shadow_strategy(
        job_data,
        result,
        previous,
        career_value,
        employer_acceptance,
        personal_preference,
    )
    result.update(
        career_match_score=career_match.career_match_score,
        career_match_level=career_match.career_match_level,
        career_value_score=career_value.career_value_score,
        career_value_level=career_value.career_value_level,
        employer_acceptance_score=employer_acceptance.employer_acceptance_score,
        employer_acceptance_level=employer_acceptance.employer_acceptance_level,
        personal_preference_score=personal_preference.personal_preference_score,
        personal_preference_level=personal_preference.personal_preference_level,
        final_strategy=final.final_shadow_strategy,
        decision_reason=final.reason,
    )
    explanation = dict(result.get("explanation_json") or {})
    explanation["application_strategy"] = {
        "career_match": career_match.model_dump(),
        "career_value": career_value.model_dump(),
        "employer_acceptance": employer_acceptance.model_dump(),
        "personal_preference": personal_preference.model_dump(),
        "previous_shadow_strategy": previous.shadow_application_strategy,
        "final_strategy": final.final_shadow_strategy,
        "decision_reason": final.reason,
    }
    result["explanation_json"] = explanation
    return result


def reassess_job(db: Session, job: Job) -> JobAssessment:
    if job.assessment:
        _archive_assessment(db, job)
    data = {column.name: getattr(job, column.name) for column in Job.__table__.columns}
    result = _prepare_assessment(
        job, evaluate_application_strategy(data, RuleBasedJobAnalyzer().analyze(data).values)
    )
    if job.assessment is None:
        job.assessment = JobAssessment(**result)
    else:
        for key, value in result.items():
            setattr(job.assessment, key, value)
        job.assessment.assessed_at = utcnow()
    reassess_application_action(job.assessment)
    return job.assessment


def _archive_assessment(db: Session, job: Job) -> None:
    current = job.assessment
    if current is None:
        return
    db.add(
        AssessmentHistory(
            job_id=job.id,
            assessment_version=current.assessment_version,
            assessed_at=current.assessed_at,
            total_score=current.total_score,
            fit_score=current.fit_score,
            opportunity_score=current.opportunity_score,
            information_completeness=current.information_completeness,
            risk_level=current.risk_level,
            application_recommendation=current.application_recommendation,
            seniority_level=current.seniority_level,
            role_direction_match=current.role_direction_match,
            seniority_match=current.seniority_match,
            experience_match=current.experience_match,
            career_match_score=current.career_match_score,
            career_match_level=current.career_match_level,
            career_value_score=current.career_value_score,
            career_value_level=current.career_value_level,
            eligibility_score=current.eligibility_score,
            direction_fit_score=current.direction_fit_score,
            life_quality_score=current.life_quality_score,
            freshness_score=current.freshness_score,
            compensation_score=current.compensation_score,
            overall_priority_score=current.overall_priority_score,
            support_role_type=current.support_role_type,
            needs_confirmation=current.needs_confirmation,
            resume_type=current.resume_type,
            job_age_days=current.job_age_days,
            date_source=current.date_source,
            employer_acceptance_score=current.employer_acceptance_score,
            employer_acceptance_level=current.employer_acceptance_level,
            personal_preference_score=current.personal_preference_score,
            personal_preference_level=current.personal_preference_level,
            final_strategy=current.final_strategy,
            decision_reason=current.decision_reason,
            grade=current.grade,
            penalty_score=current.penalty_score,
            travel_level=current.travel_level,
            travel_penalty=current.travel_penalty,
            scoring_config_hash=current.scoring_config_hash,
        )
    )


def reassess_application_strategy_job(
    db: Session, job: Job, *, archive: bool = True
) -> JobAssessment:
    """Recompute only personal strategy fields while freezing the calibrated V3 result."""
    current = job.assessment
    if current is None:
        raise ValueError(f"岗位 {job.id} 尚无 V3 assessment")
    if archive:
        _archive_assessment(db, job)
    data = {column.name: getattr(job, column.name) for column in Job.__table__.columns}
    v3 = {
        "application_recommendation": current.application_recommendation,
        "hard_filter_status": current.hard_filter_status,
        "risk_level": current.risk_level,
        "explanation_json": json.loads(current.explanation_json or "{}"),
    }
    evaluated = evaluate_application_strategy(data, v3)
    strategy_fields = (
        "career_match_score",
        "career_match_level",
        "career_value_score",
        "career_value_level",
        "employer_acceptance_score",
        "employer_acceptance_level",
        "personal_preference_score",
        "personal_preference_level",
        "final_strategy",
        "decision_reason",
    )
    for field in strategy_fields:
        setattr(current, field, evaluated[field])
    current.explanation_json = json.dumps(evaluated["explanation_json"], ensure_ascii=False)
    current.assessed_at = utcnow()
    reassess_application_action(current)
    return current


def reassess_jobs(
    db: Session,
    *,
    job_ids: list[int] | None = None,
    mode: str = "all",
) -> int:
    load_config.cache_clear()
    statement = select(Job)
    if job_ids is not None:
        statement = statement.where(Job.id.in_(job_ids))
    elif mode == "disagreement":
        statement = statement.where(Job.calibration_status.in_(["overestimated", "underestimated"]))
    elif mode == "travel":
        statement = statement.where(Job.travel_level.notin_(["unknown", "travel_level_0"]))
    jobs = list(db.scalars(statement).all())
    for job in jobs:
        reassess_job(db, job)
    db.commit()
    return len(jobs)


def parse_full_jd(text: str) -> dict[str, str | None]:
    """Conservatively extract editable fields from pasted recruitment text."""
    clean = text.replace("\r\n", "\n").strip()

    def labeled(labels: list[str]) -> str | None:
        pattern = rf"(?:{'|'.join(map(re.escape, labels))})\s*[：:]\s*([^\n]+)"
        match = re.search(pattern, clean, re.IGNORECASE)
        return match.group(1).strip() if match else None

    company = labeled(["公司", "公司名称", "企业名称", "Company"])
    title = labeled(["职位", "职位名称", "岗位", "岗位名称", "Job Title", "Position"])
    location = labeled(["地点", "工作地点", "办公地点", "Location"])
    salary = labeled(["薪资", "薪酬", "薪资范围", "Salary"])
    experience = labeled(["经验", "工作经验", "经验要求", "Experience"])
    education = labeled(["学历", "学历要求", "Education"])

    if not location:
        match = re.search(
            r"(?:深圳(?:市)?(?:南山区|福田区|宝安区|龙岗区|龙华区|罗湖区|光明区|坪山区|盐田区|大鹏新区)?)",
            clean,
        )
        location = match.group(0) if match else None
    if not salary:
        match = re.search(
            r"\d+(?:\.\d+)?\s*[kKwW万千]?\s*[-~至]\s*\d+(?:\.\d+)?\s*[kKwW万千]?(?:\s*/\s*(?:月|年|天))?",
            clean,
        )
        salary = match.group(0) if match else None
    if not experience:
        match = re.search(
            r"(?:应届|无经验|经验不限|不限经验|\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*年|\d+(?:\.\d+)?\s*年以上)",
            clean,
        )
        experience = match.group(0) if match else None
    if not education:
        match = re.search(r"(?:大专|本科|硕士|博士)(?:及以上|以上)?", clean)
        education = match.group(0) if match else None

    benefit_words = [
        "双休",
        "大小周",
        "单休",
        "五险一金",
        "年假",
        "十三薪",
        "十四薪",
        "年终奖",
        "餐补",
        "交通补贴",
        "住房补贴",
        "体检",
        "商业保险",
    ]
    benefit_lines = [
        line.strip() for line in clean.splitlines() if any(word in line for word in benefit_words)
    ]

    responsibility_match = re.search(
        r"(?:职位职责|岗位职责|工作职责|Responsibilities)\s*[：:]?\s*(.+?)(?=\n\s*(?:任职要求|岗位要求|职位要求|Requirements)\s*[：:]?|\Z)",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    responsibilities = responsibility_match.group(1).strip() if responsibility_match else None
    return {
        "company_name": company,
        "job_title": title,
        "location": location,
        "salary_raw": salary,
        "experience_raw": experience,
        "education_requirement": education,
        "benefits_raw": "\n".join(benefit_lines) or None,
        "responsibilities": responsibilities,
        "description": clean,
    }


def create_backup(db: Session) -> dict[str, Any]:
    jobs = list(db.scalars(select(Job).options()).all())
    fields = set(JobCreate.model_fields) & {column.name for column in Job.__table__.columns}
    return {
        "format": "job-compass-backup",
        "version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "jobs": [
            {
                **{field: getattr(job, field) for field in fields},
                "application_status": job.application_status,
                "manual_grade": job.manual_grade,
                "manual_score": job.manual_score,
                "manual_decision": job.manual_decision,
                "manual_comment": job.manual_comment,
                "reviewed_by_user": job.reviewed_by_user,
                "reviewed_at": job.reviewed_at.isoformat() if job.reviewed_at else None,
                "calibration_status": job.calibration_status,
                "sources": [
                    {
                        "source": item.source,
                        "source_job_id": item.source_job_id,
                        "source_url": item.source_url,
                    }
                    for item in job.sources
                ],
            }
            for job in jobs
        ],
        "external_evidence": [
            {
                **{
                    column.name: (
                        getattr(item, column.name).isoformat()
                        if isinstance(getattr(item, column.name), datetime)
                        else getattr(item, column.name)
                    )
                    for column in ExternalEvidence.__table__.columns
                    if column.name not in {"id", "job_id"}
                },
                "job_company_name": item.job.company_name if item.job else None,
                "job_title": item.job.job_title if item.job else None,
            }
            for item in db.scalars(select(ExternalEvidence)).all()
        ],
    }


def restore_backup(db: Session, content: bytes, *, overwrite: bool = False) -> dict[str, int]:
    payload = json.loads(content.decode("utf-8-sig"))
    if payload.get("format") != "job-compass-backup" or not isinstance(payload.get("jobs"), list):
        raise ValueError("不是有效的 Job Compass 备份文件")
    created = skipped = overwritten = errors = 0
    for item in payload["jobs"]:
        try:
            data = normalize_job(JobCreate.model_validate(item).model_dump())
            duplicate = find_duplicate(db, data)
            if duplicate and not overwrite:
                skipped += 1
                continue
            if duplicate:
                db.delete(duplicate)
                db.flush()
                overwritten += 1
            job, _ = create_or_merge_job(db, item)
            job.application_status = item.get("application_status") or job.application_status
            job.manual_grade = item.get("manual_grade")
            job.manual_score = item.get("manual_score")
            job.manual_decision = item.get("manual_decision")
            job.manual_comment = item.get("manual_comment")
            job.reviewed_by_user = bool(item.get("reviewed_by_user"))
            job.reviewed_at = (
                datetime.fromisoformat(item["reviewed_at"]) if item.get("reviewed_at") else None
            )
            job.calibration_status = item.get("calibration_status") or "unreviewed"
            for source in item.get("sources", [])[1:]:
                job.sources.append(JobSource(**source))
            db.commit()
            created += 1
        except (ValueError, TypeError, KeyError):
            db.rollback()
            errors += 1
    evidence_created = evidence_skipped = 0
    from app.evidence import create_evidence, find_evidence_duplicates
    from app.schemas import EvidenceCreate

    for item in payload.get("external_evidence", []):
        try:
            job = db.scalar(
                select(Job).where(
                    Job.company_name == item.get("job_company_name"),
                    Job.job_title == item.get("job_title"),
                )
            )
            values = {
                key: item.get(key)
                for key in EvidenceCreate.model_fields
                if key not in {"job_id", "published_at"}
            }
            values["job_id"] = job.id if job else None
            values["published_at"] = (
                datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None
            )
            if find_evidence_duplicates(db, values):
                evidence_skipped += 1
                continue
            create_evidence(db, values)
            evidence_created += 1
        except (ValueError, TypeError, KeyError):
            db.rollback()
            errors += 1
    result = {
        "created": created,
        "skipped": skipped,
        "overwritten": overwritten,
        "errors": errors,
    }
    if payload.get("external_evidence"):
        result.update(
            evidence_created=evidence_created,
            evidence_skipped=evidence_skipped,
        )
    return result
