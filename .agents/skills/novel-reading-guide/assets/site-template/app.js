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

function tags(values = []) {
  return values.map((value) => `<span class="tag">${escapeHtml(value)}</span>`).join("");
}

function overview() {
  const arcs = model.arcs.map((arc) => `<article class="card"><h3>${escapeHtml(arc.name)}</h3><small>第 ${arc.start_chapter}–${arc.end_chapter} 章</small><p>${escapeHtml(arc.setup || arc.central_conflict || "")}</p><p class="muted">${escapeHtml(arc.central_conflict || "")}</p></article>`).join("");
  const story = model.project.story || {};
  app.innerHTML = `<h2>故事总览</h2><p>${escapeHtml(model.project.site?.spoiler_policy === "recommendation-first" ? "本网站默认先展示阅读理由；展开摘要与全文会包含剧透。" : "本网站包含剧透内容。")}</p><article class="card"><h3>前提</h3><p>${escapeHtml(story.premise || "暂无前提说明")}</p><details><summary>展开主线总结（含剧透）</summary><p>${escapeHtml(story.overall_summary || "暂无主线总结")}</p><p><strong>当前停点 / 结局：</strong>${escapeHtml(story.end_state || "暂无")}</p></details>${tags(story.key_themes)}</article><div class="grid">${arcs || '<p class="empty">尚未提供篇章数据。</p>'}</div>`;
}

function chapterCard(chapter) {
  const quick = chapter.reading_priority === "quick_read" && chapter.retain_if_quick_read?.length
    ? `<p><strong>快读保留：</strong>${escapeHtml(chapter.retain_if_quick_read.join("；"))}</p>` : "";
  const evidence = chapter.evidence_chapters?.length ? `<small>核对章节：${chapter.evidence_chapters.join("、")}</small>` : "";
  const people = (chapter.characters_involved || []).map((id) => model.personNames[id] || id).join("、");
  const events = chapter.key_events?.length ? `<p><strong>关键事件：</strong>${escapeHtml(chapter.key_events.join("；"))}</p>` : "";
  const changes = chapter.character_changes?.length ? `<p><strong>人物变化：</strong>${escapeHtml(chapter.character_changes.map((item) => item.change || "").filter(Boolean).join("；"))}</p>` : "";
  return `<article class="card ${escapeHtml(chapter.reading_priority || "quick_read")}">
    <h3>第 ${chapter.id} 章《${escapeHtml(chapter.title)}》</h3>
    <small class="chapter-meta">${escapeHtml(model.arcNames[chapter.arc_id] || "未归类")} · ${escapeHtml(chapter.reading_priority || "未标注")} · 原文第 ${chapter.source.start_line}–${chapter.source.end_line} 行</small>
    <p><strong>为什么读：</strong>${escapeHtml(chapter.priority_reason || "未提供")}</p><p><strong>涉及人物：</strong>${escapeHtml(people || "未标注")}</p>
    <p>${escapeHtml(chapter.teaser || "")}</p>
    ${tags(chapter.content_tags)}${tags(chapter.narrative_roles)}
    <details><summary>展开剧情摘要（含剧透）</summary><p>${escapeHtml(chapter.summary || "暂无摘要")}</p>${events}${changes}${quick}${evidence}</details>
    ${chapter.text_asset ? `<p><button class="load-text" data-text="${escapeHtml(chapter.text_asset)}">阅读全文</button></p><div class="text-slot"></div>` : ""}
  </article>`;
}

