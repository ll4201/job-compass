import json
import os
import re
import signal
import threading
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session, joinedload

from app.assets import CachedStaticFiles, asset_version
from app.collection_pipeline import collection_record_diagnostic, run_enabled_sources, run_source
from app.collectors import COLLECTORS
from app.application_action import ACTION_LABELS, recommended_resume_version
from app.database import SessionLocal, get_db, init_db
from app.demo_data import seed_demo_data
from app.daily_dashboard import (
    ACTION_TYPES,
    build_daily_action_dashboard,
    daily_action_summary,
    empty_daily_actions,
)
from app.feedback_analytics import build_application_outcomes
from app.job_policy import (
    apply_effective_job_filters,
    effective_action_type,
    effective_final_strategy,
)
from app.config import load_config
from app.evidence import (
    CONFIDENCE_LEVELS,
    EVIDENCE_CATEGORIES,
    SENTIMENTS,
    SOURCE_PLATFORMS,
    VERIFICATION_STATUSES,
    analyze_evidence,
    apply_evidence_analysis,
    company_evidence_summary,
    create_evidence,
    evidence_signature,
    find_evidence_duplicates,
    parse_external_share,
    update_evidence,
)
from app.models import (
    CandidateCompany,
    CandidateWorkflow,
    CollectionRun,
    ExternalEvidence,
    Job,
    JobAssessment,
    JobSource,
    JobSourceConfig,
    RawCollectedJobRecord,
    utcnow,
)
from app.p1_scoring import evaluate_p1_shadow
from app.schemas import EvidenceApiSubmission, EvidenceCreate, JobCreate, JobOut
from app.services import (
    create_backup,
    create_or_merge_job,
    export_csv,
    import_csv,
    parse_full_jd,
    restore_backup,
    reassess_job,
    reassess_jobs,
)
from app.settings import ROOT, settings
from app.source_management import (
    ats_config_from_url,
    backfill_candidate_companies,
    detect_ats,
    discover_company,
    promote_candidate,
    sync_sources_from_yaml,
)
from app.workflow import (
    INTERVIEW_RESULTS,
    NOT_APPLIED_REASONS,
    WORKFLOW_STATUSES,
    save_application_feedback,
    update_workflow_status,
    workflow_status,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        if settings.demo_mode:
            seed_demo_data(db)
        else:
            sync_sources_from_yaml(db)
        backfill_candidate_companies(db)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
static_directory = ROOT / "app" / "static"
app.mount("/static", CachedStaticFiles(directory=static_directory), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")
templates.env.globals["demo_mode"] = settings.demo_mode
STATIC_VERSION = asset_version(
    static_directory / "app.css",
    static_directory / "favicon.svg",
)
templates.env.globals["static_version"] = STATIC_VERSION


@app.middleware("http")
async def enforce_demo_mode(request: Request, call_next):
    """Allow human-review interactions while blocking operational mutations."""
    if settings.demo_mode and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        allowed = re.fullmatch(
            r"/jobs/\d+/(manual-review|workflow|feedback|viewed)", request.url.path
        )
        if allowed is None:
            message = "This action is disabled in Demo Mode"
            if request.url.path.startswith("/api/"):
                return Response(
                    json.dumps({"detail": message}),
                    status_code=403,
                    media_type="application/json",
                )
            return RedirectResponse(f"/?message={quote(message)}", status_code=303)
    return await call_next(request)


@app.get("/favicon.ico", include_in_schema=False)
def legacy_favicon():
    """Avoid a noisy 404 for clients that still request the conventional path."""
    return RedirectResponse(
        f"/static/favicon.svg?v={STATIC_VERSION}",
        status_code=307,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/application-outcomes", response_class=HTMLResponse)
def application_outcomes(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "application_outcomes.html",
        {"outcomes": build_application_outcomes(db)},
    )


def _evidence_options() -> dict[str, list[str]]:
    return {
        "platforms": sorted(SOURCE_PLATFORMS),
        "categories": sorted(EVIDENCE_CATEGORIES),
        "verification_statuses": sorted(VERIFICATION_STATUSES),
        "confidence_levels": sorted(CONFIDENCE_LEVELS),
        "sentiments": sorted(SENTIMENTS),
    }


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _infer_calibration(
    system_score: float,
    system_grade: str,
    manual_score: float | None,
    manual_grade: str,
) -> str:
    if manual_score is not None:
        difference = system_score - manual_score
        return (
            "overestimated"
            if difference > 5
            else "underestimated"
            if difference < -5
            else "aligned"
        )
    if manual_grade:
        ranks = {"A": 4, "B": 3, "C": 2, "D": 1}
        difference = ranks[system_grade] - ranks[manual_grade]
        return (
            "overestimated" if difference > 0 else "underestimated" if difference < 0 else "aligned"
        )
    return "aligned"


def _calibration_stats(jobs: list[Job]) -> dict[str, object]:
    reviewed = [job for job in jobs if job.reviewed_by_user]
    differences = [
        job.assessment.total_score - job.manual_score
        for job in reviewed
        if job.manual_score is not None
    ]
    aligned = sum(job.calibration_status == "aligned" for job in reviewed)
    over_reasons = Counter(
        job.manual_comment
        for job in reviewed
        if job.calibration_status == "overestimated" and job.manual_comment
    )
    under_reasons = Counter(
        job.manual_comment
        for job in reviewed
        if job.calibration_status == "underestimated" and job.manual_comment
    )
    dimension_bias: defaultdict[str, list[float]] = defaultdict(list)
    for job in reviewed:
        if job.manual_score is None or not job.assessment:
            continue
        explanation = json.loads(job.assessment.explanation_json or "{}")
        target_ratio = job.manual_score / 100
        for dimension in explanation.get("dimensions", []):
            maximum = dimension.get("max_score") or 1
            dimension_bias[dimension["name"]].append(
                abs(dimension["score"] / maximum - target_ratio)
            )
    largest_dimension = max(
        dimension_bias,
        key=lambda name: sum(dimension_bias[name]) / len(dimension_bias[name]),
        default="暂无足够人工分数",
    )
    return {
        "reviewed": len(reviewed),
        "alignment_rate": round(aligned / len(reviewed) * 100, 1) if reviewed else 0,
        "average_difference": round(sum(abs(value) for value in differences) / len(differences), 1)
        if differences
        else 0,
        "overestimated": sum(job.calibration_status == "overestimated" for job in reviewed),
        "underestimated": sum(job.calibration_status == "underestimated" for job in reviewed),
        "top_over_reason": over_reasons.most_common(1)[0][0] if over_reasons else "暂无",
        "top_under_reason": under_reasons.most_common(1)[0][0] if under_reasons else "暂无",
        "largest_dimension": largest_dimension,
    }


def query_jobs(
    db: Session,
    *,
    grade: str | None = None,
    job_type: str | None = None,
    source: str | None = None,
    role: str | None = None,
    q: str | None = None,
    weekends: bool = False,
    fund: bool = False,
    salary: bool = False,
    risks: bool = False,
    reviewed: bool = False,
    calibration_status: str | None = None,
    travel_level: str | None = None,
    manual_decision: str | None = None,
    risk_level: str | None = None,
    application_recommendation: str | None = None,
    company: str | None = None,
    new_only: bool = False,
    freshness: str | None = None,
    origin: str | None = None,
    job_filter: str | None = None,
    final_strategy: str | None = None,
    workflow_status_filter: str | None = None,
    action_type: str | None = None,
    include_inactive: bool = False,
    include_test: bool = False,
) -> list[Job]:
    stmt = (
        select(Job)
        .options(joinedload(Job.assessment), joinedload(Job.candidate_workflow))
        .join(JobAssessment)
        .order_by(
            case(
                (JobAssessment.final_strategy == "priority_apply", 0),
                (JobAssessment.final_strategy == "targeted_apply", 1),
                (JobAssessment.final_strategy == "stretch_apply", 2),
                (JobAssessment.final_strategy == "low_cost_try", 3),
                (JobAssessment.final_strategy == "hold", 4),
                (JobAssessment.final_strategy == "skip", 5),
                else_=6,
            ),
            JobAssessment.fit_score.desc(),
        )
    )
    stmt = apply_effective_job_filters(
        stmt,
        include_inactive=include_inactive,
        include_test=include_test,
    )
    if grade:
        stmt = stmt.where(JobAssessment.grade == grade)
    if job_type:
        stmt = stmt.where(Job.job_type == job_type)
    if source:
        stmt = stmt.where(Job.sources.any(JobSource.source_id == source))
    if company:
        stmt = stmt.where(Job.company_name == company)
    if new_only:
        stmt = stmt.where(Job.is_new.is_(True))
    if freshness in {"24h", "3d", "7d"}:
        hours = {"24h": 24, "3d": 72, "7d": 168}[freshness]
        stmt = stmt.where(Job.first_seen_at >= utcnow() - timedelta(hours=hours))
    if origin == "automatic":
        stmt = stmt.where(Job.source.notin_(["manual", "csv"]))
    elif origin == "manual":
        stmt = stmt.where(Job.source.in_(["manual", "csv"]))
    if role:
        stmt = stmt.where(Job.role_direction == role)
    if q:
        stmt = stmt.where(Job.company_name.contains(q) | Job.job_title.contains(q))
    if weekends:
        stmt = stmt.where(Job.working_schedule == "confirmed_yes")
    if fund:
        stmt = stmt.where(Job.five_insurances_housing_fund == "confirmed_yes")
    if salary:
        stmt = stmt.where(Job.salary_min.is_not(None))
    if risks:
        stmt = stmt.where(JobAssessment.risks != "[]")
    if reviewed:
        stmt = stmt.where(Job.reviewed_by_user.is_(True))
    if calibration_status:
        stmt = stmt.where(Job.calibration_status == calibration_status)
    if travel_level:
        stmt = stmt.where(Job.travel_level == travel_level)
    if manual_decision:
        stmt = stmt.where(Job.manual_decision == manual_decision)
    if risk_level:
        stmt = stmt.where(JobAssessment.risk_level == risk_level)
    if application_recommendation:
        stmt = stmt.where(JobAssessment.application_recommendation == application_recommendation)
    if workflow_status_filter:
        stmt = stmt.outerjoin(CandidateWorkflow)
        if workflow_status_filter == "new":
            stmt = stmt.where(
                or_(
                    CandidateWorkflow.status == "new",
                    CandidateWorkflow.id.is_(None),
                )
            )
        else:
            stmt = stmt.where(CandidateWorkflow.status == workflow_status_filter)
    if job_filter == "confirmed_shenzhen":
        stmt = stmt.where(Job.location_conflict.is_(False))
    elif job_filter == "location_conflict":
        stmt = stmt.where(Job.location_conflict.is_(True))
    if job_filter == "entry_level":
        stmt = stmt.where(
            JobAssessment.seniority_level.in_(
                ["internship", "graduate", "entry", "junior", "associate"]
            )
        )
    elif job_filter == "seniority_too_high":
        stmt = stmt.where(JobAssessment.seniority_match == "low")
    elif job_filter == "experience_too_high":
        stmt = stmt.where(JobAssessment.experience_match == "low")
    jobs = list(db.scalars(stmt).unique())
    if final_strategy:
        jobs = [job for job in jobs if effective_final_strategy(job) == final_strategy]
    if action_type:
        jobs = [job for job in jobs if effective_action_type(job) == action_type]
    return jobs


def _latest_collection_summary(db: Session) -> dict[str, object]:
    summary: dict[str, object] = {
        "run": None,
        "source_name": "",
        "new_count": 0,
        "priority_apply": 0,
        "apply": 0,
        "try": 0,
        "hold": 0,
        "filtered": 0,
        "failed_sources": 0,
    }
    run = db.scalar(select(CollectionRun).order_by(CollectionRun.started_at.desc()))
    if run is None:
        return summary
    job_ids = list(
        db.scalars(
            select(RawCollectedJobRecord.imported_job_id).where(
                RawCollectedJobRecord.collection_run_id == run.id,
                RawCollectedJobRecord.imported_job_id.is_not(None),
            )
        ).all()
    )
    jobs = list(db.scalars(select(Job).where(Job.id.in_(job_ids))).all()) if job_ids else []
    recommendations = Counter(
        job.assessment.application_recommendation for job in jobs if job.assessment
    )
    summary.update(
        {
            "run": run,
            "source_name": run.source.source_name if run.source else run.source_id or "未知来源",
            "new_count": run.imported_count,
            "priority_apply": recommendations["priority_apply"],
            "apply": recommendations["apply"],
            "try": recommendations["try"],
            "hold": recommendations["hold_for_info"],
            "filtered": run.filtered_count,
            "failed_sources": 1 if run.status == "failed" else 0,
        }
    )
    return summary


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: Session = Depends(get_db),
    grade: str | None = None,
    job_type: str | None = None,
    source: str | None = None,
    role: str | None = None,
    q: str | None = None,
    weekends: bool = False,
    fund: bool = False,
    salary: bool = False,
    risks: bool = False,
    message: str | None = None,
    reviewed: bool = False,
    calibration_status: str | None = None,
    travel_level: str | None = None,
    manual_decision: str | None = None,
    risk_level: str | None = None,
    application_recommendation: str | None = None,
    company: str | None = None,
    new_only: bool = False,
    freshness: str | None = None,
    origin: str | None = None,
    job_filter: str | None = None,
    final_strategy: str | None = None,
    workflow_status: str | None = None,
    action_type: str | None = None,
    include_inactive: bool = False,
    include_test: bool = False,
):
    jobs = query_jobs(
        db,
        grade=grade,
        job_type=job_type,
        source=source,
        role=role,
        q=q,
        weekends=weekends,
        fund=fund,
        salary=salary,
        risks=risks,
        reviewed=reviewed,
        calibration_status=calibration_status,
        travel_level=travel_level,
        manual_decision=manual_decision,
        risk_level=risk_level,
        application_recommendation=application_recommendation,
        company=company,
        new_only=new_only,
        freshness=freshness,
        origin=origin,
        job_filter=job_filter,
        final_strategy=final_strategy,
        workflow_status_filter=workflow_status,
        action_type=action_type,
        include_inactive=include_inactive,
        include_test=include_test,
    )
    company_stmt = select(Job.company_name).distinct().order_by(Job.company_name)
    company_stmt = apply_effective_job_filters(
        company_stmt,
        include_inactive=include_inactive,
        include_test=include_test,
    )
    companies = list(db.scalars(company_stmt))
    sources = list(db.scalars(select(JobSourceConfig).order_by(JobSourceConfig.source_name)).all())
    strategy_labels = (
        ("priority_apply", "优先投递"),
        ("targeted_apply", "定制投递"),
        ("stretch_apply", "拉伸申请"),
        ("low_cost_try", "低成本尝试"),
        ("hold", "暂缓确认"),
        ("skip", "跳过"),
        ("unassessed", "待正式评估"),
    )
    strategy_groups = {
        key: [
            job
            for job in jobs
            if effective_final_strategy(job) == key
        ]
        for key, _label in strategy_labels
    }
    daily_actions = empty_daily_actions()
    daily_actions.update(build_daily_action_dashboard(jobs))
    daily_summary = daily_action_summary(daily_actions)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "jobs": jobs,
            "filters": request.query_params,
            "message": message,
            "companies": companies,
            "sources": sources,
            "collection_summary": _latest_collection_summary(db),
            "strategy_labels": strategy_labels,
            "strategy_groups": strategy_groups,
            "workflow_statuses": WORKFLOW_STATUSES,
            "workflow_status": workflow_status,
            "daily_actions": daily_actions,
            "daily_summary": daily_summary,
            "action_type": action_type,
            "action_types": ACTION_TYPES,
            "action_labels": ACTION_LABELS,
            "effective_final_strategy": effective_final_strategy,
            "effective_action_type": effective_action_type,
        },
    )


