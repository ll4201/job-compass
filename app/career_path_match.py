from dataclasses import asdict, dataclass
from typing import Any

from app.config import contains_any, load_config
from app.qualification import detect_seniority


@dataclass(frozen=True)
class CareerMatchResult:
    career_match_level: str
    career_match_score: float
    career_match_reason: str

    def model_dump(self) -> dict[str, str | float]:
        return asdict(self)


@dataclass(frozen=True)
class PersonalDecision:
    v3_recommendation: str
    career_match_level: str
    career_match_score: float
    career_match_reason: str
    final_recommendation: str
    decision_reason: str

    def model_dump(self) -> dict[str, str | float]:
        return asdict(self)


def load_candidate_profile() -> dict[str, Any]:
    profile = load_config("candidate_profile.yaml")
    required = {
        "profile_version",
        "candidate_stage",
        "target_roles",
        "career_paths",
        "constraints",
        "decision_thresholds",
    }
    missing = sorted(required - set(profile))
    if missing:
        raise ValueError(f"candidate_profile.yaml 缺少字段：{', '.join(missing)}")
    return profile


def _combined_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(key) or "")
        for key in (
            "job_title",
            "role_direction",
            "description",
            "responsibilities",
            "requirements",
        )
    )


def _matching_keywords(text: str, words: list[str]) -> list[str]:
    return [word for word in words if contains_any(text, [word])]


def career_path_match(
    job: dict[str, Any], profile: dict[str, Any] | None = None
) -> CareerMatchResult:
    profile = profile or load_candidate_profile()
    text = _combined_text(job)
    title = str(job.get("job_title") or "")
    role_text = f"{title} {job.get('role_direction') or ''}"
    constraints = profile["constraints"]
    reasons: list[str] = []

    workplace = str(job.get("workplace_status") or "")
    location_conflict = bool(job.get("location_conflict"))
    if location_conflict or workplace in {"non_shenzhen", "multiple_locations"}:
        reason = "地点冲突或明确非深圳，不符合个人地点限制"
        return CareerMatchResult("conflicting", 0.0, reason)
    if workplace and workplace not in constraints["required_location_statuses"]:
        reasons.append("深圳办公地点尚未明确，职业匹配仅作预评估")

    if contains_any(text, constraints["hard_exclusion_keywords"]):
        return CareerMatchResult("conflicting", 10.0, "命中个人明确排除的工作方式或岗位类型")

    score = 20.0
    role_hits: list[str] = []
    role_tier = "none"
    for direction, keywords in profile["target_roles"]["priority_1"].items():
        matched = _matching_keywords(role_text, [direction, *keywords])
        if matched:
            role_hits.extend(matched)
            role_tier = "priority_1"
    if role_tier == "none":
        for direction, keywords in profile["target_roles"]["priority_2"].items():
            matched = _matching_keywords(role_text, [direction, *keywords])
            if matched:
                role_hits.extend(matched)
                role_tier = "priority_2"
    if role_tier == "priority_1":
        score += 30
        reasons.append(f"命中第一优先目标方向：{', '.join(dict.fromkeys(role_hits[:4]))}")
    elif role_tier == "priority_2":
        score += 20
        reasons.append(f"命中第二优先目标方向：{', '.join(dict.fromkeys(role_hits[:4]))}")
    else:
        reasons.append("未直接命中目标岗位方向")

    capability_hits = _matching_keywords(text, profile["transferable_capabilities"])
    capability_points = min(18, len(set(capability_hits)) * 3)
    score += capability_points
    if capability_hits:
        reasons.append(f"可迁移能力：{', '.join(dict.fromkeys(capability_hits[:5]))}")

    path_hits: list[str] = []
    for path in profile["career_paths"].values():
        matched = _matching_keywords(text, path["evidence_keywords"])
        if matched:
            path_hits.append(path["label"])
    path_points = min(18, len(set(path_hits)) * 7)
    score += path_points
    if path_hits:
        reasons.append(f"可连接长期路径：{', '.join(dict.fromkeys(path_hits))}")

    positive_hits = _matching_keywords(
        text, profile["career_value"]["positive_responsibilities"]
    )
    score += min(14, len(set(positive_hits)) * 3)
    if positive_hits:
        reasons.append(f"有利于积累成果：{', '.join(dict.fromkeys(positive_hits[:4]))}")

    optionality_hits = _matching_keywords(text, profile["career_value"]["optionality_keywords"])
    score += min(10, len(set(optionality_hits)) * 2)

    weak_hits = _matching_keywords(text, profile["career_value"]["weak_responsibilities"])
    if weak_hits:
        penalty = min(25, len(set(weak_hits)) * 8)
        score -= penalty
        reasons.append(f"职业积累偏弱：{', '.join(dict.fromkeys(weak_hits[:4]))}")

    qualification = detect_seniority(
        title,
        text,
        job_type=str(job.get("job_type") or "full_time"),
        role_direction=job.get("role_direction"),
        experience_min=job.get("experience_min"),
    )
    if qualification.seniority_level in constraints["blocked_seniority"]:
        score = min(score - 30, 30)
        reasons.append(f"职位级别 {qualification.seniority_level} 明显高于应届阶段")
    elif qualification.seniority_level in constraints["stretch_seniority"]:
        score -= 8
        reasons.append(f"职位级别 {qualification.seniority_level} 属于可尝试但有门槛")
    if qualification.experience_years is not None:
        if qualification.experience_years > profile["experience"]["maximum_reasonable_years"]:
            score -= 25
            reasons.append("经验要求超过个人当前合理申请范围")
        elif qualification.experience_years > profile["experience"]["acceptable_stretch_years"]:
            score -= 12
            reasons.append("经验要求属于明显拉伸申请")

    score = round(max(0, min(100, score)), 1)
    thresholds = profile["decision_thresholds"]
    level = (
        "highly_aligned"
        if score >= thresholds["highly_aligned"]
        else "aligned"
        if score >= thresholds["aligned"]
        else "adjacent"
        if score >= thresholds["adjacent"]
        else "weak"
        if score >= thresholds["weak"]
        else "conflicting"
    )
    return CareerMatchResult(level, score, "；".join(reasons) or "缺少可判断的职业路径信息")


