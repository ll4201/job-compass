"use strict";

const STRATEGIES = [
  ["priority_apply", "优先投递"],
  ["targeted_apply", "定制投递"],
  ["stretch_apply", "拉伸申请"],
  ["low_cost_try", "低成本尝试"],
  ["hold", "暂缓确认"],
  ["skip", "跳过"],
  ["unassessed", "待正式评估"],
];
const STORED_STRATEGY_ORDER = Object.fromEntries(STRATEGIES.map(([value], index) => [value, index]));
const WORKFLOW_STATUSES = ["new", "saved", "preparing", "applied", "interviewing", "offer", "closed"];

const state = { jobs: [], sources: [], collectionSummary: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function display(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : escapeHtml(value);
}

function number(value) {
  return Number.isFinite(Number(value)) ? Math.round(Number(value)) : "—";
}

function dateText(value) {
  if (!value) return "未公开";
  const date = new Date(String(value).replace(" ", "T") + (String(value).endsWith("Z") ? "" : "Z"));
  return Number.isNaN(date.getTime()) ? escapeHtml(String(value).slice(0, 10)) : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Shanghai" }).format(date);
}

function getLocal(key, fallback) {
  try {
    const value = localStorage.getItem(`job-compass-static:${key}`);
    return value ? JSON.parse(value) : fallback;
  } catch (_) {
    return fallback;
  }
}

function setLocal(key, value) {
  try {
    localStorage.setItem(`job-compass-static:${key}`, JSON.stringify(value));
    return true;
  } catch (_) {
    return false;
  }
}

function candidateStatus(job) {
  return getLocal("candidate-status", {})[job.id] || job.candidate_status || "new";
}

function isEffectivelyActive(job) {
  return !job.is_sample && job.availability_status === "active" && job.is_active;
}

function queryOrder(a, b) {
  const aOrder = STORED_STRATEGY_ORDER[a.assessment.final_strategy] ?? 99;
  const bOrder = STORED_STRATEGY_ORDER[b.assessment.final_strategy] ?? 99;
  return aOrder - bOrder || Number(b.assessment.fit_score || 0) - Number(a.assessment.fit_score || 0);
}

function filterValues() {
  return {
    q: $("#filter-search").value.trim().toLocaleLowerCase("zh-CN"),
    company: $("#filter-company").value,
    source: $("#filter-source").value,
    origin: $("#filter-origin").value,
    freshness: $("#filter-freshness").value,
    jobType: $("#filter-job-type").value,
    recommendation: $("#filter-recommendation").value,
    strategy: $("#filter-strategy").value,
    action: $("#filter-action").value,
    workflow: $("#filter-workflow").value,
    jobFilter: $("#filter-job").value,
    newOnly: $("#filter-new").checked,
    includeInactive: $("#filter-inactive").checked,
    includeTest: $("#filter-test").checked,
  };
}

function filteredJobs() {
  const filters = filterValues();
  const freshnessHours = { "24h": 24, "3d": 72, "7d": 168 };
  const cutoff = filters.freshness ? Date.now() - freshnessHours[filters.freshness] * 3600000 : null;
  return state.jobs.filter((job) => {
    const assessment = job.assessment;
    if (!filters.includeTest && job.is_sample) return false;
    if (!filters.includeInactive && !isEffectivelyActive(job)) return false;
    if (filters.q && !`${job.company_name} ${job.job_title}`.toLocaleLowerCase("zh-CN").includes(filters.q)) return false;
    if (filters.company && job.company_name !== filters.company) return false;
    if (filters.source && !(job.source_ids || []).includes(filters.source)) return false;
    if (filters.origin === "automatic" && ["manual", "csv"].includes(job.source)) return false;
    if (filters.origin === "manual" && !["manual", "csv"].includes(job.source)) return false;
    if (cutoff && new Date(String(job.first_seen_at).replace(" ", "T") + "Z").getTime() < cutoff) return false;
    if (filters.jobType && job.job_type !== filters.jobType) return false;
    if (filters.recommendation && assessment.application_recommendation !== filters.recommendation) return false;
    if (filters.strategy && job.effective_strategy !== filters.strategy) return false;
    if (filters.action && job.action.type !== filters.action) return false;
    if (filters.workflow && candidateStatus(job) !== filters.workflow) return false;
    if (filters.newOnly && !job.is_new) return false;
    if (filters.jobFilter === "confirmed_shenzhen" && job.location_conflict) return false;
    if (filters.jobFilter === "location_conflict" && !job.location_conflict) return false;
    if (filters.jobFilter === "entry_level" && !["internship", "graduate", "entry", "junior", "associate"].includes(assessment.seniority_level)) return false;
    if (filters.jobFilter === "seniority_too_high" && assessment.seniority_match !== "low") return false;
    if (filters.jobFilter === "experience_too_high" && assessment.experience_match !== "low") return false;
    return true;
  }).sort(queryOrder);
}

function renderCollectionSummary() {
  const summary = state.collectionSummary;
  if (!summary) return;
  const section = $("#collection-summary");
  section.hidden = false;
  section.innerHTML = `
    <div><small>最近一次采集</small><b>${display(summary.source_name, "未知来源")}</b><span>${display(summary.status)}${summary.dry_run ? " · dry-run" : ""}</span></div>
    <div><b>${number(summary.new_count)}</b><span>新增岗位</span></div>
    <div><b>${number(summary.priority_apply)}</b><span>优先投递</span></div>
    <div><b>${number(summary.apply)}</b><span>建议投递</span></div>
    <div><b>${number(summary.try)}</b><span>可以尝试</span></div>
    <div><b>${number(summary.hold)}</b><span>待确认</span></div>
    <div><b>${number(summary.filtered)}</b><span>非深圳排除</span></div>
    <div><b>${number(summary.failed_sources)}</b><span>失败来源</span></div>`;
}

function detailLink(job, label = job.job_title) {
  return `<a class="job-detail-link" data-job-id="${job.id}" href="?job=${job.id}">${escapeHtml(label)}</a>`;
}

function renderDashboard(jobs) {
  const groups = { apply_now: [], tailor_then_apply: [], low_cost_apply: [], clarify_then_decide: [] };
  jobs.forEach((job) => {
    const a = job.assessment;
    if (!isEffectivelyActive(job) || !groups[job.action.type]) return;
    const required = [a.final_strategy, a.career_match_level, a.career_match_score, a.employer_acceptance_level, a.employer_acceptance_score, a.personal_preference_level, a.personal_preference_score];
    if (required.some((value) => value === null || value === undefined)) return;
    groups[job.action.type].push(job);
  });
  const applyNow = groups.apply_now.map((job) => `<section class="action-item"><h3>${detailLink(job)}</h3><p>${escapeHtml(job.company_name)} · ${display(job.location_raw || job.normalized_location, "地点待确认")}</p><div class="action-tags"><span>${escapeHtml(job.action.priority)}</span><span>${escapeHtml(job.action.recommended_resume_label)}</span></div><ol>${job.action.next_steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol></section>`).join("") || '<p class="action-empty">今天没有必须立即投递的岗位。</p>';
  const tailor = groups.tailor_then_apply.map((job) => `<section class="action-item"><h3>${detailLink(job)}</h3><p>${escapeHtml(job.company_name)}</p><strong>${escapeHtml(job.action.recommended_resume_label)}</strong><small>${escapeHtml(job.action.resume_focus)}</small></section>`).join("") || '<p class="action-empty">暂无需要定制后投递的岗位。</p>';
  const quick = groups.low_cost_apply.map((job) => `<section class="action-item"><h3>${detailLink(job)}</h3><p>${escapeHtml(job.company_name)} · ${escapeHtml(job.action.recommended_resume_label)}</p><div class="action-tags"><span>${escapeHtml(job.action.priority)}</span><span>控制准备成本</span></div></section>`).join("") || '<p class="action-empty">暂无低成本验证岗位。</p>';
  $("#daily-actions").classList.remove("static-loading");
  $("#daily-actions").innerHTML = `
    <article class="action-lane action-now" data-action-type="apply_now" data-action-count="${groups.apply_now.length}"><div class="action-lane-head"><div><span>A</span><h2>立即投递</h2></div><b>${groups.apply_now.length}</b></div><div class="action-items">${applyNow}</div></article>
    <article class="action-lane action-week" data-action-type="tailor_then_apply" data-action-count="${groups.tailor_then_apply.length}"><div class="action-lane-head"><div><span>B</span><h2>本周准备</h2></div><b>${groups.tailor_then_apply.length}</b></div><div class="action-items">${tailor}</div></article>
    <article class="action-lane action-quick" data-action-type="low_cost_apply" data-action-count="${groups.low_cost_apply.length}"><div class="action-lane-head"><div><span>C</span><h2>快速验证</h2></div><b>${groups.low_cost_apply.length}</b></div><div class="action-items">${quick}</div></article>
    <a class="action-lane action-hold" id="filter-hold" data-action-type="clarify_then_decide" data-action-count="${groups.clarify_then_decide.length}" href="#job-pool"><span>D · 待确认岗位</span><strong>${groups.clarify_then_decide.length}个岗位等待确认</strong><small>查看岗位并逐项核实关键信息 →</small></a>`;
  bindDetailLinks();
  $("#filter-hold").addEventListener("click", () => {
    $("#filter-action").value = "clarify_then_decide";
    renderHome();
  });
}

function jobCard(job) {
  const a = job.assessment;
  return `<article class="job-card demo-only-job-card ${job.is_new ? "new-job" : ""}">
    <div class="score grade-${escapeHtml(a.grade)}"><b>${number(a.fit_score ?? a.total_score)}</b><span>适配度</span></div>
    <div class="job-main"><div class="meta">${job.is_new ? '<span class="new-tag">NEW</span>' : ""}${job.is_sample ? "<span>TEST / SAMPLE</span>" : ""}<span class="action-tag action-tag-${escapeHtml(job.action.type)}">${escapeHtml(job.action.label)}</span><span>${display(job.role_direction)}</span><span>${job.job_type === "internship" ? "实习" : "正式"}</span><span>${number(job.source_count)} 个来源</span><span>${display(job.availability_status)}</span><span>${display(a.risk_level, "待重评")}</span></div>
      <h2>${detailLink(job)}</h2><p class="company">${escapeHtml(job.company_name)} · ${display(job.location_raw)}</p><div class="mini-metrics"><span>机会 ${number(a.opportunity_score)}</span><span>完整度 ${number(a.information_completeness)}</span><strong>${escapeHtml(job.effective_strategy)}</strong><span>V3 ${display(a.application_recommendation, "待重评")}</span></div><p>${display(a.decision_reason || a.recommendation)}</p></div>
    <div class="facts"><span>${display(job.salary_raw, "薪资未公开")}</span><span>${["manual", "csv"].includes(job.source) ? "手动录入" : "自动采集"}</span><span>Candidate: ${escapeHtml(candidateStatus(job))}</span></div>
  </article>`;
}

function renderJobGroups(jobs) {
  const groups = Object.fromEntries(STRATEGIES.map(([key]) => [key, []]));
  jobs.forEach((job) => (groups[job.effective_strategy] ||= []).push(job));
  const html = STRATEGIES.map(([strategy, label]) => groups[strategy]?.length ? `<section class="strategy-group"><h2>${label} <small>${groups[strategy].length}</small></h2><section class="jobs">${groups[strategy].map(jobCard).join("")}</section></section>` : "").join("");
  $("#job-groups").classList.remove("static-loading");
  $("#job-groups").innerHTML = html || '<div class="empty"><h2>暂无匹配结果</h2></div>';
  bindDetailLinks();
}

function renderHome() {
  const jobs = filteredJobs();
  $("#hero-job-count").textContent = jobs.length;
  $("#note-job-count").textContent = state.jobs.length;
  renderDashboard(jobs);
  renderJobGroups(jobs);
}

function list(items, empty = "暂无") {
  return items?.length ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<ul><li>${empty}</li></ul>`;
}

function recommendedResumeVersion(job) {
  const a = job.assessment;
  if (job.action.type === "archive_no_action") return "无需准备简历";
  if (job.action.type === "clarify_then_decide") return "暂不制作；确认后选择版本";
  if (job.action.type === "low_cost_apply") return "通用快速投递版";
  if (["highly_aligned", "aligned"].includes(a.career_match_level) || a.personal_preference_level === "high_alignment") return "技术产品 / 项目定制版";
  if (["apply_now", "tailor_then_apply"].includes(job.action.type)) return "能力迁移强化版";
  return "待行动层评估";
}

function renderDetail(job, push = true) {
  if (!job) {
    showNotice("岗位不存在或静态快照中没有该记录。", true);
    showHome(false);
    return;
  }
  if (push) {
    const url = new URL(location.href);
    url.searchParams.set("job", job.id);
    url.hash = "";
    history.pushState({ job: job.id }, "", url);
  }
  document.title = `${job.job_title} · Job Compass`;
  $("#page-notice").hidden = true;
  $("#list-view").hidden = true;
  const root = $("#detail-view");
  root.hidden = false;
  const a = job.assessment;
  const explanation = a.explanation_json || {};
  const application = explanation.application_strategy || {};
  const feedback = getLocal(`feedback:${job.id}`, { applied: "", reason: "", result: "", notes: "" });
  const review = getLocal(`review:${job.id}`, { grade: "", score: "", decision: "", calibration: "", comment: "" });
  const status = candidateStatus(job);
  root.innerHTML = `
    <section class="detail-head"><div><p class="eyebrow">${escapeHtml(job.company_name)} · ${display(job.location_raw)}</p><h1>${escapeHtml(job.job_title)}</h1><div class="meta"><span>${display(job.role_direction)}</span><span>${job.job_type === "internship" ? "实习" : "正式"}</span><span>Candidate: ${escapeHtml(status)}</span><span>${display(job.travel_level)}</span></div></div><div class="big-score grade-${escapeHtml(a.grade)}"><b>${number(a.total_score)}</b><span>系统 ${escapeHtml(a.grade)} 档</span></div></section>
    <p class="demo-safe-note">这是完全虚构的展示岗位。Candidate Status、Feedback 与人工评价仅保存在当前浏览器；重新评分、证据增删、采集和删除操作在静态 Demo 中不可用。</p>
    ${!isEffectivelyActive(job) ? `<div class="notice"><strong>历史/开发岗位：</strong>${job.is_sample ? "TEST / SAMPLE" : display(job.availability_status)}。当前有效岗位门禁已阻止该岗位进入推荐与每日行动区。${job.closure_reason ? ` 原因：${escapeHtml(job.closure_reason)}` : ""}</div>` : ""}

    <h2>V3 原始判断</h2>
    <section class="score-triad"><div><span>岗位适配度</span><b>${number(a.fit_score)}</b><small>是否符合方向与基本资格</small></div><div><span>机会价值</span><b>${number(a.opportunity_score)}</b><small>平台、成长、制度和上行空间</small></div><div><span>信息完整度</span><b>${number(a.information_completeness)}</b><small>缺失信息只在这里体现</small></div><div><span>风险等级</span><b class="risk-${escapeHtml(a.risk_level)}">${display(a.risk_level, "待重评")}</b></div><div><span>V3 投递建议</span><b>${display(a.application_recommendation, "待重评")}</b></div></section>

    <section class="personal-decision"><h2>个人决策分析</h2><section class="score-triad"><div><span>Career Match</span><b>${number(a.career_match_score)}</b><small>${display(a.career_match_level)}</small></div><div><span>Career Value</span><b>${number(a.career_value_score)}</b><small>${display(a.career_value_level)}</small></div><div><span>Employer Acceptance</span><b>${number(a.employer_acceptance_score)}</b><small>${display(a.employer_acceptance_level)}</small></div><div><span>Personal Preference</span><b>${number(a.personal_preference_score)}</b><small>${display(a.personal_preference_level)}</small></div><div><span>当前有效策略</span><b>${escapeHtml(job.effective_strategy)}</b><small>历史存储：${display(a.final_strategy, "待正式评估")}</small></div></section><p><strong>决策原因：</strong>${display(a.decision_reason)}</p>${Object.keys(application).length ? `<details><summary>查看各维度解释</summary><ul><li>${display(application.career_match?.career_match_reason)}</li><li>${display(application.career_value?.career_value_reason)}</li><li>${display(application.employer_acceptance?.employer_acceptance_reason)}</li><li>${display(application.personal_preference?.personal_preference_reason)}</li></ul></details>` : ""}</section>

    <section class="explain-summary"><div><span>推荐行动</span><b>${escapeHtml(job.action.label)}</b><small>${escapeHtml(job.action.type)}</small></div><div><span>推荐简历版本</span><b>${escapeHtml(recommendedResumeVersion(job))}</b></div><div><span>行动优先级</span><b>${job.action.type === a.action_type ? display(a.action_priority) : "blocked"}</b></div><div><span>候选人配置版本</span><b>${display(a.profile_version, "未记录")}</b></div></section>

    <section class="personal-decision"><h2>P1 Shadow 多维判断</h2><p class="notice">仅供人工复核，不修改当前 Final Strategy 或行动层。</p><section class="score-triad"><div><span>Eligibility</span><b>${number(a.eligibility_score)}</b></div><div><span>Direction Fit</span><b>${number(a.direction_fit_score)}</b></div><div><span>Career Value</span><b>${number(a.career_value_score)}</b></div><div><span>Life Quality</span><b>${number(a.life_quality_score)}</b></div><div><span>Compensation</span><b>${number(a.compensation_score)}</b></div><div><span>Freshness</span><b>${number(a.freshness_score)}</b><small>${display(a.job_age_days)} days · ${display(a.date_source)}</small></div><div><span>Overall Priority</span><b>${number(a.overall_priority_score)}</b></div><div><span>Proposed Strategy</span><b>${escapeHtml(job.effective_strategy)}</b></div><div><span>Resume Type</span><b>${display(a.resume_type)}</b></div><div><span>Support Type</span><b>${display(a.support_role_type)}</b></div></section></section>

    <section class="detail-grid" id="candidate-workflow"><article><h2>Candidate Status</h2><div class="static-detail-toolbar"><label>当前状态<select id="candidate-status">${WORKFLOW_STATUSES.map((value) => `<option value="${value}" ${value === status ? "selected" : ""}>${value}</option>`).join("")}</select></label></div><p class="static-save-note" id="candidate-save-note"></p><h3>状态历史</h3><ul><li>静态 Demo 的状态变化仅保存在当前浏览器。</li></ul></article><article id="application-feedback"><h2>Feedback</h2><p>共享 Demo，请勿输入姓名、邮箱、电话或其他个人信息。</p><form class="static-feedback-form" id="feedback-form"><label>是否投递<select name="applied"><option value="">未记录</option><option value="yes" ${feedback.applied === "yes" ? "selected" : ""}>是</option><option value="no" ${feedback.applied === "no" ? "selected" : ""}>否</option></select></label><label>未投原因<input name="reason" maxlength="80" value="${escapeHtml(feedback.reason)}"></label><label>面试结果<input name="result" maxlength="80" value="${escapeHtml(feedback.result)}"></label><label>备注<textarea name="notes" maxlength="500" rows="4">${escapeHtml(feedback.notes)}</textarea></label><button type="submit">保存反馈</button><p class="static-save-note" id="feedback-save-note"></p></form></article></section>

    <section class="explain-summary"><div><span>评分框架</span><b>${explanation.framework === "internship" ? "实习独立框架" : "正式岗位框架"}</b></div><div><span>企业类型</span><b>${display(a.company_type, "unknown")}</b></div><div><span>硬过滤</span><b>${display(a.hard_filter_status)}</b></div><div><span>出差等级</span><b>${display(a.travel_level)}</b></div><div><span>配置版本</span><b>${display(a.assessment_version)}</b></div></section>

    <section class="detail-grid"><article><h2>地点证据</h2><dl><dt>标题地点</dt><dd>${display(job.title_location, "未提及")}</dd><dt>结构化地点</dt><dd>${display(job.structured_location, "未提供")}</dd><dt>办公室地点</dt><dd>${display(job.office_location, "未提供")}</dd><dt>JD 地点</dt><dd>${display(job.jd_location, "未提及")}</dd><dt>标准化地点</dt><dd>${display(job.normalized_location || job.location_raw, "待确认")}</dd><dt>地点冲突</dt><dd>${job.location_conflict ? "是" : "否"}${job.location_conflict_reason ? `：${escapeHtml(job.location_conflict_reason)}` : ""}</dd></dl></article><article><h2>应届资格匹配</h2><dl><dt>职位资历</dt><dd>${display(a.seniority_level, "unknown")}</dd><dt>方向匹配</dt><dd>${display(a.role_direction_match, "unknown")}</dd><dt>资历匹配</dt><dd>${display(a.seniority_match, "unknown")}</dd><dt>经验匹配</dt><dd>${display(a.experience_match, "unknown")}</dd></dl></article></section>

    <section class="opportunity-panel"><h2>机会价值构成</h2><div class="opportunity-grid">${Object.values(explanation.opportunity_breakdown || a.opportunity_breakdown_json || {}).map((item) => `<article><h3>${display(item.label)}</h3><b>${number(item.score)} / ${number(item.max_score)}</b><p>加分证据：${item.positive_evidence?.length ? item.positive_evidence.map(escapeHtml).join("、") : "未明确披露"}</p><p>风险证据：${item.negative_evidence?.length ? item.negative_evidence.map(escapeHtml).join("、") : "未发现明确负面"}</p></article>`).join("")}</div></section>
    <section class="information-panel"><h2>信息状态</h2><div class="state-grid">${Object.entries(explanation.information_states || {}).map(([key, value]) => `<div><span>${escapeHtml(key)}</span><b class="state-${escapeHtml(value)}">${escapeHtml(value)}</b></div>`).join("")}</div><p>未公开信息只降低信息完整度，不直接降低适配度或机会价值。</p></section>
    <section class="dimension-list"><h2>评分如何产生</h2>${(explanation.dimensions || []).map((dimension) => `<article class="dimension"><header><h3>${escapeHtml(dimension.name)}</h3><strong>${number(dimension.score)} / ${number(dimension.max_score)}</strong></header><progress value="${Number(dimension.score) || 0}" max="${Number(dimension.max_score) || 1}"></progress>${dimension.items?.length ? `<ul>${dimension.items.map((item) => `<li class="${Number(item.points) < 0 ? "negative" : ""}"><b>${Number(item.points) >= 0 ? "+" : ""}${number(item.points)}</b> ${display(item.label)}${item.quote ? `<blockquote>JD 引用：${escapeHtml(item.quote)}</blockquote>` : ""}</li>`).join("")}</ul>` : "<ul><li>未命中明确关键词，使用中性或基础判断。</li></ul>"}</article>`).join("")}</section>
    <section class="calculation"><h2>最终总分</h2><p class="formula">${display(explanation.final_calculation?.formula, "暂无计算说明")}</p><h3>硬过滤判断</h3><p>${display(a.hard_filter_status)}</p>${list(a.hard_filter_reasons, "未命中排除规则")}</section>
    <div class="detail-grid"><article><h3>判断摘要</h3><p>${display(a.recommendation)}</p><h3>主要优势</h3>${list(a.strengths)}<h3>风险</h3>${list(a.risks, "暂未识别到明确重大风险")}<h3>缺失信息</h3>${list(a.missing_information, "核心信息较完整")}<h3>面试确认问题</h3>${list(a.interview_questions)}</article><aside><h3>岗位信息</h3><dl><dt>薪资</dt><dd>${display(job.salary_raw, "未公开")}</dd><dt>经验</dt><dd>${display(job.experience_raw, "未公开")}</dd><dt>双休</dt><dd>${display(job.working_schedule)}</dd><dt>五险一金</dt><dd>${display(job.five_insurances_housing_fund)}</dd><dt>简历产出</dt><dd>${display(job.resume_output_potential)}</dd><dt>转正等级</dt><dd>${display(job.conversion_level, "不适用")}</dd></dl></aside></div>
    <article class="jd"><h3>原始职位信息</h3><p>${display(job.description)}</p>${job.benefits_raw ? `<h3>福利</h3><p>${escapeHtml(job.benefits_raw)}</p>` : ""}</article>

    <section class="manual-review"><h2>人工评价</h2><p>人工评价用于校准，不会覆盖系统分数与系统评级。共享 Demo，请勿输入任何个人信息。</p><form id="review-form"><div class="review-grid"><label>我认为的档位<select name="grade"><option value="">未选择</option>${["A", "B", "C", "D"].map((value) => `<option value="${value}" ${review.grade === value ? "selected" : ""}>${value} 档</option>`).join("")}</select></label><label>人工分数<input type="number" name="score" min="0" max="100" step="0.5" value="${escapeHtml(review.score)}"></label><label>是否愿意投递<select name="decision"><option value="">未选择</option><option value="priority_apply" ${review.decision === "priority_apply" ? "selected" : ""}>优先投递</option><option value="apply" ${review.decision === "apply" ? "selected" : ""}>愿意投递</option><option value="maybe" ${review.decision === "maybe" ? "selected" : ""}>可以考虑</option><option value="do_not_apply" ${review.decision === "do_not_apply" ? "selected" : ""}>不投递</option></select></label><label>系统判断偏差<select name="calibration"><option value="">按分数自动判断</option><option value="aligned" ${review.calibration === "aligned" ? "selected" : ""}>基本一致</option><option value="overestimated" ${review.calibration === "overestimated" ? "selected" : ""}>系统高估</option><option value="underestimated" ${review.calibration === "underestimated" ? "selected" : ""}>系统低估</option></select></label><label class="wide">偏差原因与人工评论<textarea name="comment" maxlength="500" rows="5">${escapeHtml(review.comment)}</textarea></label></div><button type="submit">保存人工评价</button><p class="static-save-note" id="review-save-note"></p></form></section>

    <section class="history"><h2>评分历史</h2><div class="static-history-scroll"><table><thead><tr><th>时间</th><th>版本</th><th>旧总分</th><th>适配</th><th>机会</th><th>完整度</th><th>风险</th><th>V3建议</th><th>最终策略</th><th>评级</th></tr></thead><tbody>${job.assessment_history.length ? job.assessment_history.map((item) => `<tr><td>${dateText(item.assessed_at)}</td><td>${display(item.assessment_version)}</td><td>${number(item.total_score)}</td><td>${number(item.fit_score)}</td><td>${number(item.opportunity_score)}</td><td>${number(item.information_completeness)}</td><td>${display(item.risk_level)}</td><td>${display(item.application_recommendation)}</td><td>${display(item.final_strategy)}</td><td>${display(item.grade)}</td></tr>`).join("") : '<tr><td colspan="10">尚无重新评分历史。</td></tr>'}</tbody></table></div></section>
    <section class="evidence-section" id="external-evidence"><div class="section-heading"><div><h2>外部证据</h2><p>员工分享和沟通记录仅作为辅助证据，不替代原始 JD 与 V3 基础评分。</p></div></div><div class="evidence-list">${job.evidence.length ? job.evidence.map((item) => `<article><header><div><b>${display(item.evidence_category)}</b> <span>${display(item.source_platform)}</span> <span>${display(item.verification_status)}</span></div><small>${dateText(item.published_at)} · ${display(item.city, "城市未公开")} · ${display(item.department, "部门未公开")} · 相关度 ${display(item.relevance_level)}</small></header><h3>${display(item.source_title, "未命名证据")}</h3><p>${display(item.evidence_value || item.evidence_text)}</p></article>`).join("") : '<p class="empty-state">尚未录入外部证据。搜不到员工分享不会降低岗位评分。</p>'}</div></section>`;
  bindDetailInteractions(job);
  window.scrollTo(0, 0);
}

function bindDetailInteractions(job) {
  $("#candidate-status").addEventListener("change", (event) => {
    const values = getLocal("candidate-status", {});
    values[job.id] = event.target.value;
    $("#candidate-save-note").textContent = setLocal("candidate-status", values) ? "已保存到当前浏览器。" : "浏览器禁止本地存储，状态未保存。";
  });
  $("#feedback-form").addEventListener("submit", (event) => {
    event.preventDefault();
    $("#feedback-save-note").textContent = setLocal(`feedback:${job.id}`, Object.fromEntries(new FormData(event.currentTarget))) ? "已保存到当前浏览器。" : "浏览器禁止本地存储，反馈未保存。";
  });
  $("#review-form").addEventListener("submit", (event) => {
    event.preventDefault();
    $("#review-save-note").textContent = setLocal(`review:${job.id}`, Object.fromEntries(new FormData(event.currentTarget))) ? "已保存到当前浏览器。" : "浏览器禁止本地存储，评价未保存。";
  });
}

function bindDetailLinks() {
  $$(".job-detail-link").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    renderDetail(state.jobs.find((job) => job.id === Number(link.dataset.jobId)));
  }));
}

function showHome(push) {
  if (push) {
    const url = new URL(location.href);
    url.searchParams.delete("job");
    url.hash = "job-pool";
    history.pushState({}, "", url);
  }
  document.title = "Job Compass";
  $("#detail-view").hidden = true;
  $("#list-view").hidden = false;
  renderHome();
  if (push) requestAnimationFrame(() => $("#job-pool").scrollIntoView());
}

function showNotice(message, error = false) {
  const notice = $("#page-notice");
  notice.hidden = false;
  notice.classList.toggle("form-error", error);
  notice.textContent = message;
  notice.scrollIntoView({ block: "nearest" });
}

function bindStaticControls() {
  $("#job-filters").addEventListener("submit", (event) => { event.preventDefault(); renderHome(); });
  $("#filter-reset").addEventListener("click", (event) => { event.preventDefault(); $("#job-filters").reset(); renderHome(); });
  $$(".static-nav-unavailable").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    showNotice(`${link.dataset.staticFeature}：Static demo / unavailable in public snapshot。`);
  }));
}

async function init() {
  bindStaticControls();
  try {
    const response = await fetch("./data/demo_jobs.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`demo_jobs.json 返回 HTTP ${response.status}`);
    const payload = await response.json();
    if (!Array.isArray(payload.jobs) || !payload.jobs.length) throw new Error("静态快照没有岗位数据");
    state.jobs = payload.jobs.sort(queryOrder);
    state.sources = payload.sources || [];
    state.collectionSummary = payload.collection_summary || null;
    [...new Set(state.jobs.filter((job) => !job.is_sample && isEffectivelyActive(job)).map((job) => job.company_name))].sort((a, b) => a.localeCompare(b, "zh-CN")).forEach((company) => $("#filter-company").insertAdjacentHTML("beforeend", `<option value="${escapeHtml(company)}">${escapeHtml(company)}</option>`));
    state.sources.forEach((source) => $("#filter-source").insertAdjacentHTML("beforeend", `<option value="${escapeHtml(source.source_id)}">${escapeHtml(source.source_name)}</option>`));
    renderCollectionSummary();
    const requested = Number(new URLSearchParams(location.search).get("job"));
    if (requested) renderDetail(state.jobs.find((job) => job.id === requested), false);
    else renderHome();
  } catch (error) {
    showNotice(`静态快照未能加载：${error instanceof Error ? error.message : String(error)}。请通过 HTTP Server 访问 site/，不要使用 file://。`, true);
    $("#daily-actions").classList.remove("static-loading");
    $("#job-groups").classList.remove("static-loading");
  }
}

window.addEventListener("popstate", () => {
  const requested = Number(new URLSearchParams(location.search).get("job"));
  if (requested) renderDetail(state.jobs.find((job) => job.id === requested), false);
  else showHome(false);
});

init();
