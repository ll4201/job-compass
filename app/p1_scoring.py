from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import load_config
from app.normalizer import normalized_text
from app.qualification import detect_seniority, has_early_career_title


@dataclass(frozen=True)
class P1ShadowResult:
    eligibility_score: float
    career_value_score: float
    direction_fit_score: float
    life_quality_score: float | None
    freshness_score: float | None
    compensation_score: float | None
    overall_priority_score: float
    support_role_type: str
    needs_confirmation: bool
    resume_type: str
    job_age_days: int | None
    date_source: str
    proposed_strategy: str
    reason: str
    questions_to_confirm: tuple[str, ...]
    project_ownership_score: float | None = None
    conversion_potential_score: float | None = None

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _value(data: Any, name: str, default: Any = None) -> Any:
    if isinstance(data, dict):
        return data.get(name, default)
    return getattr(data, name, default)


def _text(job: Any) -> str:
    return normalized_text(
        " ".join(
            str(_value(job, key) or "")
            for key in (
                "job_title",
                "role_direction",
                "description",
                "responsibilities",
                "requirements",
                "experience_raw",
                "language_requirement",
                "benefits_raw",
            )
        )
    ).casefold()


def _contains(text: str, values: tuple[str, ...]) -> bool:
    return any(value.casefold() in text for value in values)


def classify_support_role(job: Any) -> str:
    text = _text(job)
    title = str(_value(job, "job_title") or "").casefold()
    if not _contains(title, ("support", "支持", "application engineer", "应用工程")):
        return "other_support"
    it_signals = (
        "sql",
        "database",
        "server",
        "linux",
        "incident",
        "sla",
        "production",
        "monitoring",
        "erp",
        "oms",
        "wms",
        "crm",
        "api debugging",
        "on-call",
        "on call",
    )
    product_signals = (
        "customer",
        "client",
        "product",
        "solution",
        "training",
        "presentation",
        "technical documentation",
        "troubleshooting",
        "overseas",
        "international",
        "product feedback",
        "customer success",
        "客户",
        "产品反馈",
        "培训",
        "解决方案",
    )
    it_count = sum(signal in text for signal in it_signals)
    product_count = sum(signal in text for signal in product_signals)
    if it_count >= 2 and it_count >= product_count:
        return "it_application_support"
    if product_count >= 2:
        return "customer_product_support"
    return "other_support"


def calculate_eligibility(job: Any) -> tuple[float, list[str], list[str]]:
    title = str(_value(job, "job_title") or "")
    text = _text(job)
    qualification = detect_seniority(
        title,
        text,
        job_type=str(_value(job, "job_type") or "full_time"),
        role_direction=_value(job, "role_direction"),
        experience_min=_value(job, "experience_min"),
    )
    score = 78.0
    reasons: list[str] = []
    questions: list[str] = []
    penalties = {
        "light_gap": 10,
        "significant_gap": 25,
        "high_risk": 40,
        "extreme_gap": 55,
    }
    score -= penalties.get(qualification.experience_band, 0)
    if qualification.experience_band == "unknown":
        questions.append("该岗位对相关工作经验年限是否有明确硬性要求？")
    elif qualification.experience_band != "compatible":
        reasons.append(f"经验门槛属于 {qualification.experience_band}")

    seniority_penalty = {
        "senior": 40,
        "lead": 45,
        "senior_manager": 60,
        "director": 70,
        "head": 75,
        "executive": 80,
    }
    if qualification.seniority_level in seniority_penalty:
        score -= seniority_penalty[qualification.seniority_level]
        reasons.append(f"职位级别为 {qualification.seniority_level}")
    if _contains(text, ("fresh graduate", "graduate program", "应届", "校招", "管培生")):
        score += 12
        reasons.append("岗位明确对应应届或毕业生入口")
    if _contains(text, ("engineering", "technical", "electronics", "英语", "english")):
        score += 5
    if _contains(text, ("phd required", "必须博士", "注册会计师", "cpa required")):
        score -= 30
        reasons.append("存在与候选人背景明显不符的硬性资格")
    if not _value(job, "education_requirement") and not _contains(
        text, ("bachelor", "master", "degree", "本科", "硕士", "学历")
    ):
        questions.append("该岗位是否接受2026届海外硕士申请？")
    return round(max(0, min(100, score)), 1), reasons, questions