@app.get("/jobs/new", response_class=HTMLResponse)
def new_job(request: Request):
    return templates.TemplateResponse(
        request, "new.html", {"values": {}, "previewed": False, "error": None}
    )


@app.post("/jobs/preview", response_class=HTMLResponse)
def preview_job(request: Request, full_jd: Annotated[str, Form()] = ""):
    if not full_jd.strip():
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "values": {"full_jd": ""},
                "previewed": False,
                "error": "请先粘贴完整 JD，再点击“解析并预览”。",
            },
            status_code=400,
        )
    values = parse_full_jd(full_jd)
    values["full_jd"] = full_jd
    return templates.TemplateResponse(
        request,
        "new.html",
        {"values": values, "previewed": True, "error": None},
    )


@app.post("/jobs/new")
def new_job_post(
    request: Request,
    db: Session = Depends(get_db),
    full_jd: str = Form(""),
    company_name: str = Form(""),
    job_title: str = Form(""),
    location: str = Form(""),
    source_url: str = Form(""),
    salary_raw: str = Form(""),
    experience_raw: str = Form(""),
    job_type: str = Form("full_time"),
    benefits_raw: str = Form(""),
    education_requirement: str = Form(""),
    responsibilities: str = Form(""),
):
    parsed = parse_full_jd(full_jd) if full_jd.strip() else {}
    values = {
        "full_jd": full_jd,
        "company_name": company_name.strip() or parsed.get("company_name") or "",
        "job_title": job_title.strip() or parsed.get("job_title") or "",
        "location": location.strip() or parsed.get("location") or "",
        "job_type": job_type,
        "salary_raw": salary_raw.strip() or parsed.get("salary_raw") or "",
        "experience_raw": experience_raw.strip() or parsed.get("experience_raw") or "",
        "education_requirement": education_requirement.strip()
        or parsed.get("education_requirement")
        or "",
        "source_url": source_url.strip(),
        "responsibilities": responsibilities.strip() or parsed.get("responsibilities") or "",
        "benefits_raw": benefits_raw.strip() or parsed.get("benefits_raw") or "",
    }
    if not full_jd.strip():
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "values": values,
                "previewed": True,
                "error": "完整 JD 不能为空，请返回上方粘贴招聘文本。",
            },
            status_code=400,
        )
    if not values["company_name"] or not values["job_title"]:
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "values": values,
                "previewed": True,
                "error": "未能确定公司名称或职位名称，请补充后再保存。",
            },
            status_code=400,
        )
    job, _ = create_or_merge_job(
        db,
        JobCreate(
            company_name=values["company_name"],
            job_title=values["job_title"],
            location_raw=values["location"],
            description=full_jd,
            source_url=values["source_url"] or None,
            salary_raw=values["salary_raw"] or None,
            experience_raw=values["experience_raw"] or None,
            job_type=values["job_type"],
            benefits_raw=values["benefits_raw"] or None,
            education_requirement=values["education_requirement"] or None,
            responsibilities=values["responsibilities"] or None,
        ),
    )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@app.post("/jobs/{job_id}/delete")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    db.delete(job)
    db.commit()
    return RedirectResponse("/?message=" + quote("岗位已删除"), status_code=303)


