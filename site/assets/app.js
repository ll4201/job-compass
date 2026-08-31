"use strict";

const STRATEGY = {
  priority_apply: { label: "优先投递", order: 0 },
  targeted_apply: { label: "定制后投递", order: 1 },
  low_cost_try: { label: "低成本尝试", order: 2 },
  hold: { label: "补充信息后决定", order: 3 },
  skip: { label: "归档 / 跳过", order: 4 },
};

const ACTION_CLASS = {
  apply_now: "apply_now",
  tailor_then_apply: "tailor_then_apply",
  low_cost_apply: "low_cost_apply",
  clarify_then_decide: "clarify_then_decide",
  archive: "archive",
};

const state = {
  jobs: [],
  filters: { search: "", company: "", location: "", strategy: "", score: 0, sort: "priority", inactive: false },
};

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

function text(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : escapeHtml(value);
}

function score(value) {
  return Number.isFinite(Number(value)) ? Math.round(Number(value)) : "—";
}

function dateText(value) {
  if (!value) return "未公开";
  const parsed = new Date(String(value).replace(" ", "T") + (String(value).includes("Z") ? "" : "Z"));
  if (Number.isNaN(parsed.getTime())) return escapeHtml(String(value).slice(0, 10));
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Shanghai" }).format(parsed);
}

function unique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
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
  const overrides = getLocal("candidate-status", {});
  return overrides[job.id] || job.candidate_status || "new";
}

