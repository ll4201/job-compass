import json
import re
import hashlib
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import load_config
from app.models import CandidateCompany, Job, JobSourceConfig


def detect_ats(url: str | None) -> str:
    lowered = (url or "").casefold()
    if "greenhouse.io" in lowered:
        return "greenhouse"
    if "lever.co" in lowered:
        return "lever"
    if "myworkdayjobs.com" in lowered or "/wday/cxs/" in lowered:
        return "workday"
    return "custom" if lowered else "unknown"


def discover_company(
    db: Session,
    company_name: str,
    *,
    discovery_source: str,
    careers_url: str | None = None,
    official_website: str | None = None,
    industry: str | None = None,
    detected_ats: str | None = None,
) -> CandidateCompany:
    company = db.scalar(
        select(CandidateCompany).where(CandidateCompany.company_name == company_name)
    )
    if company is None:
        company = CandidateCompany(
            company_name=company_name,
            discovery_source=discovery_source,
            careers_url=careers_url,
            official_website=official_website,
            industry=industry,
            detected_ats=detected_ats or detect_ats(careers_url),
        )
        db.add(company)
    else:
        if careers_url and not company.careers_url:
            company.careers_url = careers_url
            company.detected_ats = detect_ats(careers_url)
        if official_website and not company.official_website:
            company.official_website = official_website
        if industry and not company.industry:
            company.industry = industry
        if detected_ats and company.detected_ats in {"unknown", "custom"}:
            company.detected_ats = detected_ats
    return company


def ats_config_from_url(url: str | None, source_type: str | None = None) -> dict[str, str]:
    """Extract public ATS identifiers from an official recruiting URL."""
    if not url:
        return {}
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    parts = [part for part in parsed.path.split("/") if part]
    ats = source_type if source_type and source_type != "unknown" else detect_ats(url)
    if ats == "greenhouse":
        if "boards-api.greenhouse.io" in host:
            try:
                token = parts[parts.index("boards") + 1]
            except (ValueError, IndexError):
                token = ""
        else:
            token = parts[0] if parts else ""
        return {"base_url": "https://boards-api.greenhouse.io", "board_token": token}
    if ats == "lever":
        api_base = "https://api.eu.lever.co" if ".eu.lever.co" in host else "https://api.lever.co"
        if "api.lever.co" in host:
            try:
                slug = parts[parts.index("postings") + 1]
            except (ValueError, IndexError):
                slug = ""
        else:
            slug = parts[0] if parts else ""
        return {"base_url": api_base, "slug": slug}
    if ats == "workday":
        tenant = host.split(".", 1)[0]
        site_parts = parts[1:] if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]) else parts
        site = site_parts[0] if site_parts else ""
        return {
            "base_url": f"{parsed.scheme or 'https'}://{parsed.netloc}",
            "tenant": tenant,
            "site": site,
        }
    return {"listing_url": url}


def source_to_config(source: JobSourceConfig) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "source_name": source.source_name,
        "source_type": source.source_type,
        "company_name": source.company_name,
        "base_url": source.base_url,
        "board_token": source.board_token,
        "slug": source.slug,
        "tenant": source.tenant,
        "site": source.site,
        "locale": source.locale,
        "listing_url": source.listing_url,
        "detail_url_pattern": source.detail_url_pattern,
        "request_method": source.request_method,
        "headers": json.loads(source.headers_json or "{}"),
        "pagination": json.loads(source.pagination_json or "{}"),
        "selectors": json.loads(source.selectors_json or "{}"),
        "enabled": source.enabled,
        "priority": source.priority,
        "collection_interval_hours": source.collection_interval_hours,
        "request_timeout_seconds": source.request_timeout_seconds,
        "max_pages": source.max_pages,
        "request_interval_seconds": source.request_interval_seconds,
        "missing_run_threshold": source.missing_run_threshold,
        "inactive_days_threshold": source.inactive_days_threshold,
        "notes": source.notes,
    }


def _source_values(item: dict[str, Any]) -> dict[str, Any]:
    known = {
        "source_id",
        "source_name",
        "source_type",
        "company_name",
        "base_url",
        "board_token",
        "slug",
        "tenant",
        "site",
        "locale",
        "listing_url",
        "detail_url_pattern",
        "request_method",
        "enabled",
        "priority",
        "collection_interval_hours",
        "request_timeout_seconds",
        "max_pages",
        "request_interval_seconds",
        "missing_run_threshold",
        "inactive_days_threshold",
        "notes",
    }
    values = {key: value for key, value in item.items() if key in known}
    values["headers_json"] = json.dumps(item.get("headers") or {}, ensure_ascii=False)
    values["pagination_json"] = json.dumps(item.get("pagination") or {}, ensure_ascii=False)
    values["selectors_json"] = json.dumps(item.get("selectors") or {}, ensure_ascii=False)
    return values


def sync_sources_from_yaml(db: Session) -> int:
    config = load_config("source_config.yaml")
    created = 0
    for item in config.get("sources", []):
        existing = db.scalar(
            select(JobSourceConfig).where(JobSourceConfig.source_id == item["source_id"])
        )
        if existing is None:
            db.add(JobSourceConfig(**_source_values(item)))
            created += 1
        if not item.get("is_example", False):
            company = discover_company(
                db,
                item["company_name"],
                discovery_source="source_config",
                careers_url=item.get("careers_url") or item.get("listing_url") or item.get("base_url"),
                official_website=item.get("official_website"),
                industry=item.get("industry"),
                detected_ats=item.get("source_type"),
            )
            company.monitoring_status = "enabled" if item.get("enabled") else "configured"
    db.commit()
    return created


def backfill_candidate_companies(db: Session) -> int:
    created = 0
    existing_names = set(db.scalars(select(CandidateCompany.company_name)).all())
    jobs = list(db.scalars(select(Job).order_by(Job.first_seen_at)).all())
    for job in jobs:
        if job.company_name not in existing_names:
            discover_company(
                db,
                job.company_name,
                discovery_source="historical_job",
                careers_url=job.source_url,
            )
            existing_names.add(job.company_name)
            created += 1
    db.commit()
    return created


def source_id_for(company_name: str, source_type: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", company_name.casefold()).strip("-") or "company"
    suffix = hashlib.sha1(company_name.encode()).hexdigest()[:8]
    return f"{base}-{suffix}-{source_type}"


def promote_candidate(db: Session, company: CandidateCompany) -> JobSourceConfig:
    source_type = company.detected_ats if company.detected_ats != "unknown" else "generic"
    source_id = source_id_for(company.company_name, source_type)
    existing = db.scalar(select(JobSourceConfig).where(JobSourceConfig.source_id == source_id))
    if existing:
        return existing
    inferred = ats_config_from_url(company.careers_url, source_type)
    values: dict[str, Any] = {
        "source_id": source_id,
        "source_name": f"{company.company_name} 公开招聘",
        "source_type": source_type,
        "company_name": company.company_name,
        "base_url": company.careers_url,
        "listing_url": company.careers_url,
        "enabled": company.monitoring_status == "enabled",
        "priority": company.user_priority,
        "notes": company.notes,
        **inferred,
    }
    source = JobSourceConfig(**values)
    db.add(source)
    company.monitoring_status = "configured"
    db.commit()
    return source