function chapters() {
  const contentTags = [...new Set(model.chapters.flatMap((chapter) => chapter.content_tags || []))].sort();
  const roles = [...new Set(model.chapters.flatMap((chapter) => chapter.narrative_roles || []))].sort();
  const arcOptions = model.arcs.map((arc) => `<option value="${escapeHtml(arc.id)}">${escapeHtml(arc.name)}</option>`).join("");
  app.innerHTML = `<h2>章节浏览</h2><div class="toolbar">
    <input id="search" placeholder="搜索章节标题或摘要">
    <select id="priority"><option value="">全部阅读优先级</option><option value="intensive">精读 intensive</option><option value="must_read">必读 must_read</option><option value="quick_read">快读 quick_read</option></select>
    <select id="arc"><option value="">全部篇章</option>${arcOptions}</select><select id="role"><option value="">全部叙事作用</option>${roles.map((role) => `<option value="${escapeHtml(role)}">${escapeHtml(role)}</option>`).join("")}</select>
    <select id="tag"><option value="">全部内容标签</option>${contentTags.map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`).join("")}</select>
    <select id="person"><option value="">全部人物</option>${model.characters.map((person) => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}</option>`).join("")}</select>
  </div><div id="chapter-list"></div>`;
  const render = () => {
    const query = document.querySelector("#search").value.trim().toLowerCase();
    const priority = document.querySelector("#priority").value;
    const arc = document.querySelector("#arc").value;
    const role = document.querySelector("#role").value;
    const tag = document.querySelector("#tag").value;
    const person = document.querySelector("#person").value;
    const results = model.chapters.filter((chapter) => (!query || `${chapter.title} ${chapter.teaser} ${chapter.summary}`.toLowerCase().includes(query)) && (!priority || chapter.reading_priority === priority) && (!arc || chapter.arc_id === arc) && (!role || (chapter.narrative_roles || []).includes(role)) && (!tag || (chapter.content_tags || []).includes(tag)) && (!person || (chapter.characters_involved || []).includes(person)));
    document.querySelector("#chapter-list").innerHTML = results.length ? results.map(chapterCard).join("") : '<p class="empty">没有匹配章节。</p>';
  };
  ["search", "priority", "arc", "role", "tag", "person"].forEach((id) => document.querySelector(`#${id}`).addEventListener("input", render));
  render();
}

function characters() {
  const people = model.characters.map((person) => `<article class="card"><h3>${escapeHtml(person.name)}</h3><p>${escapeHtml(person.one_sentence)}</p><small>首次出现：第 ${person.first_chapter ?? "?"} 章</small></article>`).join("");
  const relations = model.relationships.map((relation) => `<article class="card"><h3>${escapeHtml(relation.type || "关系")}</h3><p>${escapeHtml(relation.one_sentence)}</p><small>支撑章节：${(relation.supporting_chapters || []).join("、")}</small></article>`).join("");
  app.innerHTML = `<h2>人物</h2><div class="grid">${people || '<p class="empty">尚未提供人物数据。</p>'}</div><h2>关系</h2><div class="grid">${relations || '<p class="empty">尚未提供关系数据。</p>'}</div>`;
}

function show(view) {
  document.querySelectorAll(".tab").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  ({ overview, chapters, characters }[view] || overview)();
}

document.addEventListener("click", async (event) => {
  const tab = event.target.closest(".tab");
  if (tab) show(tab.dataset.view);
  const button = event.target.closest(".load-text");
  if (!button || button.disabled) return;
  button.disabled = true;
  button.textContent = "正在加载…";
  const slot = button.closest("article").querySelector(".text-slot");
  try {
    const response = await fetch(button.dataset.text);
    if (!response.ok) throw new Error("text unavailable");
    const pre = document.createElement("pre");
    pre.className = "full-text";
    pre.textContent = await response.text();
    slot.replaceChildren(pre);
    button.remove();
  } catch {
    button.textContent = "全文加载失败";
  }
});

Promise.all([request("data/manifest.json", {}), request("data/chapters.json", []), request("data/arcs.json", []), request("data/characters.json", []), request("data/relationships.json", [])]).then(([project, chaptersData, arcs, charactersData, relationships]) => {
  model = { project, chapters: chaptersData, arcs, characters: charactersData, relationships, arcNames: Object.fromEntries(arcs.map((arc) => [arc.id, arc.name])), personNames: Object.fromEntries(charactersData.map((person) => [person.id, person.name])) };
  header.innerHTML = `<h1>${escapeHtml(project.novel?.title || "小说阅读导航")}</h1><p class="subtitle">${escapeHtml(project.coverage?.is_complete_book ? "全书" : `第 ${project.coverage?.start_chapter ?? "?"}–${project.coverage?.end_chapter ?? "?"} 章`)} · 本地静态阅读导航</p>${project.analysis?.status !== "final" ? '<p class="notice">当前分析状态：暂定。请以原文为准。</p>' : ""}`;
  show("overview");
});
