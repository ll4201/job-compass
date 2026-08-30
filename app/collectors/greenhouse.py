from html import unescape
import re

from app.collectors.base import BaseJobCollector, CollectorError, parse_datetime
from app.location import greenhouse_location_payload, greenhouse_raw_location
from app.schemas import RawCollectedJob


def _plain_html(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(value or ""))).strip()


class GreenhouseCollector(BaseJobCollector):
    source_type = "greenhouse"

    def collect(self) -> list[RawCollectedJob]:
        token = self.config.get("board_token")
        if not token:
            raise CollectorError("Greenhouse 数据源缺少 board_token")
        base = self.config.get("base_url") or "https://boards-api.greenhouse.io"
        url = f"{base.rstrip('/')}/v1/boards/{token}/jobs?content=true"
        payload = self.get_json(url)
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        return [
            RawCollectedJob(
                source_name=self.config["source_name"],
                source_type=self.source_type,
                source_job_id=str(item.get("id")) if item.get("id") is not None else None,
                source_url=item.get("absolute_url"),
                company_name=self.config["company_name"],
                job_title=item.get("title") or "未命名职位",
                location_raw=greenhouse_raw_location(item),
                job_type="internship"
                if "intern" in (item.get("title") or "").casefold()
                or "实习" in (item.get("title") or "")
                else "full_time",
                description_raw=_plain_html(item.get("content")),
                published_at=parse_datetime(item.get("updated_at") or item.get("created_at")),
                raw_payload=item,
                source_location_payload=greenhouse_location_payload(item),
                source_confidence="high",
            )
            for item in jobs
        ]
