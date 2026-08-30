from app.collectors.base import (
    BaseJobCollector,
    CollectorError,
    PublicJobNotFound,
    parse_datetime,
)
from app.schemas import RawCollectedJob
from urllib.parse import urljoin


class WorkdayCollector(BaseJobCollector):
    source_type = "workday"

    def collect(self) -> list[RawCollectedJob]:
        required = ["tenant", "site", "base_url"]
        missing = [name for name in required if not self.config.get(name)]
        if missing:
            raise CollectorError(f"Workday 数据源缺少配置：{', '.join(missing)}")
        base = self.config["base_url"].rstrip("/")
        endpoint = f"{base}/wday/cxs/{self.config['tenant']}/{self.config['site']}/jobs"
        pagination = self.config.get("pagination") or {}
        limit = int(pagination.get("page_size", 20))
        max_pages = int(self.config.get("max_pages", 5))
        results: list[RawCollectedJob] = []
        for page in range(max_pages):
            payload = self.post_json(
                endpoint,
                {
                    "appliedFacets": pagination.get("applied_facets") or {},
                    "limit": limit,
                    "offset": page * limit,
                    "searchText": pagination.get("search_text") or "",
                },
            )
            postings = payload.get("jobPostings", []) if isinstance(payload, dict) else []
            for item in postings:
                external_path = item.get("externalPath") or ""
                bullet_fields = item.get("bulletFields") or []
                detail_url = (
                    f"{base}/wday/cxs/{self.config['tenant']}/{self.config['site']}"
                    f"/{external_path.lstrip('/')}"
                    if external_path
                    else None
                )
                source_job_id = str((bullet_fields[0] if bullet_fields else None) or external_path)
                try:
                    detail = self.get_json(detail_url) if detail_url else {}
                except PublicJobNotFound:
                    if source_job_id:
                        self.closed_source_job_ids.add(source_job_id)
                    continue
                info = detail.get("jobPostingInfo", detail) if isinstance(detail, dict) else {}
                locations = item.get("locationsText") or info.get("location") or ""
                if isinstance(locations, list):
                    locations = "; ".join(str(value) for value in locations if value)
                source_url = info.get("externalUrl") or detail_url
                if source_url:
                    source_url = urljoin(f"{base}/", source_url)
                title = item.get("title") or info.get("title") or "未命名职位"
                results.append(
                    RawCollectedJob(
                        source_name=self.config["source_name"],
                        source_type=self.source_type,
                        source_job_id=str(info.get("jobReqId") or source_job_id),
                        source_url=source_url,
                        company_name=self.config["company_name"],
                        job_title=title,
                        location_raw=locations,
                        job_type="internship"
                        if "intern" in title.casefold() or "实习" in title
                        else "full_time",
                        description_raw=info.get("jobDescription") or "",
                        published_at=parse_datetime(info.get("startDate") or item.get("postedOn")),
                        raw_payload={"listing": item, "detail": detail},
                        source_location_payload={
                            "locationsText": item.get("locationsText"),
                            "location": info.get("location"),
                            "additionalLocations": info.get("additionalLocations"),
                        },
                        source_confidence="high",
                    )
                )
            total = payload.get("total", len(postings)) if isinstance(payload, dict) else 0
            if not postings or (page + 1) * limit >= total:
                break
        return results