@app.post("/jobs/bulk-delete")
def bulk_delete(job_ids: Annotated[list[int], Form()], db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job).where(Job.id.in_(job_ids))).all())
    for job in jobs:
        db.delete(job)
    db.commit()
    return RedirectResponse("/?message=" + quote(f"已删除 {len(jobs)} 个岗位"), status_code=303)


@app.post("/jobs/clear-samples")
def clear_samples(db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job).where(Job.is_sample.is_(True))).all())
    for job in jobs:
        db.delete(job)
    db.commit()
    return RedirectResponse("/?message=" + quote(f"已清理 {len(jobs)} 个示例岗位"), status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def detail(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = (
        db.execute(
            select(Job)
            .options(
                joinedload(Job.assessment),
                joinedload(Job.sources),
                joinedload(Job.assessment_history),
                joinedload(Job.external_evidence),
                joinedload(Job.evidence_analysis),
                joinedload(Job.candidate_workflow),
                joinedload(Job.workflow_history),
                joinedload(Job.application_feedback),
            )
            .where(Job.id == job_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if not job:
        raise HTTPException(404, "Job not found")
    a = job.assessment
    decoded = (
        {
            key: json.loads(getattr(a, key))
            for key in (
                "hard_filter_reasons",
                "strengths",
                "risks",
                "missing_information",
                "interview_questions",
            )
        }
        if a
        else {}
    )
    explanation = json.loads(a.explanation_json or "{}") if a else {}
    p1_shadow = evaluate_p1_shadow(job, a) if a else None
    evidence_items = sorted(
        job.external_evidence,
        key=lambda item: item.published_at or item.collected_at,
        reverse=True,
    )
    evidence_questions = (
        json.loads(job.evidence_analysis.interview_questions_json or "[]")
        if job.evidence_analysis
        else []
    )
    evidence_stale = bool(
        job.evidence_analysis
        and job.evidence_analysis.evidence_signature != evidence_signature(evidence_items)
    )
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "job": job,
            "decoded": decoded,
            "explanation": explanation,
            "evidence_items": evidence_items,
            "evidence_questions": evidence_questions,
            "evidence_stale": evidence_stale,
            "candidate_status": workflow_status(job),
            "workflow_statuses": WORKFLOW_STATUSES,
            "not_applied_reasons": NOT_APPLIED_REASONS,
            "interview_results": INTERVIEW_RESULTS,
            "effective_strategy": effective_final_strategy(job),
            "effective_action": effective_action_type(job),
            "action_label": (
                ACTION_LABELS.get(effective_action_type(job), "待行动层评估")
                if a
                else "待评估"
            ),
            "action_resume_version": (
                recommended_resume_version(
                    effective_action_type(job),
                    a.career_match_level,
                    a.personal_preference_level,
                )
                if a
                else "待评估"
            ),
            "p1_shadow": p1_shadow,
        },
    )


def _evidence_payload(form: dict[str, object], job_id: int | None = None) -> EvidenceCreate:
    return EvidenceCreate(
        company_name=str(form.get("company_name") or "").strip(),
        job_id=job_id,
        source_platform=str(form.get("source_platform") or "other"),
        source_url=str(form.get("source_url") or "").strip() or None,
        source_title=str(form.get("source_title") or "").strip() or None,
        source_author_type=str(form.get("source_author_type") or "").strip() or None,
        published_at=_parse_optional_datetime(str(form.get("published_at") or "")),
        city=str(form.get("city") or "").strip() or None,
        department=str(form.get("department") or "").strip() or None,
        role_name=str(form.get("role_name") or "").strip() or None,
        employment_type=str(form.get("employment_type") or "").strip() or None,
        evidence_text=str(form.get("evidence_text") or "").strip(),
        evidence_category=str(form.get("evidence_category") or "other"),
        evidence_value=str(form.get("evidence_value") or "").strip() or None,
        sentiment=str(form.get("sentiment") or "neutral"),
        source_confidence=str(form.get("source_confidence") or "").strip() or None,
        verification_status=str(form.get("verification_status") or "unverified"),
        user_notes=str(form.get("user_notes") or "").strip() or None,
    )


@app.get("/jobs/{job_id}/evidence/new", response_class=HTMLResponse)
def evidence_new(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    values = {"company_name": job.company_name, "employment_type": job.job_type}
    return templates.TemplateResponse(
        request,
        "evidence_form.html",
        {
            "job": job,
            "values": values,
            "previewed": False,
            "editing": False,
            "error": None,
            **_evidence_options(),
        },
    )


@app.post("/jobs/{job_id}/evidence/preview", response_class=HTMLResponse)
async def evidence_preview(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    form = dict(await request.form())
    text_value = str(form.get("evidence_text") or "").strip()
    if not text_value:
        return templates.TemplateResponse(
            request,
            "evidence_form.html",
            {
                "job": job,
                "values": form,
                "previewed": False,
                "editing": False,
                "error": "请先粘贴外部分享正文或关键内容。",
                **_evidence_options(),
            },
            status_code=400,
        )
    parsed = parse_external_share(text_value, str(form.get("source_title") or "") or None)
    values = {
        **form,
        **{key: value for key, value in parsed.items() if value and not form.get(key)},
    }
    values["company_name"] = values.get("company_name") or job.company_name
    values["detected_categories"] = parsed["detected_categories"]
    duplicates = find_evidence_duplicates(db, {**values, "page_text": text_value})
    return templates.TemplateResponse(
        request,
        "evidence_form.html",
        {
            "job": job,
            "values": values,
            "previewed": True,
            "editing": False,
            "error": None,
            "duplicates": duplicates,
            **_evidence_options(),
        },
    )


@app.post("/jobs/{job_id}/evidence")
async def evidence_create_web(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    form = dict(await request.form())
    try:
        create_evidence(db, _evidence_payload(form, job_id))
    except (ValueError, TypeError) as exc:
        return templates.TemplateResponse(
            request,
            "evidence_form.html",
            {
                "job": job,
                "values": form,
                "previewed": True,
                "editing": False,
                "error": str(exc),
                **_evidence_options(),
            },
            status_code=400,
        )
    return RedirectResponse(f"/jobs/{job_id}#external-evidence", status_code=303)


@app.get("/evidence/{evidence_id}/edit", response_class=HTMLResponse)
def evidence_edit(evidence_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(ExternalEvidence, evidence_id)
    if not item or not item.job_id:
        raise HTTPException(404, "证据不存在")
    values = {
        column.name: getattr(item, column.name) for column in ExternalEvidence.__table__.columns
    }
    if item.published_at:
        values["published_at"] = item.published_at.date().isoformat()
    return templates.TemplateResponse(
        request,
        "evidence_form.html",
        {
            "job": item.job,
            "evidence": item,
            "values": values,
            "previewed": True,
            "editing": True,
            "error": None,
            **_evidence_options(),
        },
    )


@app.post("/evidence/{evidence_id}/edit")
async def evidence_edit_post(evidence_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(ExternalEvidence, evidence_id)
    if not item or not item.job_id:
        raise HTTPException(404, "证据不存在")
    form = dict(await request.form())
    try:
        update_evidence(db, item, _evidence_payload(form, item.job_id))
    except (ValueError, TypeError) as exc:
        return templates.TemplateResponse(
            request,
            "evidence_form.html",
            {
                "job": item.job,
                "evidence": item,
                "values": form,
                "previewed": True,
                "editing": True,
                "error": str(exc),
                **_evidence_options(),
            },
            status_code=400,
        )
    return RedirectResponse(f"/jobs/{item.job_id}#external-evidence", status_code=303)


@app.post("/evidence/{evidence_id}/delete")
def evidence_delete(evidence_id: int, db: Session = Depends(get_db)):
    item = db.get(ExternalEvidence, evidence_id)
    if not item:
        raise HTTPException(404, "证据不存在")
    job_id = item.job_id
    db.delete(item)
    db.commit()
    return (
        RedirectResponse(f"/jobs/{job_id}#external-evidence", status_code=303)
        if job_id
        else RedirectResponse("/", status_code=303)
    )


@app.get("/jobs/{job_id}/evidence-analysis/preview", response_class=HTMLResponse)
def evidence_analysis_preview(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = (
        db.execute(
            select(Job)
            .options(joinedload(Job.assessment), joinedload(Job.external_evidence))
            .where(Job.id == job_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if not job:
        raise HTTPException(404, "岗位不存在")
    result = analyze_evidence(job, job.external_evidence)
    return templates.TemplateResponse(
        request, "evidence_analysis_preview.html", {"job": job, "result": result}
    )


@app.post("/jobs/{job_id}/evidence-analysis/apply")
def evidence_analysis_apply(job_id: int, db: Session = Depends(get_db)):
    job = (
        db.execute(
            select(Job)
            .options(
                joinedload(Job.assessment),
                joinedload(Job.external_evidence),
                joinedload(Job.evidence_analysis),
            )
            .where(Job.id == job_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if not job:
        raise HTTPException(404, "岗位不存在")
    apply_evidence_analysis(db, job, analyze_evidence(job, job.external_evidence))
    return RedirectResponse(f"/jobs/{job_id}#external-evidence", status_code=303)


@app.get("/companies/{company_name}/evidence", response_class=HTMLResponse)
def company_evidence(company_name: str, request: Request, db: Session = Depends(get_db)):
    items = list(
        db.scalars(
            select(ExternalEvidence)
            .where(ExternalEvidence.company_name == company_name)
            .order_by(ExternalEvidence.published_at.desc(), ExternalEvidence.collected_at.desc())
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "company_evidence.html",
        {"company_name": company_name, "items": items, "summary": company_evidence_summary(items)},
    )


@app.post("/api/v1/evidence")
def api_evidence(payload: EvidenceApiSubmission, db: Session = Depends(get_db)):
    parsed = parse_external_share(payload.page_text, payload.source_title)
    company_name = payload.company_name or parsed.get("company_name")
    company_matches = (
        list(
            db.scalars(
                select(Job.company_name).where(Job.company_name.contains(company_name)).distinct()
            ).all()
        )
        if company_name
        else []
    )
    statement = select(Job)
    if payload.job_id:
        statement = statement.where(Job.id == payload.job_id)
    elif company_name:
        statement = statement.where(Job.company_name == company_name)
    else:
        statement = statement.where(Job.id == -1)
    job_matches = list(db.scalars(statement).all())
    duplicate_values = {
        "source_url": payload.source_url,
        "company_name": company_name,
        "page_text": payload.page_text,
    }
    duplicates = find_evidence_duplicates(db, duplicate_values)
    saved_id = None
    if payload.save_confirmed:
        if not company_name:
            raise HTTPException(400, "确认保存前必须补充公司名称")
        evidence = create_evidence(
            db,
            EvidenceCreate(
                company_name=company_name,
                job_id=payload.job_id,
                source_platform=payload.source_platform,
                source_url=payload.source_url,
                source_title=payload.source_title,
                published_at=payload.published_at,
                evidence_text=payload.page_text,
                evidence_category=payload.evidence_category or parsed["evidence_category"],
                evidence_value=payload.evidence_value,
                sentiment=payload.sentiment or parsed["sentiment"],
                verification_status=payload.verification_status or "unverified",
                source_author_type=payload.source_author_type,
                city=payload.city or parsed.get("city"),
                department=payload.department or parsed.get("department"),
                role_name=payload.role_name or parsed.get("role_name"),
                employment_type=payload.employment_type or parsed.get("employment_type"),
                user_notes=payload.user_notes,
            ),
        )
        saved_id = evidence.id
    return {
        "parsed_preview": parsed,
        "possible_companies": company_matches,
        "possible_jobs": [
            {
                "id": job.id,
                "company_name": job.company_name,
                "job_title": job.job_title,
                "city": job.city,
            }
            for job in job_matches
        ],
        "duplicate_evidence": [
            {"id": item.id, "title": item.source_title, "url": item.source_url}
            for item in duplicates
        ],
        "saved_evidence_id": saved_id,
        "requires_user_confirmation": not payload.save_confirmed,
    }


@app.post("/jobs/{job_id}/manual-review")
def save_manual_review(
    job_id: int,
    manual_grade: str = Form(""),
    manual_score: str = Form(""),
    manual_decision: str = Form(""),
    calibration_status: str = Form(""),
    manual_comment: str = Form(""),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job or not job.assessment:
        raise HTTPException(404, "Job not found")
    if len(manual_comment) > 1000:
        raise HTTPException(400, "Demo 评论最多 1000 个字符")
    if manual_grade and manual_grade not in {"A", "B", "C", "D"}:
        raise HTTPException(400, "人工评级无效")
    if manual_decision and manual_decision not in {
        "priority_apply",
        "apply",
        "maybe",
        "do_not_apply",
    }:
        raise HTTPException(400, "人工投递决定无效")
    score = float(manual_score) if manual_score.strip() else None
    if score is not None and not 0 <= score <= 100:
        raise HTTPException(400, "人工分数必须在0至100之间")
    allowed_statuses = {"aligned", "overestimated", "underestimated"}
    if calibration_status not in allowed_statuses:
        calibration_status = _infer_calibration(
            job.assessment.total_score, job.assessment.grade, score, manual_grade
        )
    job.manual_grade = manual_grade or None
    job.manual_score = score
    job.manual_decision = manual_decision or None
    job.manual_comment = manual_comment.strip() or None
    job.reviewed_by_user = True
    job.reviewed_at = datetime.now().astimezone()
    job.calibration_status = calibration_status
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/reassess")
def reassess_one(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    load_config.cache_clear()
    reassess_job(db, job)
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/reassess")
def reassess_batch(
    mode: str = Form("all"),
    job_ids: Annotated[list[int] | None, Form()] = None,
    db: Session = Depends(get_db),
):
    if mode not in {"all", "selected", "disagreement", "travel"}:
        raise HTTPException(400, "重新评分范围无效")
    count = reassess_jobs(db, job_ids=job_ids if mode == "selected" else None, mode=mode)
    return RedirectResponse(
        "/calibration?message=" + quote(f"已重新评分 {count} 个岗位"), status_code=303
    )


@app.post("/jobs/{job_id}/viewed")
def mark_job_viewed(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    job.is_new = False
    job.viewed_at = utcnow()
    job.freshness_status = "viewed"
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def _source_form_values(form: dict[str, object]) -> dict[str, object]:
    def integer(name: str, default: int) -> int:
        return int(str(form.get(name) or default))

    def number(name: str, default: float) -> float:
        return float(str(form.get(name) or default))

    def json_text(name: str) -> str:
        value = str(form.get(name) or "{}").strip() or "{}"
        json.loads(value)
        return value

    return {
        "source_id": str(form.get("source_id") or "").strip(),
        "source_name": str(form.get("source_name") or "").strip(),
        "source_type": str(form.get("source_type") or "generic").strip(),
        "company_name": str(form.get("company_name") or "").strip(),
        "base_url": str(form.get("base_url") or "").strip() or None,
        "board_token": str(form.get("board_token") or "").strip() or None,
        "slug": str(form.get("slug") or "").strip() or None,
        "tenant": str(form.get("tenant") or "").strip() or None,
        "site": str(form.get("site") or "").strip() or None,
        "locale": str(form.get("locale") or "zh_CN").strip(),
        "listing_url": str(form.get("listing_url") or "").strip() or None,
        "detail_url_pattern": str(form.get("detail_url_pattern") or "").strip() or None,
        "request_method": str(form.get("request_method") or "GET").upper(),
        "headers_json": json_text("headers_json"),
        "pagination_json": json_text("pagination_json"),
        "selectors_json": json_text("selectors_json"),
        "priority": integer("priority", 50),
        "collection_interval_hours": integer("collection_interval_hours", 24),
        "request_timeout_seconds": integer("request_timeout_seconds", 15),
        "max_pages": integer("max_pages", 5),
        "request_interval_seconds": number("request_interval_seconds", 1),
        "missing_run_threshold": integer("missing_run_threshold", 3),
        "inactive_days_threshold": integer("inactive_days_threshold", 14),
        "notes": str(form.get("notes") or "").strip() or None,
    }


@app.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request,
    source_type: str | None = None,
    message: str | None = None,
    db: Session = Depends(get_db),
):
    sync_sources_from_yaml(db)
    statement = select(JobSourceConfig).order_by(
        JobSourceConfig.priority.desc(), JobSourceConfig.source_name
    )
    if source_type:
        statement = statement.where(JobSourceConfig.source_type == source_type)
    sources = list(db.scalars(statement).all())
    return templates.TemplateResponse(
        request,
        "sources.html",
        {"sources": sources, "filters": request.query_params, "message": message},
    )


@app.post("/sources")
async def source_create(request: Request, db: Session = Depends(get_db)):
    form = dict(await request.form())
    try:
        values = _source_form_values(form)
        if not values["source_id"] or not values["source_name"] or not values["company_name"]:
            raise ValueError("source_id、来源名称和公司名称不能为空")
        if db.scalar(
            select(JobSourceConfig).where(JobSourceConfig.source_id == values["source_id"])
        ):
            raise ValueError("source_id 已存在")
        db.add(JobSourceConfig(**values))
        db.commit()
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return RedirectResponse("/sources?message=" + quote(f"保存失败：{exc}"), status_code=303)
    return RedirectResponse(
        "/sources?message=" + quote("数据源已保存，默认未启用"), status_code=303
    )


@app.post("/sources/{source_id}/edit")
async def source_edit(source_id: str, request: Request, db: Session = Depends(get_db)):
    source = db.scalar(select(JobSourceConfig).where(JobSourceConfig.source_id == source_id))
    if not source:
        raise HTTPException(404, "数据源不存在")
    form = dict(await request.form())
    try:
        values = _source_form_values({**form, "source_id": source_id})
        values.pop("source_id")
        for key, value in values.items():
            setattr(source, key, value)
        db.commit()
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return RedirectResponse("/sources?message=" + quote(f"更新失败：{exc}"), status_code=303)
    return RedirectResponse("/sources?message=" + quote("数据源配置已更新"), status_code=303)


@app.post("/sources/{source_id}/toggle")
def source_toggle(source_id: str, db: Session = Depends(get_db)):
    source = db.scalar(select(JobSourceConfig).where(JobSourceConfig.source_id == source_id))
    if not source:
        raise HTTPException(404, "数据源不存在")
    source.enabled = not source.enabled
    db.commit()
    return RedirectResponse("/sources", status_code=303)


@app.post("/sources/{source_id}/run")
def source_run_web(
    source_id: str,
    dry_run: bool = Form(False),
    db: Session = Depends(get_db),
):
    source = db.scalar(select(JobSourceConfig).where(JobSourceConfig.source_id == source_id))
    if not source:
        raise HTTPException(404, "数据源不存在")
    run = run_source(db, source, dry_run=dry_run, shenzhen_only=True)
    return RedirectResponse(f"/collection-runs/{run.id}", status_code=303)


@app.post("/sources/run-all")
def sources_run_all_web(dry_run: bool = Form(False), db: Session = Depends(get_db)):
    runs = run_enabled_sources(db, dry_run=dry_run, shenzhen_only=True)
    message = (
        f"已运行 {len(runs)} 个启用来源；失败 {sum(run.status == 'failed' for run in runs)} 个"
    )
    return RedirectResponse("/sources?message=" + quote(message), status_code=303)


@app.get("/collection-runs", response_class=HTMLResponse)
def collection_runs_page(
    request: Request,
    source_id: str | None = None,
    db: Session = Depends(get_db),
):
    statement = (
        select(CollectionRun)
        .options(joinedload(CollectionRun.source))
        .order_by(CollectionRun.started_at.desc())
    )
    if source_id:
        statement = statement.where(CollectionRun.source_id == source_id)
    runs = list(db.scalars(statement).all())
    return templates.TemplateResponse(
        request, "collection_runs.html", {"runs": runs, "filters": request.query_params}
    )


@app.get("/collection-runs/{run_id}", response_class=HTMLResponse)
def collection_run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = (
        db.execute(
            select(CollectionRun)
            .options(joinedload(CollectionRun.source), joinedload(CollectionRun.raw_jobs))
            .where(CollectionRun.id == run_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if not run:
        raise HTTPException(404, "采集记录不存在")
    diagnostics = [collection_record_diagnostic(item) for item in run.raw_jobs]
    return templates.TemplateResponse(
        request,
        "collection_run_detail.html",
        {"run": run, "diagnostics": diagnostics},
    )


@app.get("/candidate-companies", response_class=HTMLResponse)
def candidate_companies_page(
    request: Request,
    message: str | None = None,
    db: Session = Depends(get_db),
):
    companies = list(
        db.scalars(
            select(CandidateCompany).order_by(
                CandidateCompany.user_priority.desc(), CandidateCompany.discovered_at.desc()
            )
        ).all()
    )
    configured_sources: dict[str, list[JobSourceConfig]] = defaultdict(list)
    for source in db.scalars(select(JobSourceConfig).order_by(JobSourceConfig.source_name)):
        configured_sources[source.company_name].append(source)
    return templates.TemplateResponse(
        request,
        "candidate_companies.html",
        {
            "companies": companies,
            "configured_sources": configured_sources,
            "message": message,
        },
    )


@app.post("/candidate-companies")
def candidate_company_create(
    company_name: str = Form(...),
    industry: str = Form(""),
    official_website: str = Form(""),
    careers_url: str = Form(""),
    detected_ats: str = Form("unknown"),
    user_priority: int = Form(50),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    company = discover_company(
        db,
        company_name.strip(),
        discovery_source="user",
        careers_url=careers_url.strip() or None,
        official_website=official_website.strip() or None,
        industry=industry.strip() or None,
        detected_ats=detected_ats or None,
    )
    company.detected_ats = detected_ats or detect_ats(careers_url)
    company.user_priority = user_priority
    company.notes = notes.strip() or None
    db.commit()
    return RedirectResponse("/candidate-companies", status_code=303)


@app.post("/candidate-companies/{company_id}/toggle")
def candidate_company_toggle(company_id: int, db: Session = Depends(get_db)):
    company = db.get(CandidateCompany, company_id)
    if not company:
        raise HTTPException(404, "候选企业不存在")
    company.monitoring_status = "disabled" if company.monitoring_status == "enabled" else "enabled"
    db.commit()
    return RedirectResponse("/candidate-companies", status_code=303)


@app.post("/candidate-companies/{company_id}/edit")
def candidate_company_edit(
    company_id: int,
    industry: str = Form(""),
    official_website: str = Form(""),
    careers_url: str = Form(""),
    detected_ats: str = Form("unknown"),
    user_priority: int = Form(50),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    company = db.get(CandidateCompany, company_id)
    if not company:
        raise HTTPException(404, "候选企业不存在")
    company.official_website = official_website.strip() or None
    company.industry = industry.strip() or None
    company.careers_url = careers_url.strip() or None
    company.detected_ats = detected_ats or detect_ats(careers_url)
    company.user_priority = user_priority
    company.notes = notes.strip() or None
    db.commit()
    return RedirectResponse("/candidate-companies", status_code=303)


@app.post("/candidate-companies/{company_id}/promote")
def candidate_company_promote(company_id: int, db: Session = Depends(get_db)):
    company = db.get(CandidateCompany, company_id)
    if not company:
        raise HTTPException(404, "候选企业不存在")
    source = promote_candidate(db, company)
    return RedirectResponse(
        "/sources?message=" + quote(f"已生成数据源 {source.source_id}，请补全参数后测试"),
        status_code=303,
    )


@app.post("/candidate-companies/{company_id}/test")
def candidate_company_test(company_id: int, db: Session = Depends(get_db)):
    company = db.get(CandidateCompany, company_id)
    if not company:
        raise HTTPException(404, "候选企业不存在")
    source_type = company.detected_ats if company.detected_ats != "unknown" else "generic"
    collector_class = COLLECTORS.get(source_type)
    if not collector_class or not company.careers_url:
        message = "缺少可测试的招聘官网或 ATS 类型"
    else:
        config = {
            "source_name": f"{company.company_name} 测试",
            "source_type": source_type,
            "company_name": company.company_name,
            "base_url": company.careers_url,
            "listing_url": company.careers_url,
            "request_timeout_seconds": 5,
            "request_interval_seconds": 0,
            "max_pages": 1,
            **ats_config_from_url(company.careers_url, source_type),
        }
        collector = collector_class(config)
        try:
            count = len(collector.collect())
            message = f"测试成功，发现 {count} 个公开职位；尚未写入岗位表"
        except Exception as exc:
            message = f"测试失败：{exc}"
        finally:
            collector.close()
    return RedirectResponse("/candidate-companies?message=" + quote(message), status_code=303)


@app.get("/calibration", response_class=HTMLResponse)
def calibration_page(
    request: Request,
    status: str | None = None,
    travel: bool = False,
    incomplete_benefits: bool = False,
    job_type: str | None = None,
    sort: str = "difference",
    profile: str | None = None,
    message: str | None = None,
    include_inactive: bool = False,
    include_test: bool = False,
    db: Session = Depends(get_db),
):
    statement = select(Job).options(joinedload(Job.assessment)).join(JobAssessment)
    statement = apply_effective_job_filters(
        statement,
        include_inactive=include_inactive,
        include_test=include_test,
    )
    if status == "unreviewed":
        statement = statement.where(Job.reviewed_by_user.is_(False))
    elif status:
        statement = statement.where(Job.calibration_status == status)
    if travel:
        statement = statement.where(Job.travel_level.notin_(["unknown", "travel_level_0"]))
    if incomplete_benefits:
        statement = statement.where(
            (Job.working_schedule.in_(["not_disclosed", "unclear"]))
            | (Job.five_insurances_housing_fund.in_(["not_disclosed", "unclear"]))
        )
    if job_type:
        statement = statement.where(Job.job_type == job_type)
    if profile == "fit_incomplete":
        statement = statement.where(
            JobAssessment.fit_score >= 65,
            JobAssessment.information_completeness < 60,
        )
    elif profile == "opportunity_incomplete":
        statement = statement.where(
            JobAssessment.opportunity_score >= 70,
            JobAssessment.information_completeness < 60,
        )
    elif profile == "system_no_manual_yes":
        statement = statement.where(
            JobAssessment.application_recommendation == "do_not_apply",
            Job.manual_decision.in_(["priority_apply", "apply"]),
        )
    elif profile == "quality_internship":
        statement = statement.where(
            Job.job_type == "internship",
            JobAssessment.fit_score >= 65,
            JobAssessment.opportunity_score >= 68,
        )
    elif profile == "many_confirmations":
        statement = statement.where(JobAssessment.information_completeness < 50)
    elif profile == "growth_high_risk":
        statement = statement.where(
            JobAssessment.company_type == "growth_company",
            JobAssessment.opportunity_score >= 65,
            JobAssessment.risk_level.in_(["medium", "high"]),
        )
    elif profile == "stable_balanced":
        statement = statement.where(
            JobAssessment.company_type.in_(["mature_large_company", "multinational_company"]),
            JobAssessment.opportunity_score >= 60,
            JobAssessment.risk_level == "low",
        )
    jobs = list(db.scalars(statement).unique())
    if sort == "system":
        jobs.sort(key=lambda item: item.assessment.total_score, reverse=True)
    else:
        jobs.sort(
            key=lambda item: (
                abs(item.assessment.total_score - item.manual_score)
                if item.manual_score is not None
                else -1
            ),
            reverse=True,
        )
    stats = _calibration_stats(jobs)
    return templates.TemplateResponse(
        request,
        "calibration.html",
        {"jobs": jobs, "stats": stats, "message": message, "filters": request.query_params},
    )


@app.post("/jobs/{job_id}/status")
def update_status(job_id: int, status: Annotated[str, Form()], db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    allowed = {
        "待评估",
        "待投递",
        "已投递",
        "已联系",
        "一面",
        "二面",
        "Offer",
        "拒绝",
        "主动放弃",
        "已失效",
    }
    if not job or status not in allowed:
        raise HTTPException(400, "Invalid job or status")
    job.application_status = status
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/workflow")
def update_candidate_workflow(
    job_id: int,
    status: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    try:
        update_workflow_status(db, job, status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}#candidate-workflow", status_code=303)


@app.post("/jobs/{job_id}/feedback")
def update_application_feedback(
    job_id: int,
    applied: Annotated[str, Form()] = "",
    not_applied_reason: Annotated[str, Form()] = "",
    interview_result: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if len(notes) > 1000:
        raise HTTPException(400, "Demo 反馈最多 1000 个字符")
    applied_value = True if applied == "yes" else False if applied == "no" else None
    try:
        save_application_feedback(
            db,
            job,
            applied=applied_value,
            not_applied_reason=not_applied_reason or None,
            interview_result=interview_result or None,
            notes=notes or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}#application-feedback", status_code=303)


@app.post("/api/v1/jobs", response_model=JobOut, status_code=201)
def api_create_job(payload: JobCreate, db: Session = Depends(get_db)):
    job, _ = create_or_merge_job(db, payload)
    return job


@app.post("/api/v1/import/csv")
async def api_import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV is supported")
    return import_csv(db, await file.read())


@app.post("/import")
async def web_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    import_csv(db, await file.read())
    return RedirectResponse("/", status_code=303)


@app.get("/export.csv")
def web_export(db: Session = Depends(get_db)):
    content = export_csv(query_jobs(db))
    return Response(
        "\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=jobs-export.csv"},
    )


@app.get("/backup.json")
def backup_all(db: Session = Depends(get_db)):
    content = json.dumps(create_backup(db), ensure_ascii=False, indent=2, default=str)
    filename = f"job-compass-backup-{datetime.now():%Y%m%d-%H%M%S}.json"
    return Response(
        content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/restore")
async def restore_all(
    file: UploadFile = File(...),
    overwrite: bool = Form(False),
    db: Session = Depends(get_db),
):
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(400, "Only JSON backup files are supported")
    try:
        result = restore_backup(db, await file.read(), overwrite=overwrite)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    message = (
        f"恢复完成：新增 {result['created']}，跳过 {result['skipped']}，"
        f"覆盖 {result['overwritten']}，错误 {result['errors']}"
    )
    return RedirectResponse("/?message=" + quote(message), status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "ai_analyzer_enabled": settings.ai_analyzer_enabled}


@app.post("/internal/stop", include_in_schema=False)
def internal_stop(
    x_job_compass_token: str | None = Header(None),
):
    expected = os.getenv("JOB_COMPASS_STOP_TOKEN")
    if not expected or x_job_compass_token != expected:
        raise HTTPException(403, "Invalid stop token")
    timer = threading.Timer(0.5, os.kill, args=(os.getpid(), signal.SIGTERM))
    timer.daemon = True
    timer.start()
    return {"status": "stopping"}