def calculate_direction_fit(job: Any, support_type: str) -> tuple[float, list[str]]:
    text = _text(job)
    reasons: list[str] = []
    priority_one = (
        "product assistant",
        "junior product",
        "product specialist",
        "hardware product",
        "consumer electronics",
        "overseas product",
        "project coordinator",
        "pmo",
        "international project",
        "international business",
        "产品助理",
        "产品专员",
        "海外产品",
        "项目协调",
    )
    priority_two = (
        "ai product",
        "product operations",
        "overseas operations",
        "international marketing",
        "growth marketing",
        "business analysis",
        "market research",
        "graduate program",
        "产品运营",
        "海外运营",
        "商业分析",
        "市场研究",
        "管培",
    )
    low = (
        "pure sales",
        "key account",
        "sales manager",
        "account executive",
        "accounting",
        "human resources",
        "embedded engineer",
        "algorithm engineer",
        "machine learning engineer",
        "software engineer",
        "backend engineer",
        "optical r&d",
        "会计",
        "纯销售",
        "人力资源",
        "social media",
        "content associate",
        "content creator",
        "pure content",
        "社交媒体",
        "纯内容",
        "嵌入式",
        "算法",
        "光学研发",
    )
    if _contains(text, priority_one):
        score = 88.0
        reasons.append("命中第一优先职业方向")
    elif _contains(text, priority_two):
        score = 72.0
        reasons.append("命中第二优先职业方向")
    elif _contains(text, low):
        score = 25.0
        reasons.append("岗位主要职责属于低优先职业方向")
    else:
        score = 50.0
        reasons.append("岗位方向需要结合具体职责判断")
    if support_type == "customer_product_support":
        score = max(score, 78)
        reasons.append("属于面向客户和产品的解决方案支持")
    elif support_type == "it_application_support":
        score = min(score, 35)
        reasons.append("属于IT应用与生产系统支持，不等同于产品解决方案支持")
    return round(score, 1), reasons


def calculate_career_value(job: Any, company_quality: float | None = None) -> tuple[float, list[str]]:
    text = _text(job)
    title = str(_value(job, "job_title") or "").casefold()
    positive = (
        "core business",
        "ownership",
        "customer",
        "client",
        "market",
        "international",
        "global",
        "cross-functional",
        "project management",
        "requirement analysis",
        "user research",
        "market research",
        "product lifecycle",
        "technical documentation",
        "data analysis",
        "automation",
        "核心业务",
        "独立负责",
        "用户研究",
        "需求分析",
        "跨部门",
        "海外",
    )
    weak = ("data entry", "pure execution", "仅整理", "重复录入", "纯辅助", "机械执行")
    found = [signal for signal in positive if signal in text]
    weak_found = [signal for signal in weak if signal in text]
    score = 45 + min(40, len(found) * 5) - min(35, len(weak_found) * 12)
    if _contains(
        title,
        (
            "product assistant",
            "product specialist",
            "product coordinator",
            "project coordinator",
            "technical support",
            "product support",
            "solution support",
            "产品助理",
            "产品专员",
            "项目协调",
            "技术支持",
            "growth marketing assistant",
        ),
    ):
        score += 20 if "growth marketing" not in title else 12
        found.append("target-role ownership")
    if company_quality is not None:
        normalized_company = company_quality * 10 if company_quality <= 10 else company_quality
        score += max(0, min(8, (normalized_company - 50) * 0.16))
    reasons = ([f"职业资本证据：{', '.join(found[:6])}"] if found else []) + (
        [f"执行性风险：{', '.join(weak_found[:3])}"] if weak_found else []
    )
    return round(max(0, min(100, score)), 1), reasons


