from dataclasses import asdict, dataclass
from typing import Any

from app.career_path_match import load_candidate_profile


@dataclass(frozen=True)
class ApplicationAction:
    action_type: str
    action_priority: str
    effort_level: str
    target_time: str
    resume_focus: str
    next_steps: tuple[str, ...]
    action_reason: str

    def model_dump(self) -> dict[str, str | tuple[str, ...]]:
        return asdict(self)


ACTION_LABELS = {
    "apply_now": "立即定制并投递",
    "tailor_then_apply": "定制简历后投递",
    "low_cost_apply": "低成本快速投递",
    "clarify_then_decide": "核实关键信息后决定",
    "archive_no_action": "归档，暂不行动",
}


def recommended_resume_version(
    action_type: str | None,
    career_match_level: str | None,
    personal_preference_level: str | None,
) -> str:
    """Return a dynamic resume version; this value is intentionally not persisted."""
    if action_type == "archive_no_action":
        return "无需准备简历"
    if action_type == "clarify_then_decide":
        return "暂不制作；确认后选择版本"
    if action_type == "low_cost_apply":
        return "通用快速投递版"
    if career_match_level in {"highly_aligned", "aligned"} or (
        personal_preference_level == "high_alignment"
    ):
        return "技术产品 / 项目定制版"
    if action_type in {"apply_now", "tailor_then_apply"}:
        return "能力迁移强化版"
    return "待行动层评估"


def _resume_focus(
    career_match_level: str,
    employer_acceptance_level: str,
    personal_preference_level: str,
    profile: dict[str, Any],
) -> str:
    strengths = list(profile.get("strengths") or [])
    positioning = str(profile.get("positioning") or "").strip()
    focus: list[str] = []
    if career_match_level in {"highly_aligned", "aligned"} and positioning:
        focus.append(positioning)
    if employer_acceptance_level in {"uncertain", "low"}:
        focus.extend(strengths[:4])
        focus.append("用项目成果弥补正式工作经验不足")
    else:
        focus.extend(strengths[:3])
    if personal_preference_level == "high_alignment":
        focus.append("明确长期投入该方向的动机")
    return "；".join(dict.fromkeys(focus)) or "突出与岗位最相关的教育、项目和技能证据"


def recommend_application_action(
    *,
    final_strategy: str,
    career_match_level: str,
    career_match_score: float,
    employer_acceptance_level: str,
    employer_acceptance_score: float,
    personal_preference_level: str,
    personal_preference_score: float,
    profile: dict[str, Any] | None = None,
) -> ApplicationAction:
    """Translate stable decision outputs into a next action without rescoring the job."""
    profile = profile or load_candidate_profile()
    focus = _resume_focus(
        career_match_level,
        employer_acceptance_level,
        personal_preference_level,
        profile,
    )

    if final_strategy == "priority_apply":
        return ApplicationAction(
            "apply_now",
            "urgent",
            "high",
            "24_hours",
            focus,
            (
                "确认岗位仍在招聘并复核硬性要求",
                "按JD定制简历首屏、项目经历和关键词",
                "准备简短求职动机并完成投递",
                "将Candidate Status更新为applied",
            ),
            "最终策略为优先投递，应把时间优先用于高质量定制并尽快提交",
        )

    if final_strategy == "targeted_apply":
        acceptance_note = (
            "重点补强招聘方可能质疑的直接经验与岗位关键词"
            if employer_acceptance_score < 60
            else "用最相关项目证明能力可以迁移到岗位"
        )
        return ApplicationAction(
            "tailor_then_apply",
            "high",
            "medium",
            "48_hours",
            focus,
            (
                acceptance_note,
                "选择2至3段最相关项目并改写为成果导向表述",
                "完成一次针对性简历检查后投递",
                "将Candidate Status更新为applied",
            ),
            "岗位值得投入，但需要针对职业跨度或招聘方接受度定制申请材料",
        )

    if final_strategy in {"low_cost_try", "stretch_apply"}:
        stretch = final_strategy == "stretch_apply"
        return ApplicationAction(
            "low_cost_apply",
            "medium",
            "low",
            "this_week",
            focus,
            (
                "使用最接近岗位方向的现有简历版本",
                "明确呈现可迁移能力并诚实处理经验差距" if stretch else "只调整标题、摘要和核心关键词",
                "控制准备时间并投递验证经验门槛" if stretch else "控制准备时间并直接投递验证市场反馈",
                "记录是否获得回复",
            ),
            (
                "岗位价值较高但经验门槛超出当前履历，仅适合控制成本的拉伸申请"
                if stretch
                else "岗位存在一定价值但不适合高投入，应用低成本投递获取真实反馈"
            ),
        )

    if final_strategy == "hold":
        if career_match_level == "conflicting" or career_match_score < 35:
            clarification = "先确认地点、资历或个人硬限制是否真实冲突"
        elif employer_acceptance_level in {"low", "uncertain"} or employer_acceptance_score < 45:
            clarification = "先核实经验年限、学历和应届生资格是否为硬性要求"
        else:
            clarification = "先补充工作地点、职责范围、招聘状态和关键待遇信息"
        priority = (
            "high"
            if career_match_score >= 65 and personal_preference_score >= 65
            else "medium"
        )
        return ApplicationAction(
            "clarify_then_decide",
            priority,
            "low",
            "before_applying",
            focus,
            (
                clarification,
                "优先通过JD原页、招聘方或面试沟通获取确认",
                "确认后重新选择投递或归档，不重写基础评分",
            ),
            "最终策略为等待确认，下一步是消除阻塞信息而不是立即投递或直接放弃",
        )

    if final_strategy == "skip":
        return ApplicationAction(
            "archive_no_action",
            "none",
            "none",
            "no_action",
            focus,
            (
                "记录跳过原因",
                "不投入简历定制时间",
                "仅在岗位条件发生实质变化时重新评估",
            ),
            "最终策略为跳过，应保护求职时间并避免无效申请投入",
        )

    raise ValueError(f"未知 final_strategy：{final_strategy}")
