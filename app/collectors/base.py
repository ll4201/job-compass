import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.schemas import RawCollectedJob


class CollectorError(RuntimeError):
    pass


class PublicJobNotFound(CollectorError):
    """A public official endpoint explicitly says a known job no longer exists."""


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class BaseJobCollector(ABC):
    source_type = "base"

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None):
        self.config = config
        self.closed_source_job_ids: set[str] = set()
        self._owns_client = client is None
        headers = self._safe_headers(config.get("headers") or {})
        headers.setdefault("User-Agent", "JobCompass/0.4 (+local-public-job-monitor)")
        self.client = client or httpx.Client(
            timeout=float(config.get("request_timeout_seconds", 15)),
            headers=headers,
            follow_redirects=True,
        )

    @staticmethod
    def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
        forbidden = {"cookie", "authorization", "proxy-authorization"}
        return {key: value for key, value in headers.items() if key.casefold() not in forbidden}

    @staticmethod
    def validate_public_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CollectorError(f"仅支持公开 HTTP/HTTPS 地址：{url}")

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.validate_public_url(url)
        retries = int(self.config.get("retries", 2))
        interval = float(self.config.get("request_interval_seconds", 1.0))
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if interval and attempt:
                    time.sleep(interval)
                response = self.client.request(method, url, **kwargs)
                if response.status_code == 404:
                    raise PublicJobNotFound(f"公开职位已不存在：{url}")
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
        raise CollectorError(f"请求失败：{url}；{last_error}") from last_error

    def get_json(self, url: str, **kwargs: Any) -> Any:
        try:
            return self.request("GET", url, **kwargs).json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise CollectorError(f"公开接口返回的不是有效 JSON：{url}") from exc

    def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        try:
            return self.request("POST", url, json=payload).json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise CollectorError(f"公开接口返回的不是有效 JSON：{url}") from exc

    def get_text(self, url: str) -> str:
        return self.request("GET", url).text

    @abstractmethod
    def collect(self) -> list[RawCollectedJob]:
        raise NotImplementedError

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