def calculate_life_quality(job: Any, support_type: str) -> tuple[float | None, list[str], list[str]]:
    text = _text(job)
    known = False
    score = 75.0
    reasons: list[str] = []
    questions: list[str] = []
    negatives = {
        "大小周": 25,
        "单休": 30,
        "996": 40,
        "长期加班": 25,
        "frequent travel": 20,
        "高频出差": 20,
        "长期驻外": 35,
        "night shift": 30,
        "夜班": 30,
        "24/7": 25,
        "on-call": 18,
        "on call": 18,
        "shift work": 20,
    }
    for signal, penalty in negatives.items():
        if signal in text:
            known = True
            score -= penalty
            reasons.append(signal)
    if _contains(text, ("双休", "five-day work week", "hybrid", "remote", "带薪年假")):
        known = True
        score += 10
        reasons.append("明确披露较友好的工作制度")
    if support_type == "it_application_support" and _contains(
        text, ("on-call", "on call", "24/7", "night shift", "shift")
    ):
        score -= 10
    if str(_value(job, "working_schedule") or "not_disclosed") in {
        "not_disclosed",
        "unclear",
    }:
        questions.extend(("该岗位是否双休？", "团队日常加班频率大约如何？"))
    if str(_value(job, "travel_requirement") or "not_disclosed") in {
        "not_disclosed",
        "unclear",
    }:
        questions.append("该岗位的出差比例以及单次持续时间大约是多少？")
    return (round(max(0, min(100, score)), 1) if known else None), reasons, questions


def calculate_compensation(job: Any) -> tuple[float | None, list[str]]:
    salary_min = _value(job, "salary_min")
    salary_max = _value(job, "salary_max")
    if salary_min is None and salary_max is None:
        return None, ["该岗位的固定薪资、奖金和发薪月数如何构成？"]
    salary = float(salary_max or salary_min or 0)
    if str(_value(job, "salary_period") or "month") == "year":
        salary /= 12
    internship = str(_value(job, "job_type") or "full_time") == "internship"
    if internship:
        score = 80 if salary >= 5000 else 65 if salary >= 3500 else 50
    else:
        score = 90 if salary >= 15000 else 78 if salary >= 11000 else 62 if salary >= 8000 else 42
    if _value(job, "five_insurances_housing_fund") == "confirmed_yes":
        score += 5
    return round(min(100, score), 1), []


def calculate_freshness(job: Any, now: datetime | None = None) -> tuple[int | None, float | None, str]:
    now = now or datetime.now(timezone.utc)
    published = _value(job, "published_at")
    first_seen = _value(job, "first_seen_at")
    date = published or first_seen
    source = "published" if published else "first_seen" if first_seen else "unknown"
    if date is None:
        return None, None, source
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    age = max(0, (now - date).days)
    rules = load_config("p1_scoring_rules.yaml")["freshness"]
    score = next(float(item["score"]) for item in rules if age <= int(item["max_days"]))
    return age, score, source


def classify_resume_type(job: Any, support_type: str) -> str:
    text = _text(job)
    title = str(_value(job, "job_title") or "").casefold()
    if support_type == "customer_product_support":
        return "SOLUTION_SUPPORT"
    if support_type == "it_application_support":
        return "PROJECT_BUSINESS"
    if _contains(
        title,
        (
            "social media",
            "content associate",
            "key account",
            "sales manager",
            "software engineer",
            "machine learning engineer",
            "社交媒体",
            "销售",
        ),
    ):
        return "PROJECT_BUSINESS"
    if _contains(
        title,
        (
            "project",
            "pmo",
            "international business",
            "overseas business",
            "operations",
            "graduate program",
            "management trainee",
            "business analysis",
            "项目",
            "海外业务",
            "运营",
            "管培",
            "商业分析",
        ),
    ):
        return "PROJECT_BUSINESS"
    if _contains(text, ("product", "产品", "ai product", "product operations")):
        return "PRODUCT"
    if _contains(text, ("technical support", "solution support", "product support", "技术支持")):
        return "SOLUTION_SUPPORT"
    return "PROJECT_BUSINESS"


def _internship_components(job: Any, company_quality: float | None) -> tuple[float, float, float]:
    text = _text(job)
    ownership = 45 + 10 * sum(
        signal in text for signal in ("ownership", "independent", "real project", "独立负责", "真实项目")
    )
    conversion = 50.0
    conversion_state = str(_value(job, "internship_conversion") or "not_disclosed")
    if conversion_state == "confirmed_yes":
        conversion = 85
    elif conversion_state == "confirmed_no":
        conversion = 25
    quality = float(company_quality or 50)
    if quality <= 10:
        quality *= 10
    return min(100, quality), min(100, ownership), conversion


def _weighted_score(values: dict[str, float | None], weights: dict[str, float]) -> float:
    available = [(values[key], weight) for key, weight in weights.items() if values.get(key) is not None]
    denominator = sum(weight for _value, weight in available)
    if not denominator:
        return 0.0
    return round(sum(float(value) * weight for value, weight in available) / denominator, 1)