function populateSelect(id, values) {
  const select = $(id);
  values.forEach((value) => select.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`));
}

function renderStats() {
  const counts = Object.fromEntries(Object.keys(STRATEGY).map((key) => [key, 0]));
  state.jobs.forEach((job) => { counts[job.effective_strategy] = (counts[job.effective_strategy] || 0) + 1; });
  $("#hero-job-count").textContent = state.jobs.length;
  $("#note-job-count").textContent = state.jobs.length;
  $("#stat-jobs").textContent = state.jobs.length;
  $("#stat-priority").textContent = counts.priority_apply;
  $("#stat-targeted").textContent = counts.targeted_apply;
  $("#stat-hold").textContent = counts.hold;
  $("#stat-skip").textContent = counts.skip;
}

function actionItem(job, compact = false) {
  const details = compact ? "" : `<ol>${job.action.next_steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>`;
  return `<section class="action-item">
    <h3><a class="job-detail-link" href="?job=${job.id}" data-job-id="${job.id}">${escapeHtml(job.job_title)}</a></h3>
    <p>${escapeHtml(job.company_name)} · ${text(job.location_raw || job.normalized_location, "地点待确认")}</p>
    <div class="action-tags"><span>${escapeHtml(job.action.priority)}</span><span>${text(job.action.resume_track, "按岗位方向定制")}</span></div>
    ${details}
  </section>`;
}

function renderDashboard() {
  const active = state.jobs.filter((job) => job.is_active && job.availability_status === "active");
  const lanes = [
    { action: "apply_now", letter: "A", title: "立即投递", cls: "action-now", empty: "今天没有必须立即投递的岗位。", compact: false },
    { action: "tailor_then_apply", letter: "B", title: "本周准备", cls: "action-week", empty: "暂无需要定制后投递的岗位。", compact: true },
    { action: "low_cost_apply", letter: "C", title: "快速验证", cls: "action-quick", empty: "暂无低成本验证岗位。", compact: true },
  ];
  const html = lanes.map((lane) => {
    const jobs = active.filter((job) => job.action.type === lane.action);
    return `<article class="action-lane ${lane.cls}">
      <div class="action-lane-head"><div><span>${lane.letter}</span><h3>${lane.title}</h3></div><b>${jobs.length}</b></div>
      <div class="action-items">${jobs.length ? jobs.map((job) => actionItem(job, lane.compact)).join("") : `<p class="action-empty">${lane.empty}</p>`}</div>
    </article>`;
  }).join("");
  const holds = active.filter((job) => job.action.type === "clarify_then_decide");
  $("#daily-actions").innerHTML = `${html}<a class="action-lane action-hold filter-hold" href="#job-pool"><span>D · 待确认岗位</span><strong>${holds.length} 个岗位等待确认</strong><small>查看岗位并逐项核实关键信息 →</small></a>`;
  bindDetailLinks();
  $(".filter-hold")?.addEventListener("click", () => {
    $("#filter-strategy").value = "hold";
    state.filters.strategy = "hold";
    renderJobs();
  });
}

function filteredJobs() {
  const query = state.filters.search.trim().toLocaleLowerCase("zh-CN");
  const jobs = state.jobs.filter((job) => {
    if (!state.filters.inactive && (!job.is_active || job.availability_status !== "active")) return false;
    if (query && ![job.company_name, job.job_title, job.role_direction, job.description].join(" ").toLocaleLowerCase("zh-CN").includes(query)) return false;
    if (state.filters.company && job.company_name !== state.filters.company) return false;
    if (state.filters.location && (job.normalized_location || job.location_raw) !== state.filters.location) return false;
    if (state.filters.strategy && job.effective_strategy !== state.filters.strategy) return false;
    if (Number(job.assessment.fit_score || 0) < state.filters.score) return false;
    return true;
  });
  const sorters = {
    priority: (a, b) => STRATEGY[a.effective_strategy].order - STRATEGY[b.effective_strategy].order || Number(b.assessment.fit_score) - Number(a.assessment.fit_score),
    "fit-desc": (a, b) => Number(b.assessment.fit_score) - Number(a.assessment.fit_score),
    "opportunity-desc": (a, b) => Number(b.assessment.opportunity_score) - Number(a.assessment.opportunity_score),
    newest: (a, b) => new Date(b.published_at) - new Date(a.published_at),
  };
  return jobs.sort(sorters[state.filters.sort]);
}

function jobCard(job) {
  const assessment = job.assessment;
  const actionClass = ACTION_CLASS[job.action.type] || "archive";
  const inactive = !job.is_active || job.availability_status !== "active";
  return `<article class="job-card ${job.is_new ? "new-job" : ""} ${inactive ? "inactive-card" : ""}">
    <div class="score grade-${escapeHtml(assessment.grade)}"><b>${score(assessment.fit_score)}</b><span>适配度</span></div>
    <div class="job-main">
      <div class="meta">
        ${job.is_new ? '<span class="new-tag">NEW</span>' : ""}
        ${inactive ? '<span class="inactive-badge">HISTORICAL</span>' : ""}
        <span class="action-tag action-tag-${actionClass}">${escapeHtml(job.action.label)}</span>
        <span>${text(job.role_direction)}</span><span>${job.job_type === "internship" ? "实习" : "正式"}</span><span>${text(assessment.risk_level, "风险待评估")}</span>
      </div>
      <h2><a class="job-link job-detail-link" href="?job=${job.id}" data-job-id="${job.id}">${escapeHtml(job.job_title)}</a></h2>
      <p class="company">${escapeHtml(job.company_name)} · ${text(job.location_raw)}</p>
      <div class="mini-metrics"><span>机会 ${score(assessment.opportunity_score)}</span><span>完整度 ${score(assessment.information_completeness)}</span><strong>${escapeHtml(STRATEGY[job.effective_strategy].label)}</strong><span>V3 ${text(assessment.application_recommendation)}</span></div>
      <p>${text(assessment.decision_reason || assessment.recommendation)}</p>
    </div>
    <div class="facts"><span>${text(job.salary_raw, "薪资未公开")}</span><span>${dateText(job.published_at)} 发布</span><span class="candidate-chip">Candidate: ${escapeHtml(candidateStatus(job))}</span></div>
  </article>`;
}

function renderJobs() {
  const jobs = filteredJobs();
  $("#result-count").textContent = `显示 ${jobs.length} / ${state.jobs.length} 个岗位`;
  if (!jobs.length) {
    $("#job-groups").innerHTML = '<div class="empty"><h3>暂无匹配结果</h3><p>尝试降低分数或清除部分筛选条件。</p></div>';
    return;
  }
  const groups = {};
  jobs.forEach((job) => (groups[job.effective_strategy] ||= []).push(job));
  $("#job-groups").innerHTML = Object.keys(STRATEGY).map((key) => {
    if (!groups[key]?.length) return "";
    return `<section class="strategy-group"><h3>${STRATEGY[key].label} <small>${groups[key].length}</small></h3><section class="jobs">${groups[key].map(jobCard).join("")}</section></section>`;
  }).join("");
  bindDetailLinks();
}

function renderList(items, empty = "暂无") {
  return items?.length ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p>${empty}</p>`;
}

function infoStateLabel(value) {
  return ({ confirmed: "已确认", not_disclosed: "未披露", conflict: "存在冲突", unknown: "未知" })[value] || value;
}

function renderDetail(job, push = true) {
  if (!job) {
    showError("未找到该岗位。请返回岗位列表选择一个有效岗位。");
    return;
  }
  if (push) {
    const url = new URL(window.location.href);
    url.searchParams.set("job", job.id);
    url.hash = "";
    history.pushState({ jobId: job.id }, "", url);
  }
  document.title = `${job.job_title} · Job Compass`;
  $("#list-view").hidden = true;
  const detail = $("#detail-view");
  detail.hidden = false;
  const a = job.assessment;
  const explanation = a.explanation_json || {};
  const dimensions = explanation.dimensions || [];
  const infoStates = explanation.information_states || {};
  const opportunity = explanation.opportunity_breakdown || a.opportunity_breakdown_json || {};
  const feedback = getLocal(`feedback:${job.id}`, { applied: "", reason: "", result: "", notes: "" });
  const review = getLocal(`review:${job.id}`, { grade: "", score: "", decision: "", calibration: "", comment: "" });
  const workflowStatuses = ["new", "saved", "preparing", "applied", "interviewing", "offer", "closed"];
  const currentStatus = candidateStatus(job);
  const historical = !job.is_active || job.availability_status !== "active";

  detail.innerHTML = `
    <a class="detail-back" href="./#job-pool" id="detail-back">← 返回岗位列表</a>
    <section class="detail-head"><div><p class="eyebrow">${escapeHtml(job.company_name)} · ${text(job.location_raw)}</p><h1>${escapeHtml(job.job_title)}</h1><div class="meta"><span>${text(job.role_direction)}</span><span>${job.job_type === "internship" ? "实习" : "正式"}</span><span>Candidate: ${escapeHtml(currentStatus)}</span><span>${text(job.travel_level)}</span></div></div><div class="big-score grade-${escapeHtml(a.grade)}"><b>${score(a.total_score)}</b><span>系统 ${escapeHtml(a.grade)} 档</span></div></section>
    <p class="demo-safe-note">这是原 Demo 中已有的完全虚构展示岗位。以下评分、推荐理由和证据均来自部署时的静态快照；本页不会调用 API。</p>
    ${historical ? `<div class="notice"><strong>历史岗位：</strong>${text(job.closure_reason, job.availability_status)}。当前有效岗位门禁已阻止它进入行动中心。</div>` : ""}

    <section class="detail-section"><h2>决策概览</h2><div class="metric-grid">
      <div><span>岗位适配度</span><b>${score(a.fit_score)}</b><small>${text(a.career_match_level)}</small></div>
      <div><span>机会价值</span><b>${score(a.opportunity_score)}</b><small>${text(a.career_value_level)}</small></div>
      <div><span>信息完整度</span><b>${score(a.information_completeness)}</b><small>缺失信息只在这里体现</small></div>
      <div><span>当前有效策略</span><b>${escapeHtml(STRATEGY[job.effective_strategy].label)}</b><small>${escapeHtml(job.action.label)}</small></div>
    </div><div class="detail-card"><p><strong>推荐理由：</strong>${text(a.decision_reason || a.recommendation)}</p><p><strong>推荐简历：</strong>${text(job.action.resume_track)}</p></div></section>

    <section class="detail-section"><h2>多维判断</h2><div class="metric-grid">
      <div><span>Career Match</span><b>${score(a.career_match_score)}</b><small>${text(a.career_match_level)}</small></div>
      <div><span>Career Value</span><b>${score(a.career_value_score)}</b><small>${text(a.career_value_level)}</small></div>
      <div><span>Employer Acceptance</span><b>${score(a.employer_acceptance_score)}</b><small>${text(a.employer_acceptance_level)}</small></div>
      <div><span>Personal Preference</span><b>${score(a.personal_preference_score)}</b><small>${text(a.personal_preference_level)}</small></div>
    </div></section>

    <section class="detail-section detail-columns">
      <article class="detail-card"><h2>判断摘要</h2><h3>主要优势</h3>${renderList(a.strengths)}<h3>风险</h3>${renderList(a.risks, "暂未识别到明确重大风险")}<h3>缺失信息</h3>${renderList(a.missing_information, "核心信息较完整")}<h3>建议确认</h3>${renderList(a.interview_questions, "暂无额外确认问题")}</article>
      <aside class="detail-card"><h2>岗位信息</h2><dl><dt>地点</dt><dd>${text(job.normalized_location || job.location_raw)}</dd><dt>薪资</dt><dd>${text(job.salary_raw, "未公开")}</dd><dt>经验</dt><dd>${text(job.experience_raw, "未公开")}</dd><dt>学历</dt><dd>${text(job.education_requirement, "未公开")}</dd><dt>双休</dt><dd>${text(job.working_schedule)}</dd><dt>五险一金</dt><dd>${text(job.five_insurances_housing_fund)}</dd><dt>风险</dt><dd>${text(a.risk_level)}</dd></dl></aside>
    </section>

    <section class="detail-section"><h2>信息状态</h2><div class="state-grid-static">${Object.entries(infoStates).map(([key, value]) => `<div><span>${escapeHtml(key)}</span><b>${escapeHtml(infoStateLabel(value))}</b></div>`).join("") || "<p>暂无信息状态记录。</p>"}</div><p>未公开信息只降低信息完整度，不直接降低适配度或机会价值。</p></section>

    <section class="detail-section"><h2>机会价值构成</h2><div class="opportunity-grid">${Object.values(opportunity).map((item) => `<article><h3>${text(item.label)}</h3><b>${score(item.score)} / ${score(item.max_score)}</b><p>加分证据：${item.positive_evidence?.length ? item.positive_evidence.map(escapeHtml).join("、") : "未明确披露"}</p><p>风险证据：${item.negative_evidence?.length ? item.negative_evidence.map(escapeHtml).join("、") : "未发现明确负面"}</p></article>`).join("") || "<p>暂无构成记录。</p>"}</div></section>

    <section class="detail-section dimension-list"><h2>评分如何产生</h2>${dimensions.map((dimension) => `<article class="dimension dimension-static"><header><h3>${escapeHtml(dimension.name)}</h3><strong>${score(dimension.score)} / ${score(dimension.max_score)}</strong></header><progress value="${Number(dimension.score) || 0}" max="${Number(dimension.max_score) || 1}"></progress>${dimension.items?.length ? `<ul>${dimension.items.map((item) => `<li class="${Number(item.points) < 0 ? "negative" : ""}"><b>${Number(item.points) >= 0 ? "+" : ""}${score(item.points)}</b> ${text(item.label)}${item.quote ? `<blockquote>JD 引用：${escapeHtml(item.quote)}</blockquote>` : ""}</li>`).join("")}</ul>` : "<p>未命中明确关键词，使用基础判断。</p>"}</article>`).join("") || "<p>暂无维度解释。</p>"}</section>

    <section class="detail-section detail-columns"><article class="detail-card"><h2>岗位摘要</h2><p>${text(job.description)}</p><h3>主要职责</h3><p>${text(job.responsibilities)}</p><h3>任职要求</h3><p>${text(job.requirements)}</p></article><aside class="detail-card"><h2>福利与节奏</h2><p>${text(job.benefits_raw, "未公开")}</p><dl><dt>带薪年假</dt><dd>${text(job.paid_leave)}</dd><dt>法定假日</dt><dd>${text(job.statutory_holiday_status)}</dd><dt>加班风险</dt><dd>${text(job.overtime_risk)}</dd><dt>实习转正</dt><dd>${text(job.internship_conversion)}</dd></dl></aside></section>

    <section class="detail-section detail-columns" id="human-loop"><article class="detail-card"><h2>Candidate Status</h2><p>状态只保存在此浏览器的 localStorage，不会发送到服务器。</p><div class="detail-toolbar"><label>当前状态 <select id="candidate-status">${workflowStatuses.map((value) => `<option value="${value}" ${value === currentStatus ? "selected" : ""}>${value}</option>`).join("")}</select></label></div><p class="save-note" id="candidate-save-note"></p></article>
      <article class="detail-card"><h2>Feedback</h2><p>仅用于本机体验，请勿输入姓名、邮箱、电话或其他个人信息。</p><form class="detail-form" id="feedback-form"><label>是否投递<select name="applied"><option value="">未记录</option><option value="yes" ${feedback.applied === "yes" ? "selected" : ""}>是</option><option value="no" ${feedback.applied === "no" ? "selected" : ""}>否</option></select></label><label>未投原因<input name="reason" maxlength="80" value="${escapeHtml(feedback.reason)}"></label><label>面试结果<input name="result" maxlength="80" value="${escapeHtml(feedback.result)}"></label><label>备注<textarea name="notes" maxlength="500" rows="3">${escapeHtml(feedback.notes)}</textarea></label><button type="submit">保存到本机</button><p class="save-note" id="feedback-save-note"></p></form></article>
    </section>

    <section class="detail-section detail-card"><h2>人工评价</h2><p>人工评价用于展示 Human-in-the-loop 校准流程，不覆盖静态系统评分。</p><form class="detail-form" id="review-form"><div class="review-grid"><label>我认为的档位<select name="grade"><option value="">未选择</option>${["A", "B", "C", "D"].map((value) => `<option value="${value}" ${review.grade === value ? "selected" : ""}>${value} 档</option>`).join("")}</select></label><label>人工分数<input type="number" name="score" min="0" max="100" step="0.5" value="${escapeHtml(review.score)}"></label><label>是否愿意投递<select name="decision"><option value="">未选择</option><option value="priority_apply" ${review.decision === "priority_apply" ? "selected" : ""}>优先投递</option><option value="apply" ${review.decision === "apply" ? "selected" : ""}>愿意投递</option><option value="maybe" ${review.decision === "maybe" ? "selected" : ""}>可以考虑</option><option value="do_not_apply" ${review.decision === "do_not_apply" ? "selected" : ""}>不投递</option></select></label><label>系统判断偏差<select name="calibration"><option value="">未选择</option><option value="aligned" ${review.calibration === "aligned" ? "selected" : ""}>基本一致</option><option value="overestimated" ${review.calibration === "overestimated" ? "selected" : ""}>系统高估</option><option value="underestimated" ${review.calibration === "underestimated" ? "selected" : ""}>系统低估</option></select></label><label class="wide">评论<textarea name="comment" maxlength="500" rows="3">${escapeHtml(review.comment)}</textarea></label></div><button type="submit">保存到本机</button><p class="save-note" id="review-save-note"></p></form></section>

    <section class="detail-section history"><h2>评分历史</h2><div class="history-wrap"><table><thead><tr><th>时间</th><th>版本</th><th>旧总分</th><th>适配</th><th>机会</th><th>完整度</th><th>风险</th><th>最终策略</th><th>评级</th></tr></thead><tbody>${job.assessment_history.length ? job.assessment_history.map((item) => `<tr><td>${dateText(item.assessed_at)}</td><td>${text(item.assessment_version)}</td><td>${score(item.total_score)}</td><td>${score(item.fit_score)}</td><td>${score(item.opportunity_score)}</td><td>${score(item.information_completeness)}</td><td>${text(item.risk_level)}</td><td>${text(item.final_strategy)}</td><td>${text(item.grade)}</td></tr>`).join("") : '<tr><td colspan="9">尚无重新评分历史。</td></tr>'}</tbody></table></div></section>

    <section class="detail-section evidence-section"><div class="section-heading"><div><h2>外部证据</h2><p>辅助证据不替代原始 JD 与基础评分。</p></div></div><div class="evidence-list">${job.evidence.length ? job.evidence.map((item) => `<article><header><div><b>${text(item.evidence_category)}</b> <span>${text(item.source_platform)}</span> <span>${text(item.verification_status)}</span></div><small>${dateText(item.published_at)} · ${text(item.city, "城市未公开")} · 相关度 ${text(item.relevance_level)}</small></header><h3>${text(item.source_title, "未命名证据")}</h3><p>${text(item.evidence_value || item.evidence_text)}</p></article>`).join("") : '<p class="empty-state">尚未录入外部证据。搜不到员工分享不会降低岗位评分。</p>'}</div></section>
  `;
  bindDetailInteractions(job);
  window.scrollTo({ top: 0, behavior: "instant" });
}

function bindDetailInteractions(job) {
  $("#detail-back").addEventListener("click", (event) => {
    event.preventDefault();
    showList(true);
  });
  $("#candidate-status").addEventListener("change", (event) => {
    const all = getLocal("candidate-status", {});
    all[job.id] = event.target.value;
    const saved = setLocal("candidate-status", all);
    $("#candidate-save-note").textContent = saved ? "已保存到当前浏览器。" : "浏览器禁止本地存储，状态未保存。";
  });
  $("#feedback-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    $("#feedback-save-note").textContent = setLocal(`feedback:${job.id}`, data) ? "已保存到当前浏览器。" : "浏览器禁止本地存储，反馈未保存。";
  });
  $("#review-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    $("#review-save-note").textContent = setLocal(`review:${job.id}`, data) ? "已保存到当前浏览器。" : "浏览器禁止本地存储，评价未保存。";
  });
}

