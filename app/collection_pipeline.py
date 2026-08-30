import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors import COLLECTORS, BaseJobCollector, CollectorError
from app.location import (
    evaluate_job_location_evidence,
    evaluate_location,
    greenhouse_location_payload,
    greenhouse_raw_location,
)
from app.models import (
    CollectionRun,
    Job,
    JobSource,
    JobSourceConfig,
    RawCollectedJobRecord,
    utcnow,
)
from app.normalizer import normalize_job
from app.schemas import JobCreate, RawCollectedJob
from app.services import create_or_merge_job, find_duplicate, reassess_job
from app.source_management import discover_company, source_to_config


def classify_shenzhen_location(location: str, description: str = "") -> str:
    """Compatibility wrapper for callers that only need the location status."""
    return evaluate_location(location, description=description).location_status


def _config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _raw_record(
    run: CollectionRun, source: JobSourceConfig, item: RawCollectedJob
) -> RawCollectedJobRecord:
    source_payload = item.source_location_payload
    if source_payload is None and item.source_type == "greenhouse":
        source_payload = greenhouse_location_payload(item.raw_payload)
    evidence = evaluate_job_location_evidence(
        title=item.job_title,
        raw_location=item.location_raw,
        source_location_payload=source_payload,
        description=item.description_raw,
    )
    return RawCollectedJobRecord(
        collection_run_id=run.id,
        source_id=source.source_id,
        source_job_id=item.source_job_id,
        source_url=item.source_url,
        raw_payload=json.dumps(item.raw_payload, ensure_ascii=False, default=str),
        raw_text=item.description_raw,
        job_title=item.job_title,
        raw_location=item.location_raw,
        source_location_payload=json.dumps(source_payload or {}, ensure_ascii=False, default=str),
        normalized_location=evidence.normalized_location,
        location_status=evidence.location_status,
        location_reason=evidence.location_conflict_reason
        or ("地点证据一致且明确为深圳" if evidence.location_status == "confirmed_shenzhen" else "地点证据未指向深圳"),
        collected_at=item.collected_at,
    )