def evaluate_p1_shadow(job: Any, assessment: Any, now: datetime | None = None) -> P1ShadowResult:
    config = load_config("p1_scoring_rules.yaml")
    support_type = classify_support_role(job)
    eligibility, eligibility_reasons, eligibility_questions = calculate_eligibility(job)
    direction, direction_reasons = calculate_direction_fit(job, support_type)
    current_company_quality = _value(assessment, "company_quality_score")
    career_value, career_reasons = calculate_career_value(job, current_company_quality)
    life_quality, life_reasons, life_questions = calculate_life_quality(job, support_type)
    compensation, compensation_questions = calculate_compensation(job)
    age, freshness, date_source = calculate_freshness(job, now)
    questions = list(dict.fromkeys(eligibility_questions + life_questions + compensation_questions))
    internship = str(_value(job, "job_type") or "full_time") == "internship"
    ownership = conversion = None
    values: dict[str, float | None] = {
        "eligibility_score": eligibility,
        "career_value_score": career_value,
        "direction_fit_score": direction,
        "life_quality_score": life_quality,
        "compensation_score": compensation,
        "freshness_score": freshness,
    }
    if internship:
        company_quality, ownership, conversion = _internship_components(job, current_company_quality)
        values.update(
            company_quality_score=company_quality,
            project_ownership_score=ownership,
            conversion_potential_score=conversion,
        )
        weights = config["internship_weights"]
    else:
        weights = config["full_time_weights"]
    overall = _weighted_score(values, weights)
    thresholds = config["strategy_thresholds"]
    qualification = detect_seniority(
        str(_value(job, "job_title") or ""),
        _text(job),
        job_type=str(_value(job, "job_type") or "full_time"),
        role_direction=_value(job, "role_direction"),
        experience_min=_value(job, "experience_min"),
    )
    inactive = (
        bool(_value(job, "is_sample", False))
        or not bool(_value(job, "is_active", False))
        or str(_value(job, "availability_status") or "") != "active"
    )
    location_pending = bool(_value(job, "location_conflict", False)) or str(
        _value(job, "workplace_status") or ""
    ) in {"needs_confirmation", "multiple_locations", "optional_unconfirmed"}
    if inactive or _value(assessment, "hard_filter_status") == "excluded":
        proposed = "skip"
    elif location_pending:
        proposed = "hold"
    elif qualification.seniority_level in {
        "senior",
        "lead",
        "senior_manager",
        "director",
        "head",
        "executive",
    }:
        proposed = "skip"
    elif direction <= 25:
        proposed = "skip"
    elif qualification.experience_years is not None and qualification.experience_years >= 5:
        proposed = (
            "stretch_apply"
            if has_early_career_title(str(_value(job, "job_title") or ""))
            and career_value >= 65
            and direction >= 60
            else "skip"
        )
    elif eligibility < float(thresholds["skip_eligibility"]):
        proposed = "skip"
    elif eligibility < float(thresholds["stretch_eligibility"]):
        proposed = "hold"
    elif eligibility >= float(thresholds["priority_eligibility"]) and overall >= float(
        thresholds["priority_overall"]
    ) and direction >= 65 and career_value >= 65 and not eligibility_questions:
        proposed = "priority_apply"
    elif eligibility >= float(thresholds["targeted_eligibility"]) and overall >= float(
        thresholds["targeted_overall"]
    ) and career_value >= 60 and direction >= 60:
        proposed = "targeted_apply"
    elif career_value >= 60 and direction >= 50:
        proposed = "stretch_apply"
    else:
        proposed = "hold" if eligibility >= 40 else "skip"
    reason_parts = eligibility_reasons + direction_reasons + career_reasons + life_reasons
    reason_parts.append(f"P1综合优先级 {overall:g}，Eligibility {eligibility:g}")
    return P1ShadowResult(
        eligibility_score=eligibility,
        career_value_score=career_value,
        direction_fit_score=direction,
        life_quality_score=life_quality,
        freshness_score=freshness,
        compensation_score=compensation,
        overall_priority_score=overall,
        support_role_type=support_type,
        needs_confirmation=bool(questions),
        resume_type=classify_resume_type(job, support_type),
        job_age_days=age,
        date_source=date_source,
        proposed_strategy=proposed,
        reason="；".join(reason_parts),
        questions_to_confirm=tuple(questions),
        project_ownership_score=ownership,
        conversion_potential_score=conversion,
    )
