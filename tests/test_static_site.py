from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def load_snapshot() -> dict:
    return json.loads((SITE / "data" / "demo_jobs.json").read_text(encoding="utf-8"))


def test_static_entrypoint_and_assets_are_self_contained() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert (SITE / "assets" / "app.js").is_file()
    assert (SITE / "assets" / "legacy-design.css").is_file()
    assert (SITE / "assets" / "static-site.css").is_file()
    assert (SITE / "assets" / "favicon.svg").is_file()
    assert "./data/demo_jobs.json" in (SITE / "assets" / "app.js").read_text(encoding="utf-8")
    assert "http://" not in html
    assert "https://" not in html
    assert "/static/" not in html
    assert "url_for(" not in html


def test_snapshot_preserves_the_existing_demo_jobs() -> None:
    jobs = load_snapshot()["jobs"]
    assert [job["id"] for job in jobs] == list(range(1, 9))
    assert [job["company_name"] for job in jobs] == [
        "星图科技（示例）",
        "远帆智能（示例）",
        "云阶软件（示例）",
        "澄芯电子（示例）",
        "青屿品牌（示例）",
        "北辰数据（示例）",
        "澜桥咨询（示例）",
        "跃迁机器人（示例）",
    ]
    assert all(job["assessment"]["recommendation"] for job in jobs)
    assert all(job["assessment"]["fit_score"] is not None for job in jobs)


def test_dashboard_counts_are_derived_from_snapshot() -> None:
    jobs = load_snapshot()["jobs"]
    counts = {name: sum(job["effective_strategy"] == name for job in jobs) for name in ["priority_apply", "targeted_apply", "low_cost_try", "hold", "skip"]}
    assert sum(counts.values()) == len(jobs)
    assert counts == {"priority_apply": 2, "targeted_apply": 1, "low_cost_try": 1, "hold": 2, "skip": 2}
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for stat_id in ["stat-jobs", "stat-priority", "stat-targeted", "stat-hold", "stat-skip"]:
        assert re.search(rf'id="{stat_id}">—<', html)


def test_snapshot_excludes_sensitive_and_runtime_only_fields() -> None:
    snapshot_text = (SITE / "data" / "demo_jobs.json").read_text(encoding="utf-8")
    forbidden = [
        r"api[_-]?key",
        r"password",
        r"authorization",
        r"bearer\s",
        r"cookie",
        r"source_url",
        r"manual_comment",
        r"user_notes",
        r"raw_payload",
        r"database_url",
        r"C:\\Users\\",
        r"OneDrive",
        r"@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, snapshot_text, flags=re.IGNORECASE), pattern


def test_static_runtime_has_no_backend_or_external_api_requests() -> None:
    javascript = (SITE / "assets" / "app.js").read_text(encoding="utf-8")
    fetch_targets = re.findall(r"fetch\(\s*[\"']([^\"']+)", javascript)
    assert fetch_targets == ["./data/demo_jobs.json"]
    assert "WebSocket" not in javascript
    assert "EventSource" not in javascript
    assert "XMLHttpRequest" not in javascript
    assert "?job=" in javascript

