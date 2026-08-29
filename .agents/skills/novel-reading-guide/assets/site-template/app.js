const app = document.querySelector("#app");
const header = document.querySelector("#header");
let model;

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[character]));

const request = (path, fallback) => fetch(path).then((response) => {
  if (!response.ok) throw new Error(path);
  return response.json();
}).catch(() => fallback);

const I18N = {
  priority: { intensive: "精读", must_read: "必读", quick_read: "快读" },
  contentTag: {
    battle: "打斗", dialogue: "对话", cultivation: "修炼", romance: "言情", comedy: "喜剧",
    mystery: "悬疑", treasure: "机缘寻宝", sect_life: "宗门日常", adventure: "历险",
    master_disciple: "师徒", love: "情感"
  },
  narrativeRole: {
    setup: "铺垫", payoff: "回收", turning_point: "转折", progression: "推进",
    character_development: "人物成长", world_building: "世界观", foreshadowing: "伏笔"
  },
  relationType: {
    enmity: "对立", allied: "同盟", romance: "恋人", master_disciple: "师徒", kinship: "亲族", rivalry: "竞争"
  }
};

function labelPriority(value) { return I18N.priority[value] || value; }
function labelContentTag(value) { return I18N.contentTag[value] || value; }
function labelNarrativeRole(value) { return I18N.narrativeRole[value] || value; }
function labelRelationType(value) { return I18N.relationType[value] || value; }

