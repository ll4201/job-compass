import re
from dataclasses import asdict, dataclass
from typing import Any

from app.application_strategy import (
    CareerValueResult,
    EmployerAcceptanceResult,
    ShadowApplicationDecision,
)
from app.career_path_match import load_candidate_profile
from app.config import contains_any
from app.qualification import detect_seniority, has_early_career_title


@dataclass(frozen=True)
class PersonalPreferenceResult:
    personal_preference_score: float
    personal_preference_level: str
    personal_preference_reason: str

    def model_dump(self) -> dict[str, str | float]:
        return asdict(self)


@dataclass(frozen=True)
class FinalShadowDecision:
    final_shadow_strategy: str
    reason: str

    def model_dump(self) -> dict[str, str]:
        return asdict(self)


def _text(job: dict[str, Any]) -> str:
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


def evaluate_personal_preference(
    job: dict[str, Any], profile: dict[str, Any] | None = None
) -> PersonalPreferenceResult:
    profile = profile or load_candidate_profile()
    if "personal_preferences" not in profile:
        raise ValueError("candidate_profile.yaml 缺少 personal_preferences")
    title = str(job.get("job_title") or "")
    text = _text(job)
    reasons: list[str] = []
    if bool(job.get("location_conflict")) or str(job.get("workplace_status")) in {
        "non_shenzhen",
        "multiple_locations",
        "needs_confirmation",
    }:
        return PersonalPreferenceResult(0.0, "conflict", "地点不符合深圳优先策略或存在冲突")

    qualification = detect_seniority(
        title,
        text,
        job_type=str(job.get("job_type") or "full_time"),
        role_direction=job.get("role_direction"),
        experience_min=job.get("experience_min"),
    )
    if qualification.seniority_level in {"senior_manager", "director", "head", "executive"}:
        return PersonalPreferenceResult(5.0, "conflict", "职位资历或经验要求超出当前职业阶段")
    if qualification.experience_years is not None and qualification.experience_years >= 5:
        if not has_early_career_title(title):
            return PersonalPreferenceResult(5.0, "conflict", "5年以上经验要求超出当前职业阶段")
        reasons.append("职位名称存在早期职业入口，但5年以上经验要求使其仅适合拉伸申请")

    if re.search(
        r"telephone sales|insurance sales|real estate sales|电话销售|保险销售|房产销售|"
        r"高度重复|纯数据录入|repetitive data entry",
        text,
        flags=re.IGNORECASE,
    ):
        return PersonalPreferenceResult(10.0, "conflict", "岗位属于明确不愿投入申请成本的方向")

    score = 45.0
    high = bool(
        re.search(
            r"techn(?:ical|ology) solutions assistant|technical support|solution engineer|"
            r"solution specialist|assistant product manager|product assistant|product coordinator|"
            r"product intern|product operations|"
            r"project assistant|project coordinator|overseas project|"
            r"技术支持|解决方案|产品助理|产品专员|产品实习|产品运营|"
            r"项目助理|项目协调|海外项目",
            title,
            flags=re.IGNORECASE,
        )
    )
    acceptable = bool(
        re.search(
            r"influencer|e-?commerce|growth marketing|customer success|overseas business|"
            r"international business|marketing assistant|graduate program|management trainee|"
            r"电商|营销|市场|客户成功|海外业务|海外运营|管培",
            title,
            flags=re.IGNORECASE,
        )
    )
    cautious = bool(
        re.search(
            r"data analyst|business analyst|operations|software engineer|data engineer|"
            r"cybersecurity|security specialist|machine learning|数据分析|商业分析|运营",
            title,
            flags=re.IGNORECASE,
        )
    )
    low = bool(
        re.search(
            r"accounting|accountant|finance|treasury|administrative|admin clerk|hr admin|"
            r"会计|财务|出纳|行政|人事行政",
            title,
            flags=re.IGNORECASE,
        )
    )
    if high:
        score += 38
        reasons.append("岗位可直接使用技术背景并积累产品、项目或解决方案能力")
    elif acceptable:
        score += 23
        reasons.append("虽非核心技术岗，但海外、英语和跨团队能力可以形成合理叙事")
    elif cautious:
        score += 7
        reasons.append("属于可探索方向，是否值得申请取决于具体职责和成长空间")

    narrative = [
        word
        for word in ("global", "international", "海外", "english", "英语", "跨部门", "客户", "项目")
        if contains_any(text, [word])
    ]
    score += min(12, len(narrative) * 2)
    if narrative:
        reasons.append(f"个人背景可解释：{', '.join(narrative[:5])}")

    if qualification.seniority_level in {"senior", "lead", "manager"}:
        score = min(score - 20, 35)
        reasons.append("岗位级别偏高，个人投入意愿较低")
    elif qualification.experience_years is not None and qualification.experience_years > 2:
        score = min(score - 12, 49)
        reasons.append("经验差距较大，只适合条件性评估")
    if low:
        score = min(score - 18, 34)
        reasons.append("财务、会计或行政路径与个人长期策略不一致")

    score = round(max(0, min(100, score)), 1)
    level = (
        "high_alignment"
        if score >= 80
        else "acceptable"
        if score >= 65
        else "conditional"
        if score >= 45
        else "low_alignment"
        if score >= 25
        else "conflict"
    )
    return PersonalPreferenceResult(
        personal_preference_score=score,
        personal_preference_level=level,
        personal_preference_reason="；".join(reasons) or "个人偏好证据有限，建议结合JD复核",
    )


