from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from app.config import contains_any, load_config
from app.qualification import QualificationAssessment, detect_seniority


@dataclass
class AssessmentResult:
    values: dict[str, Any]


class JobAnalyzer(ABC):
    @abstractmethod
    def analyze(self, job: dict[str, Any]) -> AssessmentResult: ...


class LLMJobAnalyzer(JobAnalyzer):
    def analyze(self, job: dict[str, Any]) -> AssessmentResult:
        raise RuntimeError("LLM analyzer is optional and disabled")


class RuleBasedJobAnalyzer(JobAnalyzer):
    def __init__(self) -> None:
        self.full_weights = load_config("scoring_weights.yaml")
        self.intern_weights = load_config("internship_scoring_weights.yaml")
        self.roles = load_config("role_keywords.yaml")
        self.exclusions = load_config("exclusion_rules.yaml")
        self.benefits = load_config("benefit_rules.yaml")
        self.penalties = load_config("penalty_rules.yaml")
        self.travel_rules = load_config("travel_rules.yaml")
        self.opportunity_rules = load_config("opportunity_rules.yaml")

    def analyze(self, job: dict[str, Any]) -> AssessmentResult:
        title = str(job.get("job_title") or "")
        text = " ".join(
            str(job.get(key) or "")
            for key in (
                "job_title",
                "description",
                "responsibilities",
                "requirements",
                "benefits_raw",
                "language_requirement",
                "travel_requirement",
            )
        )
        travel = self._travel(text)
        qualification = detect_seniority(
            title,
            text,
            job_type=str(job.get("job_type") or "full_time"),
            role_direction=job.get("role_direction"),
            experience_min=job.get("experience_min"),
        )
        hard_status, hard_reasons = self._hard_filter(job, title, text, travel)
        if job.get("job_type") == "internship":
            result = self._analyze_internship(job, title, text)
        else:
            result = self._analyze_full_time(job, title, text)

        base_score = sum(item["score"] for item in result["dimensions"])
        base_penalty, penalty_details, risks = self._base_penalties(job, text)
        total_penalty = base_penalty + travel["penalty"] + result["extra_penalty"]
        if travel["penalty"]:
            penalty_details.append(
                {
                    "label": f"海外出差 {travel['level']}",
                    "points": -travel["penalty"],
                    "keyword": travel["keyword"],
                    "quote": travel["quote"],
                }
            )
        risks.extend(result["risks"])
        if travel["risk_level"] in {"major", "critical"}:
            risks.append(f"海外出差风险：{travel['level']}")
        legacy_total = (
            0
            if hard_status == "excluded"
            else max(0, min(100, round(base_score - total_penalty, 1)))
        )
        questions = result["questions"] + self._travel_questions(travel)
        missing = self._missing(job, internship=job.get("job_type") == "internship")
        v3 = self._v3_scores(
            job,
            title,
            text,
            hard_status,
            hard_reasons,
            travel,
            result,
            qualification,
        )
        total = v3["fit_score"]
        grade = "A" if total >= 80 else "B" if total >= 65 else "C" if total >= 50 else "D"
        explanation = {
            "framework": "internship" if job.get("job_type") == "internship" else "full_time",
            "dimensions": result["dimensions"],
            "penalty_details": penalty_details,
            "hard_filter": {"status": hard_status, "reasons": hard_reasons},
            "travel": travel,
            "final_calculation": {
                "dimension_total": round(base_score, 1),
                "penalty_total": round(total_penalty, 1),
                "formula": v3["fit_formula"],
                "total": total,
            },
            "legacy_v2_calculation": {
                "dimension_total": round(base_score, 1),
                "penalty_total": round(total_penalty, 1),
                "total": legacy_total,
            },
            "information_states": v3["information_states"],
            "opportunity_breakdown": v3["opportunity_breakdown"],
            "risk_reasons": v3["risk_reasons"],
            "qualification": qualification.model_dump(),
        }
        strengths = [
            item["label"]
            for dim in result["dimensions"]
            for item in dim["items"]
            if item["points"] > 0
        ][:6]
        recommendation_labels = {
            "priority_apply": "优先投递：适配度和机会价值均较高",
            "apply": "建议投递：符合方向，值得投入一次简历成本",
            "try": "可以低成本尝试：存在可迁移能力，信息缺失不等于负面",
            "hold_for_info": "等待补充信息：先确认地点、资格或高风险条件",
            "do_not_apply": "不建议投递：命中硬过滤或明确重大风险",
        }
        recommendation = recommendation_labels[v3["application_recommendation"]]
        config_hash = self._config_hash()
        return AssessmentResult(
            {
                "hard_filter_status": hard_status,
                "hard_filter_reasons": hard_reasons,
                **result["legacy_scores"],
                "penalty_score": round(total_penalty, 1),
                "total_score": total,
                "fit_score": v3["fit_score"],
                "opportunity_score": v3["opportunity_score"],
                "information_completeness": v3["information_completeness"],
                "risk_level": v3["risk_level"],
                "application_recommendation": v3["application_recommendation"],
                "seniority_level": qualification.seniority_level,
                "role_direction_match": qualification.role_direction_match,
                "seniority_match": qualification.seniority_match,
                "experience_match": qualification.experience_match,
                "company_type": v3["company_type"],
                "opportunity_breakdown_json": v3["opportunity_breakdown"],
                "grade": grade,
                "recommendation": recommendation,
                "strengths": strengths or ["存在部分可迁移能力"],
                "risks": list(dict.fromkeys(risks)),
                "missing_information": missing,
                "interview_questions": list(
                    dict.fromkeys(
                        questions
                        + (
                            [
                                "该岗位实际日常办公地点是深圳还是东莞？",
                                "是否需要长期在东莞办公或深圳东莞两地往返？",
                            ]
                            if job.get("location_conflict")
                            else []
                        )
                        + [f"请确认{item}。" for item in missing]
                    )
                ),
                "suggested_resume_track": job.get("role_direction") or "产品、项目与海外业务",
                "assessment_version": "v3-internship-application-value-2"
                if job.get("job_type") == "internship"
                else "v3-fulltime-application-value-2",
                "travel_level": travel["level"],
                "travel_penalty": travel["penalty"],
                "scoring_config_hash": config_hash,
                "explanation_json": explanation,
                "resume_output_potential": result["resume_output_potential"],
                "conversion_level": result.get("conversion_level"),
            }
        )

    def _analyze_full_time(self, job: dict[str, Any], title: str, text: str) -> dict[str, Any]:
        role_base = (
            17
            if job.get("role_direction") in self.roles["priority_1"]
            else 12
            if job.get("role_direction") in self.roles["priority_2"]
            else 4
        )
        role_items = self._keyword_items(text, self.roles["positive_capabilities"], 2, 8)
        role = min(25, role_base + sum(item["points"] for item in role_items))
        role_items.insert(0, self._item("目标岗位方向基础分", role_base, title, text))

        compensation, compensation_items = self._full_time_conditions(job, text)
        entry, entry_items = self._entry_score(job, title, text)
        english_items = self._keyword_items(
            text, ["英语", "english", "海外", "global", "跨文化"], 3, 15
        )
        english = min(15, sum(item["points"] for item in english_items))
        technical_items = self._keyword_items(
            text, ["电子", "硬件", "技术产品", "研发团队", "项目管理"], 2, 10
        )
        technical = min(10, sum(item["points"] for item in technical_items))
        growth_items = self._keyword_items(
            text, ["产品周期", "项目交付", "导师", "培训", "轮岗", "核心业务"], 2, 10
        )
        growth = min(10, sum(item["points"] for item in growth_items))
        company = 1 if contains_any(text, ["主体不明", "公司信息不详"]) else 3
        company_items = [self._item("企业主体基础可信度", company, "公司", text)]
        dimensions = [
            self._dimension("岗位职责与方向匹配", role, 25, role_items),
            self._dimension("薪资福利与工作条件", compensation, 20, compensation_items),
            self._dimension("应届身份与经验门槛", entry, 15, entry_items),
            self._dimension("英语及海外背景价值", english, 15, english_items),
            self._dimension("产品、项目或技术背景", technical, 10, technical_items),
            self._dimension("职业成长与可迁移性", growth, 10, growth_items),
            self._dimension("公司及业务质量", company, 5, company_items),
        ]
        return {
            "dimensions": dimensions,
            "legacy_scores": {
                "role_match_score": role,
                "compensation_benefits_score": compensation,
                "entry_level_score": entry,
                "english_overseas_score": english,
                "technical_project_score": technical,
                "career_growth_score": growth,
                "company_quality_score": company,
            },
            "extra_penalty": 0,
            "risks": [],
            "questions": [],
            "resume_output_potential": self._resume_output(text),
        }

    def _analyze_internship(self, job: dict[str, Any], title: str, text: str) -> dict[str, Any]:
        config = self.intern_weights
        role_items = self._keyword_items(text, self.roles["positive_capabilities"], 3, 15)
        direction_base = (
            10
            if job.get("role_direction") in self.roles["priority_1"]
            else 7
            if job.get("role_direction") in self.roles["priority_2"]
            else 3
        )
        role_items.insert(0, self._item("目标实习方向基础分", direction_base, title, text))
        role = min(25, direction_base + sum(item["points"] for item in role_items[1:]))

        company_items = self._keyword_items(text, config["company_value_keywords"], 3, 12)
        company_base = 6
        if contains_any(text, config["resume_output"]["low"]):
            company_base = 3
        company_items.insert(0, self._item("企业与团队基础价值", company_base, "公司", text))
        company = min(20, company_base + sum(item["points"] for item in company_items[1:]))

        conversion_level, conversion, conversion_item = self._conversion(text)
        output_level = self._resume_output(text)
        high_items = self._keyword_items(text, config["resume_output"]["high"], 2, 15)
        low_items = self._keyword_items(text, config["resume_output"]["low"], -3, 9)
        output = max(0, min(15, 5 + sum(x["points"] for x in high_items + low_items)))
        output_items = [self._item("成果产出中性基础分", 5, "职责", text), *high_items, *low_items]

        background_items = self._keyword_items(
            text, ["英语", "english", "海外", "global", "电子", "硬件", "技术"], 2, 10
        )
        background = min(10, sum(item["points"] for item in background_items))
        conditions, condition_items, condition_penalty, condition_risks = self._intern_conditions(
            job, text
        )
        mentor_items = self._keyword_items(text, config["mentor_keywords"], 1, 5)
        mentor = min(5, 1 + sum(item["points"] for item in mentor_items))
        mentor_items.insert(0, self._item("导师与履历中性基础分", 1, "实习", text))
        dimensions = [
            self._dimension("实习内容与目标方向匹配", role, 25, role_items),
            self._dimension("企业、团队及平台价值", company, 20, company_items),
            self._dimension("转正与长期机会", conversion, 15, [conversion_item]),
            self._dimension("核心业务参与和成果产出", output, 15, output_items),
            self._dimension("英语、海外及技术背景价值", background, 10, background_items),
            self._dimension("实习薪资与工作条件", conditions, 10, condition_items),
            self._dimension("导师、培训和履历价值", mentor, 5, mentor_items),
        ]
        questions = list(config["internship_questions"])
        if conversion_level == "conversion_level_1":
            questions = list(config["conversion_questions"]) + questions
        return {
            "dimensions": dimensions,
            "legacy_scores": {
                "role_match_score": role,
                "compensation_benefits_score": conditions,
                "entry_level_score": conversion,
                "english_overseas_score": background,
                "technical_project_score": output * (10 / 15),
                "career_growth_score": mentor * 2,
                "company_quality_score": company * (5 / 20),
            },
            "extra_penalty": condition_penalty,
            "risks": condition_risks,
            "questions": questions,
            "resume_output_potential": output_level,
            "conversion_level": conversion_level,
        }

    def _travel(self, text: str) -> dict[str, Any]:
        for level, rule in self.travel_rules["levels"].items():
            for keyword in rule["keywords"]:
                if contains_any(text, [keyword]):
                    return {
                        "level": level,
                        "penalty": float(rule["penalty"]),
                        "risk_level": rule["risk_level"],
                        "hard_filter": bool(rule["hard_filter"]),
                        "keyword": keyword,
                        "quote": self._quote(text, keyword),
                        "interview_question": rule.get("interview_question"),
                    }
        unknown = self.travel_rules["unknown"]
        return {
            "level": unknown["travel_level"],
            "penalty": float(unknown["penalty"]),
            "risk_level": unknown["risk_level"],
            "hard_filter": False,
            "keyword": None,
            "quote": None,
            "interview_question": None,
        }

    def _hard_filter(
        self, job: dict[str, Any], title: str, text: str, travel: dict[str, Any]
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        if travel["hard_filter"]:
            reasons.append("长期驻外或海外派驻")
        workplace = job.get("workplace_status")
        if job.get("location_conflict"):
            return "pending_confirmation", [
                str(job.get("location_conflict_reason") or "标题、结构化地点或JD地点存在冲突")
            ]
        if workplace == "non_shenzhen":
            reasons.append("工作地点非深圳")
        elif workplace != "confirmed_shenzhen" and not reasons:
            return "pending_confirmation", ["深圳办公地点未明确确认"]
        if contains_any(title, self.exclusions["pure_rd_titles"]):
            reasons.append("纯研发或强研发岗位")
        if contains_any(title, self.exclusions["undesired_titles"]):
            reasons.append("属于明确不期望岗位")
        return ("excluded", reasons) if reasons else ("eligible", [])

    def _full_time_conditions(
        self, job: dict[str, Any], text: str
    ) -> tuple[float, list[dict[str, Any]]]:
        score, items = 0.0, []
        salary = job.get("salary_min")
        if salary is None:
            items.append(self._item("薪资未公开：待确认", 0, "薪资", text))
        else:
            monthly = (
                salary
                if job.get("salary_period") == "month"
                else salary * 21.75
                if job.get("salary_period") == "day"
                else salary / 12
            )
            points = (
                6 if monthly >= 15000 else 5 if monthly >= 11000 else 3 if monthly >= 8000 else 1
            )
            score += points
            items.append(
                self._item("薪资竞争力", points, str(job.get("salary_raw") or "薪资"), text)
            )
        schedule = job.get("working_schedule")
        points = (
            6
            if schedule == "confirmed_yes"
            else 3
            if schedule in {"not_disclosed", "unclear"}
            else 2
            if schedule == "big_small_week"
            else 0
        )
        score += points
        items.append(self._item("工作时间与休息制度", points, schedule or "工时", text))
        fund = job.get("five_insurances_housing_fund")
        points = 4 if fund == "confirmed_yes" else 2 if fund in {"not_disclosed", "unclear"} else 0
        score += points
        items.append(self._item("五险一金", points, fund or "五险一金", text))
        extras = self._keyword_items(text, self.benefits["extra_benefits"], 1, 4)
        score += sum(item["points"] for item in extras)
        return min(20, score), items + extras

    def _entry_score(
        self, job: dict[str, Any], title: str, text: str
    ) -> tuple[float, list[dict[str, Any]]]:
        qualification = detect_seniority(
            title,
            text,
            job_type=str(job.get("job_type") or "full_time"),
            role_direction=job.get("role_direction"),
            experience_min=job.get("experience_min"),
        )
        if qualification.seniority_match == "low" or (
            qualification.experience_years is not None
            and qualification.experience_years >= 5
        ):
            score, label = 0, "职位资历或经验门槛明显高于应届水平"
        elif contains_any(text, ["应届", "校招", "graduate", "entry level", "无经验"]):
            score, label = 15, "明确接受应届或无经验"
        elif job.get("experience_min") in (0, None) or contains_any(
            title, self.exclusions["entry_title_keywords"]
        ):
            score, label = 11, "初级岗位或经验要求未公开"
        elif float(job.get("experience_min") or 0) <= 2:
            score, label = 8, "1至2年经验，可尝试"
        else:
            score, label = 2, "经验门槛偏高"
        return score, [self._item(label, score, str(job.get("experience_raw") or title), text)]

    def _intern_conditions(
        self, job: dict[str, Any], text: str
    ) -> tuple[float, list[dict[str, Any]], float, list[str]]:
        score, items = 0.0, []
        salary = job.get("salary_min")
        salary_points = (
            2
            if salary is None
            else 4
            if job.get("salary_period") == "day" and salary >= 200
            else 3
            if salary > 0
            else 0
        )
        score += salary_points
        items.append(
            self._item(
                "实习薪资" if salary is not None else "实习薪资未公开：中性分",
                salary_points,
                str(job.get("salary_raw") or "薪资未公开"),
                text,
            )
        )
        schedule = job.get("working_schedule")
        schedule_points = (
            3
            if schedule == "confirmed_yes"
            else 1.5
            if schedule in {"not_disclosed", "unclear"}
            else 0
        )
        score += schedule_points
        items.append(
            self._item(
                "双休和工时" if schedule == "confirmed_yes" else "工时未公开：待确认",
                schedule_points,
                schedule or "工时",
                text,
            )
        )
        allowance = self._keyword_items(text, self.intern_weights["allowance_keywords"], 1, 1)
        score += sum(item["points"] for item in allowance)
        risk_points = 2
        score += risk_points
        items.append(self._item("未发现明确工作条件风险", risk_points, "工作条件", text))
        penalty, risks = 0.0, []
        for name, rule in self.intern_weights["negative_conditions"].items():
            if contains_any(text, rule["keywords"]):
                penalty += float(rule["penalty"])
                risks.append(f"实习工作条件风险：{name}")
        return min(10, score), items + allowance, penalty, risks

    def _conversion(self, text: str) -> tuple[str, float, dict[str, Any]]:
        config = self.intern_weights["conversion"]
        for level in ("conversion_level_3", "conversion_level_2", "conversion_level_0"):
            for keyword in config[level]["keywords"]:
                if contains_any(text, [keyword]):
                    score = float(config[level]["score"])
                    return level, score, self._item(f"转正分级：{level}", score, keyword, text)
        level = "conversion_level_1"
        score = float(config[level]["score"])
        return level, score, self._item("转正信息未公开：中性基础分", score, "转正", text)

    def _base_penalties(
        self, job: dict[str, Any], text: str
    ) -> tuple[float, list[dict[str, Any]], list[str]]:
        penalty, details, risks = 0.0, [], []
        rules = [
            (job.get("working_schedule") == "single_rest", "single_rest", "单休", "单休"),
            (job.get("working_schedule") == "big_small_week", "big_small_week", "大小周", "大小周"),
            (
                job.get("five_insurances_housing_fund") == "confirmed_no"
                and job.get("job_type") != "internship",
                "no_five_insurances",
                "无五险一金",
                "五险一金",
            ),
            (
                contains_any(text, ["长期无偿加班", "无偿加班"]),
                "long_unpaid_overtime",
                "长期无偿加班",
                "无偿加班",
            ),
            (
                contains_any(text, ["底薪低", "薪资高度依赖绩效"]),
                "performance_salary_risk",
                "薪资结构风险",
                "绩效",
            ),
        ]
        for matched, key, label, keyword in rules:
            if matched:
                points = float(self.penalties[key])
                penalty += points
                risks.append(label)
                details.append(
                    {
                        "label": label,
                        "points": -points,
                        "keyword": keyword,
                        "quote": self._quote(text, keyword),
                    }
                )
        if contains_any(text, self.travel_rules["support_risk_keywords"]):
            risks.append("现场支持、轮班或跨时区响应需核实")
        return penalty, details, risks

    def _travel_questions(self, travel: dict[str, Any]) -> list[str]:
        if travel["level"] == "travel_level_0":
            return []
        if travel["level"] == "unknown":
            return list(self.travel_rules["common_interview_questions"])
        questions = [travel["interview_question"]] if travel.get("interview_question") else []
        return questions + list(self.travel_rules["common_interview_questions"][-3:])

    def _missing(self, job: dict[str, Any], *, internship: bool) -> list[str]:
        checks = {"薪资": job.get("salary_min"), "双休/工时制度": job.get("working_schedule")}
        if not internship:
            checks.update(
                {
                    "五险一金": job.get("five_insurances_housing_fund"),
                    "带薪年假": job.get("paid_leave"),
                    "劳动合同主体": job.get("contract_entity_status"),
                }
            )
        return [
            name
            for name, value in checks.items()
            if value is None or value in {"not_disclosed", "unclear", "unreliable"}
        ]

    def _resume_output(self, text: str) -> str:
        config = self.intern_weights["resume_output"]
        high = sum(contains_any(text, [word]) for word in config["high"])
        low = sum(contains_any(text, [word]) for word in config["low"])
        if high >= 2 and high > low:
            return "high"
        if low >= 2 and low >= high:
            return "low"
        if high or low:
            return "medium"
        return "unclear"

    def _v3_scores(
        self,
        job: dict[str, Any],
        title: str,
        text: str,
        hard_status: str,
        hard_reasons: list[str],
        travel: dict[str, Any],
        legacy: dict[str, Any],
        qualification: QualificationAssessment,
    ) -> dict[str, Any]:
        fit = 50.0
        fit_steps = ["可投递候选基础分 50"]
        direction = job.get("role_direction")
        if direction in self.roles["priority_1"]:
            fit += 20
            fit_steps.append("第一优先岗位方向 +20")
        elif direction in self.roles["priority_2"]:
            fit += 15
            fit_steps.append("第二优先岗位方向 +15")
        transfer_hits = sum(
            contains_any(text, [keyword]) for keyword in self.roles["positive_capabilities"]
        )
        transfer_points = min(15, transfer_hits * 3)
        fit += transfer_points
        fit_steps.append(f"可迁移能力关键词 +{transfer_points}")
        background_hits = sum(
            contains_any(text, [keyword])
            for keyword in ["英语", "english", "海外", "电子", "硬件", "项目管理"]
        )
        background_points = min(10, background_hits * 2)
        fit += background_points
        if background_points:
            fit_steps.append(f"英语、海外或技术背景 +{background_points}")

        output = legacy["resume_output_potential"]
        if output == "high":
            fit += 10
            fit_steps.append("核心业务和成果产出 +10")
        elif output == "medium":
            fit += 5
            fit_steps.append("存在可用成果产出 +5")
        elif output == "low":
            fit -= 12
            fit_steps.append("职责偏重复或辅助 -12")

        years = qualification.experience_years
        if years is not None and 0 < years <= 2:
            fit -= 5
            fit_steps.append("明确1至2年经验，轻度扣分 -5")
        elif years is not None and 3 <= years < 5:
            fit -= 20
            fit_steps.append("明确3年以上经验，明显扣分 -20")
        elif years is not None and years >= 5:
            fit -= 30
            fit_steps.append("明确5年以上经验，显著扣分 -30")
        if qualification.seniority_match == "stretch":
            fit -= 8
            fit_steps.append("职位资历略高于应届水平 -8")
        elif qualification.seniority_match == "low":
            fit -= 25
            fit_steps.append("职位资历明显高于应届水平 -25")

        if job.get("job_type") == "internship":
            conversion = legacy.get("conversion_level")
            if conversion == "conversion_level_3":
                fit += 5
                fit_steps.append("明确转正或留用 +5")
            elif conversion == "conversion_level_0":
                fit -= 4
                fit_steps.append("明确无转正 -4")

        confirmed_bad = 0
        schedule = job.get("working_schedule")
        if schedule == "confirmed_yes":
            fit += 3
            fit_steps.append("明确双休 +3")
        elif schedule == "single_rest":
            fit -= 10
            confirmed_bad += 1
            fit_steps.append("明确单休 -10")
        elif schedule == "big_small_week":
            fit -= 5
            confirmed_bad += 1
            fit_steps.append("明确大小周 -5")
        fund = job.get("five_insurances_housing_fund")
        if job.get("job_type") != "internship":
            if fund == "confirmed_yes":
                fit += 2
                fit_steps.append("明确五险一金 +2")
            elif fund == "confirmed_no":
                fit -= 6
                confirmed_bad += 1
                fit_steps.append("明确无五险一金 -6")
        if contains_any(text, ["长期无偿加班", "无偿加班"]):
            confirmed_bad += 1
        if travel["penalty"]:
            fit -= travel["penalty"]
            fit_steps.append(f"出差偏好扣分 -{travel['penalty']}")
        if output == "low":
            fit = min(fit, 55)
            fit_steps.append("低价值辅助职责使适配度封顶 55")
        if hard_status == "excluded":
            fit = min(fit, 25)
            fit_steps.append("命中硬过滤，适配度封顶 25")
        fit = round(max(0, min(100, fit)), 1)

        company_type = self._company_type(text)
        opportunity_breakdown = self._opportunity_breakdown(job, text, company_type, output)
        opportunity = round(sum(item["score"] for item in opportunity_breakdown.values()), 1)
        information_states, completeness = self._information_completeness(job, text, travel)
        risk_level, risk_reasons = self._risk_level(
            hard_status,
            hard_reasons,
            travel,
            schedule,
            fund,
            text,
            information_states,
            confirmed_bad,
        )
        recommendation = self._application_recommendation(
            fit,
            opportunity,
            completeness,
            risk_level,
            hard_status,
            job.get("job_type") == "internship",
            qualification,
        )
        return {
            "fit_score": fit,
            "opportunity_score": opportunity,
            "information_completeness": completeness,
            "risk_level": risk_level,
            "application_recommendation": recommendation,
            "company_type": company_type,
            "opportunity_breakdown": opportunity_breakdown,
            "information_states": information_states,
            "risk_reasons": risk_reasons,
            "fit_formula": "；".join(fit_steps) + f"；最终 {fit}",
        }

    def _company_type(self, text: str) -> str:
        for company_type, keywords in self.opportunity_rules["company_types"].items():
            if contains_any(text, keywords):
                return company_type
        return "unknown"

    def _opportunity_breakdown(
        self,
        job: dict[str, Any],
        text: str,
        company_type: str,
        output: str,
    ) -> dict[str, dict[str, Any]]:
        breakdown: dict[str, dict[str, Any]] = {}
        labels = {
            "platform_value": "平台与履历价值",
            "growth_value": "成长与成果价值",
            "stability_and_system": "稳定性与制度",
            "upside_and_risk": "上行空间与风险",
        }
        for key, label in labels.items():
            rules = self.opportunity_rules[key]
            positive = [word for word in rules["positive"] if contains_any(text, [word])]
            negative = [word for word in rules["negative"] if contains_any(text, [word])]
            score = 12.5 + min(12.5, len(positive) * 2.5) - min(12.5, len(negative) * 3)
            if key == "upside_and_risk" and job.get("salary_min") is not None:
                monthly = (
                    job["salary_min"]
                    if job.get("salary_period") == "month"
                    else job["salary_min"] * 21.75
                    if job.get("salary_period") == "day"
                    else job["salary_min"] / 12
                )
                if monthly >= 15000:
                    score += 4
                    positive.append("薪资上限较好")
                elif monthly >= 10000:
                    score += 2
                    positive.append("薪资处于可接受区间")
            breakdown[key] = {
                "label": label,
                "score": round(max(0, min(25, score)), 1),
                "max_score": 25,
                "positive_evidence": positive,
                "negative_evidence": negative,
                "company_type_context": company_type,
            }
        if output == "low":
            total = sum(item["score"] for item in breakdown.values())
            if total > 55:
                reduction = total - 55
                breakdown["growth_value"]["score"] = max(
                    0, breakdown["growth_value"]["score"] - reduction
                )
                breakdown["growth_value"]["negative_evidence"].append("低价值职责限制品牌溢价")
        return breakdown

    def _information_completeness(
        self,
        job: dict[str, Any],
        text: str,
        travel: dict[str, Any],
    ) -> tuple[dict[str, str], float]:
        schedule = job.get("working_schedule")
        fund = job.get("five_insurances_housing_fund")
        states = {
            "location": "confirmed_good"
            if job.get("workplace_status") == "confirmed_shenzhen"
            else "unclear"
            if job.get("workplace_status") in {"optional_unconfirmed", "suspicious"}
            else "confirmed_bad",
            "salary": "confirmed_good" if job.get("salary_min") is not None else "not_disclosed",
            "working_schedule": "confirmed_good"
            if schedule == "confirmed_yes"
            else "confirmed_bad"
            if schedule in {"single_rest", "big_small_week"}
            else schedule
            if schedule in {"unclear", "unreliable"}
            else "not_disclosed",
            "five_insurances": "confirmed_good"
            if fund == "confirmed_yes"
            else "confirmed_bad"
            if fund == "confirmed_no"
            else fund
            if fund in {"unclear", "unreliable"}
            else "not_disclosed",
            "experience": "confirmed_good" if job.get("experience_raw") else "not_disclosed",
            "education": "confirmed_good" if job.get("education_requirement") else "not_disclosed",
            "responsibilities": "confirmed_good"
            if len(str(job.get("responsibilities") or job.get("description") or "")) >= 50
            else "unclear",
            "travel": "confirmed_good" if travel["level"] != "unknown" else "not_disclosed",
            "company": "confirmed_good" if job.get("company_name") else "not_disclosed",
        }
        weights = {
            "location": 15,
            "salary": 15,
            "working_schedule": 15,
            "five_insurances": 10,
            "experience": 10,
            "education": 5,
            "responsibilities": 15,
            "travel": 10,
            "company": 5,
        }
        factors = {
            "confirmed_good": 1,
            "confirmed_bad": 1,
            "unclear": 0.35,
            "not_disclosed": 0,
            "unreliable": 0.15,
        }
        completeness = round(sum(weights[key] * factors[states[key]] for key in weights), 1)
        return states, completeness

    @staticmethod
    def _risk_level(
        hard_status: str,
        hard_reasons: list[str],
        travel: dict[str, Any],
        schedule: str | None,
        fund: str | None,
        text: str,
        information_states: dict[str, str],
        confirmed_bad: int,
    ) -> tuple[str, list[str]]:
        reasons = list(hard_reasons)
        if hard_status == "excluded" or travel["level"] == "travel_level_4":
            return "critical", reasons or ["命中硬过滤"]
        if travel["level"] == "travel_level_3":
            reasons.append("频繁海外出差")
            return "high", reasons
        if contains_any(text, ["长期无偿加班", "不签合同", "经营风险"]):
            reasons.append("存在明确重大用工或经营风险")
            return "high", reasons
        if schedule == "single_rest":
            reasons.append("明确单休")
        if fund == "confirmed_no":
            reasons.append("明确无五险一金")
        if travel["level"] == "travel_level_2":
            reasons.append("定期海外出差")
        unclear_count = sum(
            value in {"unclear", "unreliable"} for value in information_states.values()
        )
        if confirmed_bad >= 2:
            return "high", reasons
        if reasons or unclear_count >= 2:
            return "medium", reasons or ["多项信息描述模糊，需要确认"]
        return "low", []

    @staticmethod
    def _application_recommendation(
        fit: float,
        opportunity: float,
        completeness: float,
        risk_level: str,
        hard_status: str,
        internship: bool,
        qualification: QualificationAssessment,
    ) -> str:
        if hard_status == "excluded" or risk_level == "critical":
            return "do_not_apply"
        if hard_status == "pending_confirmation":
            return "hold_for_info"
        if qualification.experience_years is not None and qualification.experience_years >= 5:
            if qualification.seniority_level in {"entry", "junior", "associate"}:
                return "try" if fit >= 35 else "hold_for_info"
            return "do_not_apply"
        if qualification.seniority_level in {
            "senior_manager",
            "director",
            "head",
            "executive",
        }:
            return "do_not_apply"
        if qualification.seniority_match == "low":
            return "hold_for_info"
        if risk_level == "high":
            return "hold_for_info" if fit >= 50 else "do_not_apply"
        if fit < 35:
            return "hold_for_info"
        if fit >= 80 and opportunity >= 70:
            return "priority_apply"
        if internship and fit >= 70 and opportunity >= 68:
            return "priority_apply"
        if fit >= 65 and qualification.experience_match != "low":
            return "apply"
        if fit >= 50:
            return "try"
        if completeness < 35 and risk_level == "medium":
            return "hold_for_info"
        return "try"

    def _keyword_items(
        self, text: str, keywords: list[str], points_each: float, cap: float
    ) -> list[dict[str, Any]]:
        items, used = [], 0.0
        for keyword in keywords:
            if contains_any(text, [keyword]) and used < cap:
                points = max(-cap, min(points_each, cap - used)) if points_each > 0 else points_each
                used += abs(points) if points > 0 else 0
                items.append(self._item(f"命中“{keyword}”", points, keyword, text))
        return items

    def _config_hash(self) -> str:
        payload = json.dumps(
            [
                self.full_weights,
                self.intern_weights,
                self.roles,
                self.exclusions,
                self.benefits,
                self.penalties,
                self.travel_rules,
                self.opportunity_rules,
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _dimension(
        name: str, score: float, maximum: float, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {"name": name, "score": round(score, 1), "max_score": maximum, "items": items}

    def _item(self, label: str, points: float, keyword: str, text: str) -> dict[str, Any]:
        return {
            "label": label,
            "points": round(points, 1),
            "keyword": keyword,
            "quote": self._quote(text, keyword),
        }

    @staticmethod
    def _quote(text: str, keyword: str | None) -> str | None:
        if not keyword:
            return None
        index = text.casefold().find(keyword.casefold())
        if index < 0:
            return None
        return text[max(0, index - 35) : min(len(text), index + len(keyword) + 60)].strip()