def collection_record_diagnostic(record: RawCollectedJobRecord) -> dict[str, Any]:
    """Return complete diagnostics, including for records created before these columns existed."""
    try:
        payload = json.loads(record.raw_payload or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    source_payload = greenhouse_location_payload(payload)
    job_title = record.job_title or (payload.get("title") if isinstance(payload, dict) else "") or ""
    raw_location = record.raw_location or greenhouse_raw_location(payload)
    evidence = evaluate_job_location_evidence(
        title=job_title,
        raw_location=raw_location,
        source_location_payload=source_payload,
        description=record.raw_text,
    )
    return {
        "record": record,
        "job_title": job_title,
        "raw_location": record.raw_location or raw_location,
        "source_location_payload": record.source_location_payload
        or json.dumps(source_payload, ensure_ascii=False, default=str),
        "normalized_location": evidence.normalized_location,
        "location_status": evidence.location_status,
        "location_reason": evidence.location_conflict_reason
        or record.location_reason
        or "地点证据已重新计算",
        "source_url": record.source_url,
    }


def refresh_imported_location_evidence(
    db: Session, source_id: str
) -> list[Job]:
    """Backfill location evidence from the latest raw record without replacing jobs."""
    jobs = list(
        db.scalars(select(Job).where(Job.sources.any(JobSource.source_id == source_id))).all()
    )
    if not jobs:
        return []
    records = list(
        db.scalars(
            select(RawCollectedJobRecord)
            .where(
                RawCollectedJobRecord.source_id == source_id,
                RawCollectedJobRecord.imported_job_id.in_([job.id for job in jobs]),
            )
            .order_by(RawCollectedJobRecord.collection_run_id.desc())
        ).all()
    )
    latest: dict[int | None, RawCollectedJobRecord] = {}
    for record in records:
        latest.setdefault(record.imported_job_id, record)
    for job in jobs:
        record = latest.get(job.id)
        if record is None:
            continue
        try:
            payload = json.loads(record.raw_payload or "{}")
        except json.JSONDecodeError:
            payload = {}
        evidence = evaluate_job_location_evidence(
            title=job.job_title,
            raw_location=greenhouse_raw_location(payload) or job.location_raw,
            source_location_payload=greenhouse_location_payload(payload),
            description=record.raw_text or job.description,
        )
        for key, value in evidence.model_dump().items():
            if key != "location_status":
                setattr(job, key, value)
        job.workplace_status = (
            "needs_confirmation" if evidence.location_conflict else evidence.location_status
        )
        job.city = "深圳" if "Shenzhen" in evidence.normalized_location else None
    return jobs


def _job_payload(source: JobSourceConfig, item: RawCollectedJob) -> dict[str, Any]:
    source_payload = item.source_location_payload
    if source_payload is None and item.source_type == "greenhouse":
        source_payload = greenhouse_location_payload(item.raw_payload)
    location = evaluate_job_location_evidence(
        title=item.job_title,
        raw_location=item.location_raw,
        source_location_payload=source_payload,
        description=item.description_raw,
    )
    return JobCreate(
        source=source.source_id,
        source_job_id=item.source_job_id,
        source_url=item.source_url,
        company_name=item.company_name,
        job_title=item.job_title,
        job_type=item.job_type,
        employment_type=item.employment_type,
        location_raw=item.location_raw,
        title_location=location.title_location or None,
        structured_location=location.structured_location or None,
        office_location=location.office_location or None,
        jd_location=location.jd_location or None,
        normalized_location=location.normalized_location or None,
        location_conflict=location.location_conflict,
        location_conflict_reason=location.location_conflict_reason or None,
        description=item.description_raw,
        published_at=item.published_at,
    ).model_dump()


def _source_link(job: Job, source: JobSourceConfig, item: RawCollectedJob) -> JobSource:
    link = next(
        (
            value
            for value in job.sources
            if value.source_id == source.source_id
            and (
                not item.source_job_id
                or value.source_job_id == item.source_job_id
                or value.source_url == item.source_url
            )
        ),
        None,
    )
    if link is None:
        link = JobSource(
            source_id=source.source_id,
            source=source.source_type,
            source_job_id=item.source_job_id,
            source_url=item.source_url,
        )
        job.sources.append(link)
    link.last_seen_at = utcnow()
    link.last_checked_at = utcnow()
    link.last_verified_at = utcnow()
    link.is_active = True
    link.missing_run_count = 0
    link.availability_status = "active"
    link.closure_reason = None
    return link


def _choose_primary_source(
    db: Session,
    job: Job,
    source: JobSourceConfig,
    link: JobSource,
    item: RawCollectedJob,
) -> None:
    primary = next((value for value in job.sources if value.is_primary), None)
    if primary and primary.source == "manual":
        return
    current_priority = -1
    if primary and primary.source_id:
        current = db.scalar(
            select(JobSourceConfig).where(JobSourceConfig.source_id == primary.source_id)
        )
        current_priority = current.priority if current else -1
    if primary is None or source.priority > current_priority:
        for value in job.sources:
            value.is_primary = False
        link.is_primary = True
        job.source = source.source_id
        job.source_job_id = item.source_job_id
        job.source_url = item.source_url


def _apply_automatic_update(db: Session, job: Job, data: dict[str, Any]) -> bool:
    if job.source == "manual" or any(
        link.is_primary and link.source == "manual" for link in job.sources
    ):
        return False
    normalized = normalize_job(data)
    if job.content_hash == normalized["content_hash"]:
        return False
    preserved = {
        "id",
        "source",
        "source_job_id",
        "source_url",
        "application_status",
        "manual_grade",
        "manual_score",
        "manual_decision",
        "manual_comment",
        "reviewed_by_user",
        "reviewed_at",
        "calibration_status",
        "created_at",
        "first_seen_at",
        "is_new",
        "viewed_at",
    }
    allowed = {column.name for column in Job.__table__.columns} - preserved
    for key, value in normalized.items():
        if key in allowed:
            setattr(job, key, value)
    reassess_job(db, job)
    return True


def _finish_seen_job(job: Job) -> None:
    now = utcnow()
    job.last_seen_at = now
    job.last_checked_at = now
    job.last_verified_at = now
    job.is_active = True
    job.availability_status = "active"
    job.closure_reason = None
    job.missing_run_count = 0
    job.source_count = len(job.sources)
    age = now - job.first_seen_at.replace(tzinfo=job.first_seen_at.tzinfo or timezone.utc)
    job.freshness_status = (
        "new" if job.is_new else "recent" if age <= timedelta(days=7) else "existing"
    )


def update_missing_for_source(
    db: Session, source: JobSourceConfig, seen_source_job_ids: set[str]
) -> None:
    links = list(db.scalars(select(JobSource).where(JobSource.source_id == source.source_id)).all())
    for link in links:
        if link.source_job_id and link.source_job_id in seen_source_job_ids:
            continue
        checked_at = utcnow()
        link.last_checked_at = checked_at
        link.last_verified_at = checked_at
        link.missing_run_count += 1
        link.closure_reason = f"missing_from_complete_source_listing:{link.missing_run_count}"
        if link.missing_run_count >= source.missing_run_threshold:
            link.availability_status = "possibly_closed"
            link.is_active = False
        job = link.job
        job.last_checked_at = checked_at
        job.last_verified_at = checked_at
        job.missing_run_count = max((item.missing_run_count for item in job.sources), default=0)
        if not any(item.is_active for item in job.sources):
            job.availability_status = "possibly_closed"
            job.is_active = False
            job.closure_reason = link.closure_reason


def mark_source_jobs_closed(db: Session, source: JobSourceConfig, source_job_ids: set[str]) -> int:
    if not source_job_ids:
        return 0
    links = list(
        db.scalars(
            select(JobSource).where(
                JobSource.source_id == source.source_id,
                JobSource.source_job_id.in_(source_job_ids),
            )
        ).all()
    )
    for link in links:
        link.is_active = False
        link.availability_status = "closed"
        checked_at = utcnow()
        link.last_checked_at = checked_at
        link.last_verified_at = checked_at
        link.closure_reason = "official_detail_reported_closed"
        job = link.job
        if not any(item.is_active for item in job.sources):
            job.is_active = False
            job.availability_status = "closed"
            job.last_checked_at = checked_at
            job.last_verified_at = checked_at
            job.closure_reason = link.closure_reason
    return len(links)


def run_source(
    db: Session,
    source: JobSourceConfig,
    *,
    dry_run: bool = False,
    shenzhen_only: bool = True,
    collector: BaseJobCollector | None = None,
) -> CollectionRun:
    config = source_to_config(source)
    run = CollectionRun(
        source_id=source.source_id,
        dry_run=dry_run,
        config_hash=_config_hash(config),
    )
    db.add(run)
    db.flush()
    owned_collector = collector is None
    try:
        collector_class = COLLECTORS.get(source.source_type)
        if collector is None:
            if collector_class is None:
                raise CollectorError(f"不支持的数据源类型：{source.source_type}")
            collector = collector_class(config)
        items = collector.collect()
        run.discovered_count = len(items)
        seen_ids: set[str] = set()
        for item in items:
            record = _raw_record(run, source, item)
            db.add(record)
            db.flush()
            try:
                location_status = record.location_status
                record.location_status = location_status
                if item.source_job_id:
                    seen_ids.add(item.source_job_id)
                if location_status == "confirmed_shenzhen":
                    run.shenzhen_count += 1
                if location_status != "confirmed_shenzhen":
                    record.normalized_status = "filtered_location"
                    run.filtered_count += 1
                    continue
                if dry_run:
                    record.normalized_status = "dry_run"
                    continue
                payload = _job_payload(source, item)
                normalized = normalize_job(payload.copy())
                duplicate = find_duplicate(db, normalized)
                if duplicate:
                    updated = _apply_automatic_update(db, duplicate, payload)
                    link = _source_link(duplicate, source, item)
                    _choose_primary_source(db, duplicate, source, link, item)
                    _finish_seen_job(duplicate)
                    record.imported_job_id = duplicate.id
                    record.normalized_status = "updated" if updated else "duplicate"
                    run.updated_count += int(updated)
                    run.duplicate_count += int(not updated)
                    job = duplicate
                else:
                    job, _ = create_or_merge_job(db, payload)
                    link = _source_link(job, source, item)
                    _choose_primary_source(db, job, source, link, item)
                    job.is_new = True
                    job.freshness_status = "new"
                    _finish_seen_job(job)
                    record.imported_job_id = job.id
                    record.normalized_status = "imported"
                    run.imported_count += 1
                discover_company(
                    db,
                    item.company_name,
                    discovery_source=source.source_id,
                    careers_url=source.base_url or source.listing_url,
                )
            except (ValueError, TypeError) as exc:
                record.normalized_status = "failed"
                record.error_message = str(exc)
                run.failed_count += 1
        if not dry_run and run.failed_count == 0:
            update_missing_for_source(db, source, seen_ids)
            mark_source_jobs_closed(db, source, getattr(collector, "closed_source_job_ids", set()))
        run.status = "partial" if run.failed_count else "success"
    except Exception as exc:  # single-source isolation boundary
        run.status = "failed"
        run.failed_count += 1
        run.error_summary = str(exc)
    finally:
        if owned_collector and collector is not None:
            collector.close()
        run.finished_at = utcnow()
        source.last_run_at = run.finished_at
        source.last_status = run.status
        source.last_error = run.error_summary
        db.commit()
    return run


def run_enabled_sources(
    db: Session, *, dry_run: bool = False, shenzhen_only: bool = True
) -> list[CollectionRun]:
    sources = list(
        db.scalars(
            select(JobSourceConfig)
            .where(JobSourceConfig.enabled.is_(True))
            .order_by(JobSourceConfig.priority.desc())
        ).all()
    )
    return [
        run_source(db, source, dry_run=dry_run, shenzhen_only=shenzhen_only) for source in sources
    ]


def check_inactive_jobs(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    possibly_closed = closed = 0
    jobs = list(db.scalars(select(Job)).all())
    for job in jobs:
        automated_links = [
            link for link in job.sources if link.source_id and link.source != "manual"
        ]
        if not automated_links:
            continue
        thresholds = []
        for link in automated_links:
            source = db.scalar(
                select(JobSourceConfig).where(JobSourceConfig.source_id == link.source_id)
            )
            if source:
                thresholds.append(source.inactive_days_threshold)
        threshold = min(thresholds, default=14)
        last_seen = job.last_seen_at.replace(tzinfo=job.last_seen_at.tzinfo or timezone.utc)
        age_days = (now - last_seen).days
        if age_days >= threshold and not any(link.is_active for link in automated_links):
            job.availability_status = "closed"
            job.is_active = False
            job.last_verified_at = now
            job.closure_reason = f"missing_from_source_for_{age_days}_days"
            closed += 1
        elif job.missing_run_count >= 1 and not any(link.is_active for link in automated_links):
            job.availability_status = "possibly_closed"
            job.last_verified_at = now
            job.closure_reason = f"missing_from_complete_source_listing:{job.missing_run_count}"
            possibly_closed += 1
    db.commit()
    return {"possibly_closed": possibly_closed, "closed": closed}
