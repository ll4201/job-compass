import re
from dataclasses import asdict, dataclass
from typing import Any

from app.career_path_match import CareerMatchResult
from app.config import contains_any
from app.qualification import (
    QualificationAssessment,
    detect_seniority,
    has_early_career_title,
)


@dataclass(frozen=True)
class CareerValueResult:
    career_value_level: str
    career_value_score: float
    career_value_reason: str

    def model_dump(self) -> dict[str, str | float]:
        return asdict(self)


@dataclass(frozen=True)
class EmployerAcceptanceResult:
    employer_acceptance_level: str
    employer_acceptance_score: float
    employer_acceptance_reason: str

    def model_dump(self) -> dict[str, str | float]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowApplicationDecision:
    shadow_application_strategy: str
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


def evaluate_career_value(
    job: dict[str, Any], career_match: CareerMatchResult
) -> CareerValueResult:
    title = str(job.get("job_title") or "")
    text = _text(job)
    reasons: list[str] = []
    score = 35.0
    high_title = bool(
        re.search(
            r"assistant product manager|product assistant|product coordinator|"
            r"techn(?:ical|ology) solutions assistant|technical support|application support|"
            r"project assistant|project coordinator|customer success|product intern|"
            r"产品助理|产品专员|产品实习|项目助理|技术支持|解决方案",
            title,
            flags=re.IGNORECASE,
        )
    )
    medium_title = bool(
        re.search(
            r"e-?commerce|influencer|growth marketing|product marketing|"
            r"marketing assistant|海外运营|电商|营销|市场",
            title,
            flags=re.IGNORECASE,
        )
    )
    low_title = bool(
        re.search(
            r"accounting|accountant|finance|treasury|administrative|admin clerk|"
            r"会计|财务|出纳|行政|文员",
            title,
            flags=re.IGNORECASE,
        )
    )
    if high_title:
        score += 38
        reasons.append("岗位直接连接产品、项目、技术支持或客户解决方案路径")
    elif medium_title:
        score += 20
        reasons.append("岗位可积累商业、消费品牌或海外市场经验")
    if career_match.career_match_level == "highly_aligned":
        score += 18
    elif career_match.career_match_level == "aligned":
        score += 14
    elif career_match.career_match_level == "adjacent":
        score += 8

    positive = [
        word
        for word in (
            "产品规划",
            "项目交付",
            "技术支持",
            "客户",
            "跨部门",
            "海外",
            "global",
            "数据分析",
            "成果产出",
        )
        if contains_any(text, [word])
    ]
    score += min(15, len(positive) * 3)
    if positive:
        reasons.append(f"可积累：{', '.join(positive[:5])}")
    weak = [
        word
        for word in ("纯辅助", "重复录入", "仅整理资料", "机械执行", "纯行政", "纯财务")
        if contains_any(text, [word])
    ]
    if weak:
        score -= min(25, len(weak) * 10)
        reasons.append(f"职业积累偏弱：{', '.join(weak)}")
    if low_title:
        score = min(score - 20, 30)
        reasons.append("岗位属于财务、会计或行政路径，与目标职业路径距离较远")
    score = round(max(0, min(100, score)), 1)
    level = "high" if score >= 70 else "medium" if score >= 45 else "low"
    return CareerValueResult(level, score, "；".join(reasons) or "职业积累证据有限")


def _qualification(job: dict[str, Any]) -> QualificationAssessment:
    return detect_seniority(
        str(job.get("job_title") or ""),
        _text(job),
        job_type=str(job.get("job_type") or "full_time"),
        role_direction=job.get("role_direction"),
        experience_min=job.get("experience_min"),
    )


