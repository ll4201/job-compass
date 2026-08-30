import hashlib
import re
import unicodedata
from typing import Any

from app.config import contains_any, load_config

UNKNOWN = "not_disclosed"


def normalized_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def parse_salary(raw: str | None) -> tuple[float | None, float | None, str | None]:
    text = normalized_text(raw).lower().replace(",", "")
    if not text or any(x in text for x in ("面议", "保密", "未公开")):
        return None, None, None
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*([kw万千]?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*([kw万千]?)", text
    )
    if not match:
        return None, None, None
    low, high = float(match.group(1)), float(match.group(3))
    unit = match.group(4) or match.group(2)
    multiplier = 1000 if unit in {"k", "千"} else 10000 if unit in {"w", "万"} else 1
    period = (
        "day"
        if any(x in text for x in ("/天", "日薪", "每天"))
        else "year"
        if any(x in text for x in ("/年", "年薪"))
        else "month"
    )
    return low * multiplier, high * multiplier, period


def parse_experience(raw: str | None) -> tuple[float | None, float | None]:
    text = normalized_text(raw).lower()
    if not text:
        return None, None
    if contains_any(text, ["不限", "无经验", "应届", "在校生", "fresh graduate"]):
        return 0, 0
    between = re.search(r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*年", text)
    if between:
        return float(between.group(1)), float(between.group(2))
    above = re.search(r"(\d+(?:\.\d+)?)\s*年(?:以上|起)", text)
    if above:
        return float(above.group(1)), None
    one = re.search(r"(\d+(?:\.\d+)?)\s*年", text)
    return (float(one.group(1)), float(one.group(1))) if one else (None, None)


def workplace(location: str, full_text: str = "") -> tuple[str, str | None]:
    rules = load_config("exclusion_rules.yaml")
    loc = normalized_text(location)
    combined = f"{loc} {full_text}"
    if contains_any(combined, rules["long_term_travel_keywords"]):
        return "suspicious", "深圳" if contains_any(loc, rules["allowed_city_keywords"]) else None
    if contains_any(loc, rules["ambiguous_location_keywords"]):
        return "optional_unconfirmed", "深圳" if "深圳" in loc else None
    has_sz = contains_any(loc, rules["allowed_city_keywords"])
    has_other = contains_any(loc, rules["other_city_keywords"])
    if has_sz and not has_other:
        return "confirmed_shenzhen", "深圳"
    if has_sz:
        return "optional_unconfirmed", "深圳"
    return ("non_shenzhen", None) if loc else ("optional_unconfirmed", None)


def infer_state(text: str, yes_words: list[str], no_words: list[str] | None = None) -> str:
    if no_words and contains_any(text, no_words):
        return "confirmed_no"
    if contains_any(text, yes_words):
        return "confirmed_yes"
    if contains_any(text, ["完善福利", "福利齐全", "按规定", "视情况"]):
        return "unclear"
    return UNKNOWN


def infer_schedule(text: str) -> str:
    rules = load_config("benefit_rules.yaml")["schedule"]
    if contains_any(text, rules["single_rest"]):
        return "single_rest"
    if contains_any(text, rules["big_small_week"]):
        return "big_small_week"
    return infer_state(text, rules["confirmed_yes"])


def infer_role(title: str, text: str) -> str:
    rules = load_config("role_keywords.yaml")
    combined = f"{title} {text}"
    for tier in ("priority_1", "priority_2"):
        for direction, words in rules[tier].items():
            if contains_any(combined, words):
                return direction
    return "其他"


def normalize_job(data: dict[str, Any]) -> dict[str, Any]:
    description = normalized_text(data.get("description"))
    combined = " ".join(
        normalized_text(data.get(k))
        for k in ("job_title", "description", "responsibilities", "requirements", "benefits_raw")
    )
    salary_min, salary_max, salary_period = parse_salary(data.get("salary_raw"))
    exp_min, exp_max = parse_experience(data.get("experience_raw"))
    workplace_status, city = workplace(
        str(data.get("normalized_location") or data.get("location_raw", "")), combined
    )
    if data.get("location_conflict"):
        workplace_status = "needs_confirmation"
        city = "深圳" if "Shenzhen" in str(data.get("normalized_location") or "") else city
    benefits = load_config("benefit_rules.yaml")
    data.update(
        description=description,
        city=city,
        workplace_status=workplace_status,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period=salary_period,
        experience_min=exp_min,
        experience_max=exp_max,
        role_direction=infer_role(str(data.get("job_title", "")), combined),
        working_schedule=infer_schedule(combined),
        five_insurances_housing_fund=infer_state(
            combined,
            benefits["five_insurances"]["confirmed_yes"],
            benefits["five_insurances"]["confirmed_no"],
        ),
        paid_leave=infer_state(combined, benefits["paid_leave"]),
        overtime_risk="unclear" if contains_any(combined, benefits["intensity_risks"]) else UNKNOWN,
        internship_conversion=infer_state(
            combined, ["可转正", "留用机会", "转正机会"], ["无转正", "不留用"]
        ),
        content_hash=hashlib.sha256(normalized_text(combined).casefold().encode()).hexdigest(),
    )
    return data
