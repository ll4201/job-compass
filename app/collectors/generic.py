import re
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.collectors.base import BaseJobCollector, CollectorError, parse_datetime
from app.schemas import RawCollectedJob


def _json_path(value: Any, path: str | None) -> Any:
    if not path:
        return None
    current = value
    for part in (path or "").strip("$.").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


class _ListingParser(HTMLParser):
    def __init__(self, selector: str):
        super().__init__()
        self.selector = selector
        self.depth = 0
        self.active_depth: int | None = None
        self.current: dict[str, str] | None = None
        self.items: list[dict[str, str]] = []

    def _matches(self, tag: str, attrs: dict[str, str]) -> bool:
        selector = self.selector
        if selector.startswith("#"):
            return attrs.get("id") == selector[1:]
        if selector.startswith("."):
            return selector[1:] in attrs.get("class", "").split()
        if "." in selector:
            wanted_tag, wanted_class = selector.split(".", 1)
            return tag == wanted_tag and wanted_class in attrs.get("class", "").split()
        return tag == selector

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attrs = {key: value or "" for key, value in attrs_list}
        if self.active_depth is None and self._matches(tag, attrs):
            self.active_depth = self.depth
            self.current = {"text": "", "url": attrs.get("href", "")}
        elif self.current is not None and tag == "a" and attrs.get("href"):
            self.current["url"] = attrs["href"]

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current["text"] += f" {data}"

    def handle_endtag(self, _: str) -> None:
        if self.active_depth == self.depth and self.current is not None:
            self.current["text"] = re.sub(r"\s+", " ", unescape(self.current["text"])).strip()
            self.items.append(self.current)
            self.current = None
            self.active_depth = None
        self.depth -= 1


class GenericCareerPageCollector(BaseJobCollector):
    source_type = "generic"

    def collect(self) -> list[RawCollectedJob]:
        url = self.config.get("listing_url") or self.config.get("base_url")
        if not url:
            raise CollectorError("通用招聘页数据源缺少 listing_url")
        pagination = self.config.get("pagination") or {}
        page_param = pagination.get("page_param")
        start = int(pagination.get("start", 1))
        max_pages = int(self.config.get("max_pages", 1)) if page_param else 1
        results: list[RawCollectedJob] = []
        for offset in range(max_pages):
            page_url = self._page_url(url, page_param, start + offset)
            response = self.request(self.config.get("request_method", "GET"), page_url)
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                page_jobs = self._from_json(response.json())
            elif (
                "xml" in content_type
                or "rss" in content_type
                or response.text.lstrip().startswith("<?xml")
            ):
                page_jobs = self._from_rss(response.text)
            else:
                page_jobs = self._from_html(response.text, page=start + offset)
            results.extend(page_jobs)
            if not page_jobs:
                break
        return results

    @staticmethod
    def _page_url(url: str, page_param: str | None, page: int) -> str:
        if not page_param:
            return url
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query[page_param] = str(page)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    def _from_json(self, payload: Any) -> list[RawCollectedJob]:
        selectors = self.config.get("selectors") or {}
        items = _json_path(payload, selectors.get("items_path"))
        if not isinstance(items, list):
            raise CollectorError("通用 JSON 数据源的 items_path 未返回列表")
        return [self._raw_from_mapping(item, selectors) for item in items]

    def _raw_from_mapping(self, item: dict[str, Any], selectors: dict[str, str]) -> RawCollectedJob:
        def field(name: str, default: Any = None) -> Any:
            return _json_path(item, selectors.get(name)) or default

        return RawCollectedJob(
            source_name=self.config["source_name"],
            source_type="generic",
            source_job_id=str(field("id", "")) or None,
            source_url=field("url"),
            company_name=self.config["company_name"],
            job_title=field("title", "未命名职位"),
            location_raw=field("location", ""),
            job_type=field("job_type", "full_time"),
            description_raw=field("description", ""),
            published_at=parse_datetime(field("published_at")),
            raw_payload=item,
            source_confidence="medium_high",
        )

    def _from_html(self, html: str, page: int = 1) -> list[RawCollectedJob]:
        selectors = self.config.get("selectors") or {}
        item_selector = selectors.get("item_selector")
        if not item_selector:
            raise CollectorError("通用 HTML 数据源缺少 item_selector")
        parser = _ListingParser(item_selector)
        parser.feed(html)
        title_pattern = selectors.get("title_pattern")
        location_pattern = selectors.get("location_pattern")
        results = []
        for index, item in enumerate(parser.items):
            title_match = re.search(title_pattern, item["text"]) if title_pattern else None
            location_match = re.search(location_pattern, item["text"]) if location_pattern else None
            url = item["url"]
            pattern = self.config.get("detail_url_pattern")
            if pattern and url:
                url = pattern.format(path=url, id=index)
            results.append(
                RawCollectedJob(
                    source_name=self.config["source_name"],
                    source_type="generic",
                    source_job_id=f"{page}-{index}",
                    source_url=url or self.config.get("listing_url"),
                    company_name=self.config["company_name"],
                    job_title=title_match.group(1) if title_match else item["text"],
                    location_raw=location_match.group(1) if location_match else "",
                    description_raw=item["text"],
                    raw_payload={"html_item": item},
                    source_confidence="medium",
                )
            )
        return results

    def _from_rss(self, xml: str) -> list[RawCollectedJob]:
        selectors = self.config.get("selectors") or {}
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise CollectorError("通用 RSS 数据源返回的 XML 无法解析") from exc
        results = []
        for index, item in enumerate(root.findall(selectors.get("item_path", ".//item"))):

            def value(path: str) -> str:
                return item.findtext(selectors.get(path, path)) or ""

            results.append(
                RawCollectedJob(
                    source_name=self.config["source_name"],
                    source_type="generic",
                    source_job_id=value("id") or value("guid") or str(index),
                    source_url=value("url") or value("link") or None,
                    company_name=self.config["company_name"],
                    job_title=value("title") or "未命名职位",
                    location_raw=value("location"),
                    job_type=value("job_type") or "full_time",
                    description_raw=value("description"),
                    published_at=parse_datetime(value("published_at") or value("pubDate")),
                    raw_payload={child.tag: child.text for child in item},
                    source_confidence="medium",
                )
            )
        return results