const textCache = new Map();
let lastViewedId = null;
if (location.hash && location.hash.startsWith("#chapter-")) {
  const m = location.hash.match(/#chapter-(\d+)/);
  if (m) lastViewedId = parseInt(m[1], 10);
}

function collapseAllExcept(exceptBtn) {
  document.querySelectorAll(".load-text").forEach((btn) => {
    if (btn === exceptBtn) return;
    if (btn.dataset.loaded === "true" || btn.textContent === "收起全文" || btn.textContent === "正在加载…") {
      btn.textContent = "阅读全文";
      btn.dataset.loaded = "false";
      btn.disabled = false;
      const s = btn.closest("article")?.querySelector(".text-slot");
      if (s) s.replaceChildren();
    }
  });
}

function tags(values = [], mapper) {
  return values.map((value) => `<span class="tag">${escapeHtml(mapper ? mapper(value) : value)}</span>`).join("");
}

function overview() {
  const arcs = model.arcs.map((arc) => `<article class="card arc-card" data-arc="${escapeHtml(arc.id)}" tabindex="0" role="button" aria-label="查看${escapeHtml(arc.name)}章节"><h3>${escapeHtml(arc.name)}</h3><small>第 ${arc.start_chapter}–${arc.end_chapter} 章 · 点击查看本篇章章节 →</small><p>${escapeHtml(arc.setup || arc.central_conflict || "")}</p><p class="muted">${escapeHtml(arc.central_conflict || "")}</p></article>`).join("");
  const story = model.project.story || {};
  app.innerHTML = `<h2>故事总览</h2><p>${escapeHtml(model.project.site?.spoiler_policy === "recommendation-first" ? "本网站默认先展示阅读理由；展开摘要与全文会包含剧透。" : "本网站包含剧透内容。")}</p><article class="card"><h3>前提</h3><p>${escapeHtml(story.premise || "暂无前提说明")}</p><details><summary>展开主线总结（含剧透）</summary><p>${escapeHtml(story.overall_summary || "暂无主线总结")}</p><p><strong>当前停点 / 结局：</strong>${escapeHtml(story.end_state || "暂无")}</p></details>${tags(story.key_themes || [])}</article><div class="grid">${arcs || '<p class="empty">尚未提供篇章数据。</p>'}</div>`;
}

function chapterCard(chapter) {
  const quick = chapter.reading_priority === "quick_read" && chapter.retain_if_quick_read?.length
    ? `<p><strong>快读保留：</strong>${escapeHtml(chapter.retain_if_quick_read.join("；"))}</p>` : "";
  const evidence = chapter.evidence_chapters?.length ? `<small>核对章节：${chapter.evidence_chapters.join("、")}</small>` : "";
  const people = (chapter.characters_involved || []).map((id) => model.personNames[id] || id).join("、");
  const events = chapter.key_events?.length ? `<p><strong>关键事件：</strong>${escapeHtml(chapter.key_events.join("；"))}</p>` : "";
  const changes = chapter.character_changes?.length ? `<p><strong>人物变化：</strong>${escapeHtml(chapter.character_changes.map((item) => item.change || "").filter(Boolean).join("；"))}</p>` : "";
  return `<article class="card ${escapeHtml(chapter.reading_priority || "quick_read")}" id="chapter-${chapter.id}">
    <h3>第 ${chapter.id} 章《${escapeHtml(chapter.title)}》 <a href="#chapter-${chapter.id}" class="chapter-anchor" title="复制本章链接" aria-label="定位到第 ${chapter.id} 章">#</a></h3>
    <small class="chapter-meta">${escapeHtml(model.arcNames[chapter.arc_id] || "未归类")} · ${escapeHtml(labelPriority(chapter.reading_priority) || "未标注")} · 原文第 ${chapter.source.start_line}–${chapter.source.end_line} 行</small>
    <p><strong>为什么读：</strong>${escapeHtml(chapter.priority_reason || "未提供")}</p><p><strong>涉及人物：</strong>${escapeHtml(people || "未标注")}</p>
    <p>${escapeHtml(chapter.teaser || "")}</p>
    ${tags(chapter.content_tags, labelContentTag)}${tags(chapter.narrative_roles, labelNarrativeRole)}
    <details><summary>展开剧情摘要（含剧透）</summary><p class="chapter-summary">${escapeHtml(chapter.summary || "暂无摘要")}</p>${events}${changes}${quick}${evidence}</details>
    ${chapter.text_asset ? `<p><button class="load-text" data-text="${escapeHtml(chapter.text_asset)}" data-loaded="false">阅读全文</button></p><div class="text-slot"></div>` : ""}
  </article>`;
}

function chapters(initialArc) {
  const contentTags = [...new Set(model.chapters.flatMap((chapter) => chapter.content_tags || []))].sort();
  const roles = [...new Set(model.chapters.flatMap((chapter) => chapter.narrative_roles || []))].sort();
  const arcOptions = model.arcs.map((arc) => `<option value="${escapeHtml(arc.id)}">${escapeHtml(arc.name)}</option>`).join("");
  app.innerHTML = `<h2>章节浏览</h2>
  <div class="chapters-header">
    <button id="filterToggle" class="filter-toggle">筛选 ▾</button>
    <div id="activeChips" class="active-chips"></div>
    <small id="resultCount"></small>
  </div>
  <div id="chapter-list"></div>
  <aside id="filterDrawer" class="drawer hidden" aria-label="筛选抽屉">
    <div class="drawer-header"><strong>筛选</strong><button id="closeDrawer" aria-label="关闭">✕</button></div>
    <div class="drawer-body">
      <input id="search" placeholder="搜索章节标题或摘要">
      <div class="priority-pills" id="priorityPills" role="group" aria-label="阅读优先级">
        <button type="button" class="pill active" data-value="intensive">精读</button>
        <button type="button" class="pill active" data-value="must_read">必读</button>
        <button type="button" class="pill active" data-value="quick_read">快读</button>
      </div>
      <select id="arc"><option value="">全部篇章</option>${arcOptions}</select>
      <select id="role"><option value="">全部叙事作用</option>${roles.map((role) => `<option value="${escapeHtml(role)}">${escapeHtml(labelNarrativeRole(role))}</option>`).join("")}</select>
      <select id="tag"><option value="">全部内容标签</option>${contentTags.map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(labelContentTag(tag))}</option>`).join("")}</select>
      <select id="person"><option value="">全部人物</option>${model.characters.map((person) => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}</option>`).join("")}</select>
    </div>
    <div class="drawer-footer"><small>筛选不占主区宽度</small><button id="clearFilters" class="secondary">重置筛选</button></div>
  </aside>
  <div id="drawerBackdrop" class="backdrop hidden"></div>`;
  if (initialArc) {
    const arcSelect = document.querySelector("#arc");
    if (arcSelect) arcSelect.value = initialArc;
  }
  const getSelectedPriorities = () => [...document.querySelectorAll("#priorityPills .pill.active")].map((el) => el.dataset.value);
  const updateChips = () => {
    const chips = [];
    const priorities = getSelectedPriorities();
    if (priorities.length && priorities.length < 3) chips.push(`<span class="chip">优先级:${priorities.map(labelPriority).join("、")} <button data-clear="priority">×</button></span>`);
    const arc = document.querySelector("#arc").value;
    if (arc) chips.push(`<span class="chip">${escapeHtml(model.arcNames[arc]||arc)} <button data-clear="arc">×</button></span>`);
    const role = document.querySelector("#role").value;
    if (role) chips.push(`<span class="chip">${escapeHtml(labelNarrativeRole(role))} <button data-clear="role">×</button></span>`);
    const tag = document.querySelector("#tag").value;
    if (tag) chips.push(`<span class="chip">${escapeHtml(labelContentTag(tag))} <button data-clear="tag">×</button></span>`);
    const person = document.querySelector("#person").value;
    if (person) chips.push(`<span class="chip">${escapeHtml(model.personNames[person]||person)} <button data-clear="person">×</button></span>`);
    const q = document.querySelector("#search").value.trim();
    if (q) chips.push(`<span class="chip">搜索:${escapeHtml(q)} <button data-clear="search">×</button></span>`);
    document.querySelector("#activeChips").innerHTML = chips.join("") || `<span class="muted">无筛选</span>`;
  };
  const openDrawer = () => {
    document.querySelector("#filterDrawer").classList.remove("hidden");
    requestAnimationFrame(() => document.querySelector("#filterDrawer").classList.add("open"));
    document.querySelector("#drawerBackdrop").classList.remove("hidden");
  };
  const closeDrawer = () => {
    document.querySelector("#filterDrawer").classList.remove("open");
    setTimeout(() => document.querySelector("#filterDrawer").classList.add("hidden"), 220);
    document.querySelector("#drawerBackdrop").classList.add("hidden");
  };
  const scrollToHash = () => {
    const hash = location.hash;
    if (hash && hash.startsWith("#chapter-")) {
      const el = document.querySelector(hash);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };
  const scrollToTopOrLastViewed = (results) => {
    if (lastViewedId && results.some((c) => c.id === lastViewedId)) {
      const el = document.getElementById(`chapter-${lastViewedId}`);
      if (el) { el.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    }
    if (location.hash && location.hash.startsWith("#chapter-")) {
      setTimeout(scrollToHash, 50);
      return;
    }
    const header = document.querySelector(".chapters-header");
    if (header) header.scrollIntoView({ behavior: "smooth", block: "start" });
    else window.scrollTo({ top: 0, behavior: "smooth" });
  };
  let isFirstRender = true;
  const render = () => {
    const query = document.querySelector("#search").value.trim().toLowerCase();
    const priorities = getSelectedPriorities();
    const arc = document.querySelector("#arc").value;
    const role = document.querySelector("#role").value;
    const tag = document.querySelector("#tag").value;
    const person = document.querySelector("#person").value;
    const results = model.chapters.filter((chapter) => (!query || `${chapter.title} ${chapter.teaser} ${chapter.summary}`.toLowerCase().includes(query)) && (!priorities.length || priorities.includes(chapter.reading_priority)) && (!arc || chapter.arc_id === arc) && (!role || (chapter.narrative_roles || []).includes(role)) && (!tag || (chapter.content_tags || []).includes(tag)) && (!person || (chapter.characters_involved || []).includes(person)));
    document.querySelector("#chapter-list").innerHTML = results.length ? results.map(chapterCard).join("") : '<p class="empty">没有匹配章节。</p>';
    const rc = document.querySelector("#resultCount");
    if (rc) rc.textContent = `共 ${results.length} 章`;
    updateChips();
    if (isFirstRender) {
      isFirstRender = false;
      if (location.hash) setTimeout(scrollToHash, 50);
    } else {
      setTimeout(() => scrollToTopOrLastViewed(results), 50);
    }
  };
  ["search", "arc", "role", "tag", "person"].forEach((id) => document.querySelector(`#${id}`).addEventListener("input", render));
  document.querySelectorAll("#priorityPills .pill").forEach((btn) => btn.addEventListener("click", () => {
    btn.classList.toggle("active");
    render();
  }));
  document.querySelector("#filterToggle").addEventListener("click", openDrawer);
  document.querySelector("#closeDrawer").addEventListener("click", closeDrawer);
  document.querySelector("#drawerBackdrop").addEventListener("click", closeDrawer);
  document.querySelector("#clearFilters").addEventListener("click", () => {
    document.querySelector("#search").value = "";
    document.querySelectorAll("#priorityPills .pill").forEach((el) => el.classList.add("active"));
    document.querySelector("#arc").value = "";
    document.querySelector("#role").value = "";
    document.querySelector("#tag").value = "";
    document.querySelector("#person").value = "";
    render();
    history.replaceState(null, "", location.pathname + location.search);
  });
  document.querySelector("#activeChips").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-clear]");
    if (!btn) return;
    const key = btn.dataset.clear;
    if (key === "priority") document.querySelectorAll("#priorityPills .pill").forEach((el) => el.classList.add("active"));
    else if (key === "search") document.querySelector("#search").value = "";
    else document.querySelector(`#${key}`).value = "";
    render();
  });
  document.querySelector("#chapter-list").addEventListener("click", (e) => {
    const a = e.target.closest(".chapter-anchor");
    if (a) {
      const href = a.getAttribute("href");
      if (href) {
        history.replaceState(null, "", href);
        const m = href.match(/#chapter-(\d+)/);
        if (m) lastViewedId = parseInt(m[1], 10);
      }
    }
  });
  window.addEventListener("hashchange", (e) => {
    const m = location.hash.match(/#chapter-(\d+)/);
    if (m) lastViewedId = parseInt(m[1], 10);
    scrollToHash();
  });
  render();
}

function characters() {
  const people = model.characters.map((person) => `<article class="card"><h3>${escapeHtml(person.name)}</h3><p>${escapeHtml(person.one_sentence)}</p><small>首次出现：第 ${person.first_chapter ?? "?"} 章</small></article>`).join("");
  const relations = model.relationships.map((relation) => `<article class="card"><h3>${escapeHtml(labelRelationType(relation.type) || relation.type || "关系")}</h3><p>${escapeHtml(relation.one_sentence)}</p><small>支撑章节：${(relation.supporting_chapters || []).join("、")}</small></article>`).join("");
  app.innerHTML = `<h2>人物</h2><div class="grid">${people || '<p class="empty">尚未提供人物数据。</p>'}</div><h2>关系</h2><div class="grid">${relations || '<p class="empty">尚未提供关系数据。</p>'}</div>`;
}

function show(view, param) {
  document.querySelectorAll(".tab").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (view === "chapters") { chapters(param); return; }
  ({ overview, chapters, characters }[view] || overview)();
}

document.addEventListener("click", async (event) => {
  const arcCard = event.target.closest(".arc-card");
  if (arcCard) {
    const arcId = arcCard.dataset.arc;
    show("chapters", arcId);
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const tab = event.target.closest(".tab");
  if (tab) show(tab.dataset.view);
  const button = event.target.closest(".load-text");
  if (!button) return;
  const article = button.closest("article");
  if (article && article.id && article.id.startsWith("chapter-")) {
    const m = article.id.match(/chapter-(\d+)/);
    if (m) {
      lastViewedId = parseInt(m[1], 10);
      history.replaceState(null, "", `#chapter-${lastViewedId}`);
    }
  }
  const slot = article.querySelector(".text-slot");
  const isExpanded = button.dataset.loaded === "true";
  // 点击已展开的则收起
  if (isExpanded) {
    slot.replaceChildren();
    button.textContent = "阅读全文";
    button.dataset.loaded = "false";
    return;
  }
  // 单开：先收起其他所有（包括正在加载中的）
  collapseAllExcept(button);
  const url = button.dataset.text;
  // 若已缓存，直接展开
  if (textCache.has(url)) {
    const pre = document.createElement("pre");
    pre.className = "full-text";
    pre.textContent = textCache.get(url);
    slot.replaceChildren(pre);
    button.textContent = "收起全文";
    button.dataset.loaded = "true";
    return;
  }
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = "正在加载…";
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("text unavailable");
    const text = await response.text();
    textCache.set(url, text);
    // 实现单开：加载完成后再次确保其他已收起（处理竞态）
    collapseAllExcept(button);
    const pre = document.createElement("pre");
    pre.className = "full-text";
    pre.textContent = text;
    slot.replaceChildren(pre);
    button.textContent = "收起全文";
    button.dataset.loaded = "true";
  } catch {
    button.textContent = "全文加载失败";
    button.dataset.loaded = "false";
  } finally {
    button.disabled = false;
  }
});

Promise.all([request("data/manifest.json", {}), request("data/chapters.json", []), request("data/arcs.json", []), request("data/characters.json", []), request("data/relationships.json", [])]).then(([project, chaptersData, arcs, charactersData, relationships]) => {
  model = { project, chapters: chaptersData, arcs, characters: charactersData, relationships, arcNames: Object.fromEntries(arcs.map((arc) => [arc.id, arc.name])), personNames: Object.fromEntries(charactersData.map((person) => [person.id, person.name])) };
  header.innerHTML = `<h1>${escapeHtml(project.novel?.title || "小说阅读导航")}</h1><p class="subtitle">${escapeHtml(project.coverage?.is_complete_book ? "全书" : `第 ${project.coverage?.start_chapter ?? "?"}–${project.coverage?.end_chapter ?? "?"} 章`)} · 本地静态阅读导航</p>${project.analysis?.status !== "final" ? '<p class="notice">当前分析状态：暂定。请以原文为准。</p>' : ""}`;
  show("overview");
});