def evaluate_employer_acceptance(job: dict[str, Any]) -> EmployerAcceptanceResult:
    title = str(job.get("job_title") or "")
    text = _text(job)
    score = 35.0
    reasons: list[str] = []
    if contains_any(text, ["bachelor", "master", "本科", "硕士", "degree"]):
        score += 12
        reasons.append("KCL海外硕士和工程管理教育背景可满足学历初筛")
    if contains_any(text, ["english", "英语", "global", "international", "overseas", "海外"]):
        score += 10
        reasons.append("英语环境学习和跨文化沟通经历具有直接可迁移性")
    if contains_any(
        text,
        ["engineering", "technical", "electronics", "hardware", "data", "分析", "技术", "工程"],
    ):
        score += 12
        reasons.append("电子工程、技术理解和数据分析背景与JD存在交集")
    if contains_any(text, ["consumer electronics", "tech accessories", "智能硬件", "消费电子"]):
        score += 8
        reasons.append("消费电子和智能硬件兴趣提高行业叙事可信度")
    if contains_any(text, ["project", "项目", "cross-functional", "跨部门", "stakeholder"]):
        score += 8
        reasons.append("项目管理和跨团队沟通能力可用于简历初筛")
    if re.search(r"\b(assistant|coordinator|associate|graduate|junior)\b|助理|专员|管培", title, re.I):
        score += 8
        reasons.append("职位名称对早期职业候选人相对友好")

    if re.search(r"accounting|accountant|finance|treasury|会计|财务|出纳", title, re.I):
        score -= 30
        score = min(score, 32)
        reasons.append("缺少财务会计专业和实务经历，HR初筛存在明显专业跨度")
    elif re.search(r"influencer|marketing|e-?commerce|营销|市场|电商", title, re.I):
        score -= 8
        score = min(score, 59)
        reasons.append("缺少正式营销履历，需要用海外、数据和消费电子经历补足")
    elif re.search(r"product", title, re.I):
        score -= 8
        score = min(score, 59)
        reasons.append("缺少正式产品岗位经历，需要突出工程管理和项目成果")
    if re.search(r"software engineer|data engineer|security specialist|算法|软件开发", title, re.I):
        score -= 15
        reasons.append("岗位可能要求更直接的软件、数据工程或安全技术栈")

    qualification = _qualification(job)
    years = qualification.experience_years
    if years is not None and years >= 5:
        score -= 45
        score = min(score, 25)
        reasons.append(f"JD明确要求 {years:g}+ 年经验，明显超出当前履历")
    elif years is not None and years >= 3:
        score -= 25
        score = min(score, 44)
        reasons.append(f"JD明确要求 {years:g}+ 年经验，HR通过概率较低")
    elif years is not None and years > 0:
        score -= 8
        score = min(score, 69)
        reasons.append(f"JD要求 {years:g} 年左右经验，属于拉伸申请")
    if qualification.seniority_level in {"senior_manager", "director", "head", "executive"}:
        score = min(score - 35, 15)
        reasons.append(f"职位级别为 {qualification.seniority_level}，与应届履历明显不符")
    score = round(max(0, min(100, score)), 1)
    level = (
        "high"
        if score >= 70
        else "medium_high"
        if score >= 60
        else "medium"
        if score >= 45
        else "uncertain"
        if score >= 30
        else "low"
    )
    return EmployerAcceptanceResult(level, score, "；".join(reasons) or "缺少HR初筛证据")


def decide_shadow_application_strategy(
    job: dict[str, Any],
    v3_assessment: dict[str, Any],
    career_value: CareerValueResult,
    employer_acceptance: EmployerAcceptanceResult,
) -> ShadowApplicationDecision:
    qualification = _qualification(job)
    years = qualification.experience_years
    if bool(job.get("location_conflict")) or str(job.get("workplace_status")) in {
        "needs_confirmation",
        "multiple_locations",
    }:
        return ShadowApplicationDecision("hold", "地点存在冲突或仍需确认，shadow维度不得绕过")
    if str(v3_assessment.get("hard_filter_status")) == "excluded" or str(
        v3_assessment.get("risk_level")
    ) == "critical":
        return ShadowApplicationDecision("skip", "命中V3硬限制或重大风险")
    blocked_level = qualification.seniority_level in {
        "senior_manager",
        "director",
        "head",
        "executive",
    }
    if blocked_level:
        return ShadowApplicationDecision("skip", "职位级别明显超出当前职业阶段")
    early_title = has_early_career_title(str(job.get("job_title") or ""))
    high_value_stretch = career_value.career_value_level == "high"
    if years is not None and years >= 5:
        if early_title and high_value_stretch:
            return ShadowApplicationDecision(
                "stretch_apply", "岗位方向和职业价值高，但5年以上经验要求只适合拉伸申请"
            )
        return ShadowApplicationDecision("skip", "5年以上经验要求且职位名称无早期职业入口")
    if years is not None and years > 2 and high_value_stretch:
        return ShadowApplicationDecision(
            "stretch_apply", "岗位方向和职业价值高，但3至5年经验门槛限制申请优先级"
        )
    if str(v3_assessment.get("application_recommendation")) == "do_not_apply":
        return ShadowApplicationDecision("skip", "V3明确不建议投递")
    if str(v3_assessment.get("hard_filter_status")) == "pending_confirmation" or str(
        v3_assessment.get("application_recommendation")
    ) == "hold_for_info":
        return ShadowApplicationDecision("hold", "V3基础资格或信息仍待确认")
    if career_value.career_value_level == "low":
        return ShadowApplicationDecision("skip", "职业积累价值低，不值得占用定制投递成本")
    if career_value.career_value_level == "high":
        if employer_acceptance.employer_acceptance_level in {"high", "medium_high"}:
            return ShadowApplicationDecision("priority_apply", "职业价值高且HR初筛接受度较高")
        return ShadowApplicationDecision("targeted_apply", "职业价值高，但需针对经验差距定制简历")
    if employer_acceptance.employer_acceptance_level in {"high", "medium_high", "medium"}:
        return ShadowApplicationDecision("targeted_apply", "职业价值中等且存在可解释的简历切入点")
    if employer_acceptance.employer_acceptance_level == "uncertain":
        return ShadowApplicationDecision("low_cost_try", "方向并非核心，但可用低成本投递验证市场反馈")
    return ShadowApplicationDecision("skip", "职业价值和招聘方接受度均不足")