def decide_final_shadow_strategy(
    job: dict[str, Any],
    v3_assessment: dict[str, Any],
    previous: ShadowApplicationDecision,
    career_value: CareerValueResult,
    employer_acceptance: EmployerAcceptanceResult,
    preference: PersonalPreferenceResult,
) -> FinalShadowDecision:
    if previous.shadow_application_strategy == "hold":
        return FinalShadowDecision("hold", "沿用地点、信息或资格待确认结论")
    if previous.shadow_application_strategy == "skip" and (
        str(v3_assessment.get("application_recommendation")) == "do_not_apply"
        or str(v3_assessment.get("hard_filter_status")) == "excluded"
    ):
        return FinalShadowDecision("skip", "V3硬限制或明确不建议投递不能被个人偏好推翻")
    if previous.shadow_application_strategy == "stretch_apply":
        return FinalShadowDecision("stretch_apply", "方向和职业价值较高，但经验门槛限制为拉伸申请")
    if preference.personal_preference_level == "conflict":
        return FinalShadowDecision("skip", "个人偏好与职业阶段存在明确冲突")
    if career_value.career_value_level == "low":
        return FinalShadowDecision("skip", "职业价值低，不值得投入申请成本")
    if employer_acceptance.employer_acceptance_level == "low":
        return FinalShadowDecision("skip", "招聘方初筛接受度低")
    if preference.personal_preference_level == "low_alignment":
        return FinalShadowDecision("skip", "个人长期投入意愿低")
    if (
        career_value.career_value_level == "high"
        and employer_acceptance.employer_acceptance_level in {"high", "medium_high"}
        and preference.personal_preference_level in {"high_alignment", "acceptable"}
    ):
        return FinalShadowDecision("priority_apply", "高职业价值、较高初筛概率且符合个人偏好")
    if (
        career_value.career_value_level in {"high", "medium"}
        and employer_acceptance.employer_acceptance_level in {"high", "medium_high", "medium"}
        and preference.personal_preference_level in {"high_alignment", "acceptable"}
    ):
        return FinalShadowDecision("targeted_apply", "跨方向但叙事合理，值得定制简历投递")
    if career_value.career_value_level != "low" and (
        employer_acceptance.employer_acceptance_level == "uncertain"
        or preference.personal_preference_level == "conditional"
    ):
        return FinalShadowDecision("low_cost_try", "存在一定价值，但适合低成本验证或进一步核实")
    return FinalShadowDecision(previous.shadow_application_strategy, "个人偏好层不改变上一版策略")
