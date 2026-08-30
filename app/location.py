import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


SHENZHEN_DISTRICTS = {
    "罗湖",
    "福田",
    "南山",
    "盐田",
    "宝安",
    "龙岗",
    "龙华",
    "坪山",
    "光明",
    "大鹏",
}
UNKNOWN_LOCATION_VALUES = {
    "",
    "unknown",
    "not specified",
    "unspecified",
    "multiple locations",
    "various locations",
    "remote",
    "远程",
    "待定",
    "未公开",
    "不限",
    "全国",
    "全球",
}


@dataclass(frozen=True)
class LocationDecision:
    raw_location: str
    source_location_payload: str
    normalized_location: str
    location_status: str
    location_reason: str

    def model_dump(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class JobLocationEvidence:
    title_location: str
    structured_location: str
    office_location: str
    jd_location: str
    normalized_location: str
    location_status: str
    location_conflict: bool
    location_conflict_reason: str

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def greenhouse_location_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"location": None, "offices": []}
    return {
        "location": payload.get("location"),
        "offices": payload.get("offices") or [],
    }


def greenhouse_raw_location(payload: Any) -> str:
    source = greenhouse_location_payload(payload)
    location = source.get("location")
    if isinstance(location, dict) and str(location.get("name") or "").strip():
        return str(location["name"]).strip()
    values: list[str] = []
    for office in source.get("offices") or []:
        if not isinstance(office, dict):
            continue
        value = str(office.get("location") or office.get("name") or "").strip()
        if value and value not in values:
            values.append(value)
    return " | ".join(values)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def _has_shenzhen(value: str) -> bool:
    folded = value.casefold()
    return "shenzhen" in folded or "深圳" in value or any(
        district in value for district in SHENZHEN_DISTRICTS
    )


CITY_ALIASES = {
    "Shenzhen": ("shenzhen", "深圳", *SHENZHEN_DISTRICTS),
    "Dongguan": ("dongguan", "东莞", "凤岗", "雁田"),
    "Hong Kong": ("hong kong", "香港", "kwun tong", "九龙", "新界"),
    "Taipei": ("taipei", "台北"),
    "Seoul": ("seoul", "首尔"),
    "Tokyo": ("tokyo", "东京"),
    "Singapore": ("singapore", "新加坡"),
    "Shanghai": ("shanghai", "上海"),
    "Beijing": ("beijing", "北京"),
    "Guangzhou": ("guangzhou", "广州"),
}


def _cities(value: str) -> set[str]:
    folded = _clean(value).casefold()
    return {
        city
        for city, aliases in CITY_ALIASES.items()
        if any(alias.casefold() in folded for alias in aliases)
    }


def _title_location(title: str) -> str:
    return " | ".join(sorted(_cities(title)))


def _jd_location(description: str) -> str:
    text = _clean(description)
    matches = re.findall(
        r"(?:work location|workplace|工作地点|办公地点|工作地址)\s*[:：]\s*"
        r"(.{1,100}?)(?=&nbsp;|purpose of position|job description|职责|要求|$)",
        text,
        flags=re.IGNORECASE,
    )
    locations = set().union(*(_cities(match) for match in matches)) if matches else set()
    if not locations and any(word in text for word in ("凤岗镇", "雁田村")):
        locations.add("Dongguan")
    return " | ".join(sorted(locations))


def evaluate_job_location_evidence(
    *,
    title: str,
    raw_location: str,
    source_location_payload: Any = None,
    description: str = "",
) -> JobLocationEvidence:
    payload = source_location_payload if isinstance(source_location_payload, dict) else {}
    location = payload.get("location")
    structured = (
        str(location.get("name") or "").strip()
        if isinstance(location, dict)
        else str(location or raw_location or "").strip()
    )
    if not structured:
        structured = _clean(raw_location)
    office_values: list[str] = []
    for office in payload.get("offices") or []:
        if isinstance(office, dict):
            value = _clean(str(office.get("location") or office.get("name") or ""))
            if value and value not in office_values:
                office_values.append(value)
    office = " | ".join(office_values)
    title_location = _title_location(title)
    jd_location = _jd_location(description)
    evidence = {
        "标题": _cities(title_location),
        "结构化地点": _cities(structured),
        "办公室": _cities(office),
        "JD": _cities(jd_location),
    }
    all_cities = set().union(*evidence.values())
    conflict = len(all_cities) > 1
    ambiguous_shenzhen = "Shenzhen" in all_cities and any(
        marker in f"{raw_location} {structured}".casefold()
        for marker in ("/", "或", "可选", "任选", "remote")
    )
    if conflict or ambiguous_shenzhen:
        parts = [f"{label}={','.join(sorted(cities))}" for label, cities in evidence.items() if cities]
        reason = "；".join(parts) or "地点包含深圳及其他可选安排"
        return JobLocationEvidence(
            title_location=title_location,
            structured_location=structured,
            office_location=office,
            jd_location=jd_location,
            normalized_location=" | ".join(sorted(all_cities)),
            location_status="multiple_locations",
            location_conflict=True,
            location_conflict_reason=f"地点证据冲突：{reason}",
        )
    if all_cities == {"Shenzhen"}:
        return JobLocationEvidence(
            title_location,
            structured,
            office,
            jd_location,
            "Shenzhen",
            "confirmed_shenzhen",
            False,
            "",
        )
    if all_cities:
        normalized = " | ".join(sorted(all_cities))
        return JobLocationEvidence(
            title_location,
            structured,
            office,
            jd_location,
            normalized,
            "non_shenzhen",
            False,
            f"地点证据明确为非深圳：{normalized}",
        )
    fallback = evaluate_location(raw_location, job_title=title, description=description)
    return JobLocationEvidence(
        title_location,
        structured,
        office,
        jd_location,
        fallback.normalized_location,
        fallback.location_status,
        False,
        "",
    )