def combine_with_v3(
    v3_recommendation: str,
    career_match: CareerMatchResult,
    *,
    hard_filter_status: str = "eligible",
    risk_level: str = "low",
) -> PersonalDecision:
    final = v3_recommendation
    reason = "V3建议保持不变"
    if v3_recommendation == "do_not_apply" or hard_filter_status == "excluded":
        final = "do_not_apply"
        reason = "V3硬过滤或明确重大风险优先，职业路径分不覆盖安全边界"
    elif hard_filter_status == "pending_confirmation" or risk_level == "critical":
        final = "hold_for_info"
        reason = "基础资格或风险仍待确认"
    elif career_match.career_match_level == "conflicting":
        final = "hold_for_info"
        reason = "岗位与个人职业路径或限制条件冲突"
    elif career_match.career_match_score < 50 and v3_recommendation in {
        "priority_apply",
        "apply",
    }:
        final = "try"
        reason = "岗位本身可投，但长期职业路径匹配不足，降为低成本尝试"
    elif career_match.career_match_score < 65 and v3_recommendation == "priority_apply":
        final = "apply"
        reason = "职业路径仅部分匹配，不进入最高优先级"
    elif (
        career_match.career_match_score >= 85
        and v3_recommendation == "apply"
        and risk_level == "low"
    ):
        final = "priority_apply"
        reason = "V3岗位价值良好且高度符合个人长期职业路径"
    return PersonalDecision(
        v3_recommendation=v3_recommendation,
        career_match_level=career_match.career_match_level,
        career_match_score=career_match.career_match_score,
        career_match_reason=career_match.career_match_reason,
        final_recommendation=final,
        decision_reason=reason,
    )


def personal_job_decision(
    job: dict[str, Any], v3_assessment: dict[str, Any], profile: dict[str, Any] | None = None
) -> PersonalDecision:
    match = career_path_match(job, profile)
    return combine_with_v3(
        str(v3_assessment["application_recommendation"]),
        match,
        hard_filter_status=str(v3_assessment.get("hard_filter_status") or "eligible"),
        risk_level=str(v3_assessment.get("risk_level") or "low"),
    )
