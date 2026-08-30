from html import unescape
import re

from app.collectors.base import BaseJobCollector, CollectorError, parse_datetime
from app.schemas import RawCollectedJob


def _text(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(value or ""))).strip()


def _location(categories: dict, item: dict) -> str:
    all_locations = categories.get("allLocations")
    if isinstance(all_locations, list) and len(all_locations) > 1:
        return "; ".join(str(part) for part in all_locations if part)
    value = categories.get("location") or item.get("location") or ""
    if isinstance(value, list):
        return "; ".join(str(part) for part in value if part)
    return str(value)


class LeverCollector(BaseJobCollector):
    source_type = "lever"

    def collect(self) -> list[RawCollectedJob]:
        slug = self.config.get("slug")
        if not slug:
            raise CollectorError("Lever 数据源缺少 slug")
        base = self.config.get("base_url") or "https://api.lever.co"
        url = f"{base.rstrip('/')}/v0/postings/{slug}?mode=json"
        payload = self.get_json(url)
        if not isinstance(payload, list):
            raise CollectorError("Lever 公开接口响应格式无法识别")
        results = []
        for item in payload:
            categories = item.get("categories") or {}
            description = " ".join(
                filter(
                    None,
                    [
                        _text(item.get("description")),
                        _text(item.get("descriptionPlain")),
                        *[_text(section.get("content")) for section in item.get("lists", [])],
                        _text(item.get("additional")),
                    ],
                )
            )
            commitment = categories.get("commitment") or ""
            title = item.get("text") or "未命名职位"
            results.append(
                RawCollectedJob(
                    source_name=self.config["source_name"],
                    source_type=self.source_type,
                    source_job_id=str(item.get("id")) if item.get("id") else None,
                    source_url=item.get("hostedUrl") or item.get("applyUrl"),
                    company_name=self.config["company_name"],
                    job_title=title,
                    location_raw=_location(categories, item),
                    job_type="internship"
                    if "intern" in f"{commitment} {title}".casefold() or "实习" in title
                    else "full_time",
                    employment_type=commitment or None,
                    department=categories.get("team") or categories.get("department"),
                    description_raw=description,
                    published_at=parse_datetime(item.get("createdAt")),
                    raw_payload=item,
                    source_location_payload={
                        "location": categories.get("location"),
                        "allLocations": categories.get("allLocations"),
                        "workplaceType": item.get("workplaceType"),
                    },
                    source_confidence="high",
                )
            )
        return results