function showList(push = false) {
  if (push) {
    const url = new URL(window.location.href);
    url.searchParams.delete("job");
    url.hash = "job-pool";
    history.pushState({}, "", url);
  }
  document.title = "Job Compass · Portfolio Demo";
  $("#detail-view").hidden = true;
  $("#list-view").hidden = false;
  renderJobs();
  if (push) requestAnimationFrame(() => $("#job-pool").scrollIntoView());
}

function bindDetailLinks() {
  $$(".job-detail-link").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    renderDetail(state.jobs.find((job) => job.id === Number(link.dataset.jobId)));
  }));
}

function bindFilters() {
  const form = $("#job-filters");
  const update = () => {
    state.filters = {
      search: $("#filter-search").value,
      company: $("#filter-company").value,
      location: $("#filter-location").value,
      strategy: $("#filter-strategy").value,
      score: Number($("#filter-score").value),
      sort: $("#filter-sort").value,
      inactive: $("#filter-inactive").checked,
    };
    renderJobs();
  };
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  form.addEventListener("reset", () => setTimeout(update));
}

function showError(message) {
  $("#list-view").hidden = true;
  $("#detail-view").hidden = true;
  const error = $("#load-error");
  error.hidden = false;
  error.innerHTML = `<h2>静态快照未能加载</h2><p>${escapeHtml(message)}</p><p>请通过 HTTP 服务器访问 <code>site/</code>，不要使用 <code>file://</code> 双击页面。</p>`;
}