def _location_values(raw_location: str, source_payload: Any) -> list[str]:
    values: list[str] = []

    def append(value: Any) -> None:
        cleaned = _clean(str(value or ""))
        if cleaned and cleaned.casefold() not in {item.casefold() for item in values}:
            values.append(cleaned)

    append(raw_location)
    if isinstance(source_payload, dict):
        location = source_payload.get("location")
        append(location.get("name")) if isinstance(location, dict) else append(location)
        for office in source_payload.get("offices") or []:
            if isinstance(office, dict):
                append(office.get("location") or office.get("name"))
    return values


def _is_unknown(value: str) -> bool:
    folded = value.casefold().strip(" -|/,，")
    return folded in UNKNOWN_LOCATION_VALUES


def evaluate_location(
    raw_location: str = "",
    *,
    job_title: str = "",
    source_location_payload: Any = None,
    description: str = "",
) -> LocationDecision:
    values = _location_values(raw_location, source_location_payload)
    meaningful = [value for value in values if not _is_unknown(value)]
    shenzhen_values = [value for value in meaningful if _has_shenzhen(value)]
    other_values = [value for value in meaningful if not _has_shenzhen(value)]
    serialized_payload = json.dumps(
        source_location_payload or {}, ensure_ascii=False, default=str
    )

    if shenzhen_values and other_values:
        return LocationDecision(
            raw_location=_clean(raw_location),
            source_location_payload=serialized_payload,
            normalized_location=" | ".join(shenzhen_values + other_values),
            location_status="multiple_locations",
            location_reason="结构化地点同时包含深圳和其他地点，需确认实际工作地点",
        )
    combined = " | ".join(shenzhen_values)
    if shenzhen_values and any(marker in combined for marker in ("或", "可选", "任选")):
        return LocationDecision(
            raw_location=_clean(raw_location),
            source_location_payload=serialized_payload,
            normalized_location=combined,
            location_status="multiple_locations",
            location_reason="地点将深圳列为可选项，需确认实际工作地点",
        )
    if shenzhen_values and any(marker in combined.casefold() for marker in ("/", "remote")):
        return LocationDecision(
            raw_location=_clean(raw_location),
            source_location_payload=serialized_payload,
            normalized_location=combined,
            location_status="multiple_locations",
            location_reason="地点包含深圳及其他可选或远程安排，需确认",
        )
    if shenzhen_values:
        return LocationDecision(
            raw_location=_clean(raw_location),
            source_location_payload=serialized_payload,
            normalized_location="Shenzhen",
            location_status="confirmed_shenzhen",
            location_reason="结构化地点明确为深圳",
        )
    if meaningful:
        return LocationDecision(
            raw_location=_clean(raw_location),
            source_location_payload=serialized_payload,
            normalized_location=" | ".join(meaningful),
            location_status="non_shenzhen",
            location_reason="结构化地点明确，且不包含深圳",
        )

    if _has_shenzhen(job_title):
        return LocationDecision(
            raw_location=_clean(raw_location),
            source_location_payload=serialized_payload,
            normalized_location="Shenzhen (from title)",
            location_status="confirmed_shenzhen",
            location_reason="结构化地点缺失，职位标题明确包含深圳",
        )
    return LocationDecision(
        raw_location=_clean(raw_location),
        source_location_payload=serialized_payload,
        normalized_location="",
        location_status="unknown",
        location_reason="结构化地点和职位标题均未提供可判断的地点",
    )
