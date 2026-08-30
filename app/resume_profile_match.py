from dataclasses import asdict, dataclass
from typing import Any

from app.config import contains_any, load_config


@dataclass(frozen=True)
class ResumeProfileMatch:
    recommended_resume_profile: str
    profile_match_score: float
    profile_match_reason: str
    resume_focus: str
    modification_points: tuple[str, ...]

    def model_dump(self) -> dict[str, str | float | tuple[str, ...]]:
        return asdict(self)


def load_resume_profiles() -> dict[str, Any]:
    config = load_config("resume_profiles.yaml")
    if not config.get("config_version") or not config.get("profiles"):
        raise ValueError("resume_profiles.yaml 缺少配置版本或 profiles")
    required = {"technical_product", "overseas_business", "general_entry"}
    missing = sorted(required - set(config["profiles"]))
    if missing:
        raise ValueError(f"resume_profiles.yaml 缺少版本：{', '.join(missing)}")
    return config


def _text(job_data: dict[str, Any]) -> tuple[str, str]:
    title = str(job_data.get("job_title") or "")
    combined = " ".join(
        str(job_data.get(key) or "")
        for key in ("job_title", "role_direction", "description", "responsibilities", "requirements")
    )
    return title, combined


def _matches(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if contains_any(text, [keyword])]


def resume_profile_match(
    job_data: dict[str, Any],
    final_strategy: str,
    action_type: str,
    config: dict[str, Any] | None = None,
) -> ResumeProfileMatch:
    config = config or load_resume_profiles()
    if action_type == "archive_no_action" or final_strategy == "skip":
        return ResumeProfileMatch(
            "not_applicable",
            0.0,
            "最终策略为跳过，不应为该岗位投入简历修改成本",
            "无需准备简历",
            ("保留岗位与跳过原因，仅在条件实质变化后重新评估",),
        )

    title, combined = _text(job_data)
    candidates: list[tuple[float, int, str, list[str], list[str]]] = []
    for order, (name, values) in enumerate(config["profiles"].items()):
        title_hits = _matches(title, list(values.get("title_keywords") or []))
        evidence_hits = _matches(combined, list(values.get("evidence_keywords") or []))
        score = 20 + min(50, len(title_hits) * 30) + min(25, len(evidence_hits) * 5)
        if final_strategy == "hold":
            score -= 5
        candidates.append((float(score), -order, name, title_hits, evidence_hits))

    best_score, _order, profile_name, title_hits, evidence_hits = max(candidates)
    if not title_hits and best_score <= 35:
        profile_name = str(config.get("fallback_profile") or "general_entry")
        values = config["profiles"][profile_name]
        evidence_hits = _matches(combined, list(values.get("evidence_keywords") or []))
        best_score = 40 + min(20, len(evidence_hits) * 5)
    else:
        values = config["profiles"][profile_name]

    emphasis = tuple(str(item) for item in values.get("emphasis") or [])
    templates = tuple(str(item) for item in values.get("modification_templates") or [])
    if action_type == "low_cost_apply":
        modifications = tuple(f"轻量调整：{item}" for item in templates[:2])
    elif action_type == "clarify_then_decide":
        modifications = (
            "先确认岗位关键信息；确认值得投递后再执行以下修改",
            *templates,
        )
    else:
        modifications = templates
    signals = [*title_hits[:3], *evidence_hits[:4]]
    reason = (
        f"命中岗位与职责信号：{', '.join(dict.fromkeys(signals))}"
        if signals
        else "岗位方向较泛，使用通用应届版本作为低风险起点"
    )
    return ResumeProfileMatch(
        recommended_resume_profile=profile_name,
        profile_match_score=round(max(0, min(100, best_score)), 1),
        profile_match_reason=reason,
        resume_focus="；".join(emphasis),
        modification_points=modifications,
    )