async function init() {
  try {
    const response = await fetch("./data/demo_jobs.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`demo_jobs.json 返回 HTTP ${response.status}`);
    const payload = await response.json();
    if (!Array.isArray(payload.jobs) || !payload.jobs.length) throw new Error("静态快照中没有岗位数据");
    state.jobs = payload.jobs;
    populateSelect("#filter-company", unique(state.jobs.map((job) => job.company_name)));
    populateSelect("#filter-location", unique(state.jobs.map((job) => job.normalized_location || job.location_raw)));
    renderStats();
    renderDashboard();
    bindFilters();
    const requestedId = Number(new URLSearchParams(window.location.search).get("job"));
    if (requestedId) renderDetail(state.jobs.find((job) => job.id === requestedId), false);
    else renderJobs();
  } catch (error) {
    showError(error instanceof Error ? error.message : String(error));
  }
}

$("#reset-local-data").addEventListener("click", () => {
  if (!window.confirm("确认清除本浏览器中保存的 Candidate Status、Feedback 和人工评价？")) return;
  try {
    Object.keys(localStorage).filter((key) => key.startsWith("job-compass-static:")).forEach((key) => localStorage.removeItem(key));
  } catch (_) { /* storage may be disabled */ }
  if (!$("#detail-view").hidden) {
    const id = Number(new URLSearchParams(window.location.search).get("job"));
    renderDetail(state.jobs.find((job) => job.id === id), false);
  } else {
    renderJobs();
  }
});

window.addEventListener("popstate", () => {
  const id = Number(new URLSearchParams(window.location.search).get("job"));
  if (id) renderDetail(state.jobs.find((job) => job.id === id), false);
  else showList(false);
});

init();
