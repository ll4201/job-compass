import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class QualificationAssessment:
    seniority_level: str
    role_direction_match: str
    seniority_match: str
    experience_match: str
    experience_years: float | None
    experience_band: str
    reasons: tuple[str, ...]

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def extract_experience_years(text: str) -> float | None:
    normalized = text.casefold()
    range_patterns = (
        r"(\d+(?:\.\d+)?)\s*[-–~]\s*\d+(?:\.\d+)?\s*years?.{0,60}?experience",
        r"(\d+(?:\.\d+)?)\s*[-~至]\s*\d+(?:\.\d+)?\s*年.{0,30}?经验",
    )
    patterns = (
        r"(?:minimum(?: of)?|at least|over|more than)?\s*(\d+(?:\.\d+)?)\s*\+?\s*years?"
        r"(?:\s+of)?\s+(?:(?:relevant|related|professional|working|product|marketing|"
        r"industry|hands-on)\s+){0,3}experience",
        r"(?:至少|不少于|具有)?\s*(\d+(?:\.\d+)?)\s*年(?:以上)?(?:相关|工作|行业|岗位|管理)?经验",
        r"(?:经验|工作年限)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*年",
    )
    values = [
        float(value)
        for pattern in (*range_patterns, *patterns)
        for value in re.findall(pattern, normalized)
    ]
    return max(values) if values else None


def experience_gap_band(years: float | None) -> str:
    if years is None:
        return "unknown"
    if years <= 1:
        return "compatible"
    if years <= 2:
        return "light_gap"
    if years <= 3:
        return "significant_gap"
    if years < 5:
        return "high_risk"
    return "extreme_gap"


def has_early_career_title(title: str) -> bool:
    return bool(
        re.search(
            r"\b(assistant|associate|junior)\b|助理|初级|初阶",
            title,
            flags=re.IGNORECASE,
        )
    )


def detect_seniority(
    title: str,
    text: str = "",
    *,
    job_type: str = "full_time",
    role_direction: str | None = None,
    experience_min: float | None = None,
) -> QualificationAssessment:
    title_folded = title.casefold().strip()
    combined = f"{title} {text}"
    combined_folded = combined.casefold()
    parsed_years = extract_experience_years(combined)
    years = (
        parsed_years
        if parsed_years is not None and (experience_min is None or experience_min <= 0)
        else experience_min
    )
    reasons: list[str] = []

    if job_type == "internship" or re.search(r"\b(intern|internship)\b|实习", title_folded):
        level = "internship"
    elif re.search(r"management trainee|管培生|管理培训生", title_folded):
        level = "graduate"
    elif re.search(r"assistant\s+.+manager|助理.+经理|经理助理", title_folded):
        level = "junior"
    elif re.search(r"\b(head of|vp|vice president|chief)\b|部门负责人|事业部负责人", title_folded):
        level = "head" if "head" in title_folded or "负责人" in title else "executive"
    elif re.search(r"(?:\bsenior\b|\bsr\.?)\s+.+manager|高级经理|资深经理", title_folded):
        level = "senior_manager"
    elif re.search(r"\bdirector\b|总监", title_folded):
        level = "director"
    elif re.search(r"\blead\b|负责人", title_folded):
        level = "lead"
    elif re.search(r"\b(senior|principal|staff)\b|\bsr\.?|高级|资深", title_folded):
        level = "senior"
    elif re.search(r"\bmanager\b|经理|主管", title_folded):
        level = "manager"
    elif re.search(r"\bassociate\b", title_folded):
        level = "associate"
    elif re.search(r"\bspecialist\b|专家", title_folded):
        level = "specialist"
    elif re.search(r"\bjunior\b|初级", title_folded):
        level = "junior"
    elif re.search(r"\bgraduate\b|校招|应届", title_folded):
        level = "graduate"
    elif re.search(r"\b(entry|assistant|coordinator|clerk)\b|助理|协调员|文员", title_folded):
        level = "entry"
    elif years is not None and years >= 8:
        level = "senior"
    elif years is not None and years >= 3:
        level = "mid"
    elif years is not None and years >= 1:
        level = "junior"
    else:
        level = "unknown"

    management_evidence = re.search(
        r"manage(?:s|d|ment|ing)?\s+(?:a\s+)?team|direct reports?|people management|team of \d+|"
        r"department strategy|own(?:s|ing)?\s+(?:the\s+)?budget|budget responsibility|"
        r"管理.{0,8}团队|带领.{0,8}团队|部门战略|负责.{0,6}预算",
        combined_folded,
    )
    if management_evidence:
        reasons.append(f"JD包含人员管理、战略或预算责任：{management_evidence.group(0)}")
        if level in {"unknown", "mid", "specialist"}:
            level = "manager"

    band = experience_gap_band(years)
    if years is None:
        experience_match = "unknown"
    elif years <= 1:
        experience_match = "compatible"
    elif years <= 2:
        experience_match = "stretch"
    else:
        experience_match = "low"
        reasons.append(f"JD明确要求至少 {years:g} 年经验")

    if level in {"internship", "graduate", "entry", "junior", "associate"}:
        seniority_match = "compatible"
    elif level in {"specialist", "mid", "manager", "unknown"}:
        seniority_match = "stretch" if level != "unknown" else "unknown"
    else:
        seniority_match = "low"
        reasons.append(f"职位资历识别为 {level}")

    if role_direction in {"产品", "项目", "技术支持"}:
        role_match = "high"
    elif role_direction and role_direction != "其他":
        role_match = "medium"
    else:
        role_match = "low"
    return QualificationAssessment(
        seniority_level=level,
        role_direction_match=role_match,
        seniority_match=seniority_match,
        experience_match=experience_match,
        experience_years=years,
        experience_band=band,
        reasons=tuple(reasons),
    )
