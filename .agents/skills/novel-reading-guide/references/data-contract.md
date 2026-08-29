# 长篇小说阅读导航的数据契约

JSON 或 JSONL 是规范的中间数据格式。CSV 适合导出简单的“章节 → 行号”索引，但不适合保存多标签、人物关系和跨章节链接。

## 项目级元信息：`guide-project.json`

每部小说都应有一个项目级元信息文件。它是索引器、AI 批处理器和建站器之间唯一稳定的交接点；不要把小说标题、章节范围、文件路径或网站偏好硬编码进脚本。

```json
{
  "schema_version": "1.0",
  "novel": {
    "id": "stable-slug",
    "title": "小说标题",
    "author": null,
    "language": "zh-CN"
  },
  "source": {
    "path": "原文件路径",
    "sha256": "...",
    "encoding": "gb18030",
    "line_count": 403438,
    "chapter_parser": "chinese-chapter-v1"
  },
  "coverage": {
    "start_chapter": 1,
    "end_chapter": 2468,
    "is_complete_book": true
  },
  "analysis": {
    "status": "provisional",
    "batch_size": 100,
    "overlap_chapters": 2
  },
  "story": {
    "spoiler_level": "full",
    "premise": "全书前提。",
    "overall_summary": "覆盖当前范围的主线与阶段结果。",
    "end_state": "全书完成时写结局；部分处理时写当前停点。",
    "key_themes": ["主题一"]
  },
  "data": { "directory": "data", "index_file": "章节定位索引.jsonl" },
  "taxonomy": {
    "content_tags": ["battle", "dialogue", "romance"],
    "narrative_roles": ["setup", "payoff", "turning_point"]
  },
  "site": {
    "locale": "zh-CN",
    "full_text_mode": "per-chapter-assets",
    "spoiler_policy": "recommendation-first"
  }
}
```

- 相对路径均相对于 `guide-project.json` 所在目录解析。
- `analysis.status` 可取 `not_started`、`provisional` 或 `final`。`not_started` 表示只有索引、尚无可浏览的语义分析；`provisional` 表示完成了实际阅读但尚待整合复核；只有整合与抽查完成后才设为 `final`。网站不得为 `not_started` 项目构建章节阅读页。
- `full_text_mode: "per-chapter-assets"` 表示建站器依据章节行号，从本地源文件抽取每章原文至静态网站。建站器不访问网络。
- `story` 是协调者基于全书粗扫与已整合章节记录写出的结果；它不是一次塞入全文后的即兴总结。部分处理时明确写“当前覆盖范围”，全书完成后才写完整结局。
- `data.directory` 包含 `chapters.json`、`arcs.json`、`characters.json`、`relationships.json`；`index_file` 是索引器生成的 JSONL，用于逐章核验行号。

## 章节记录

```json
{
  "id": 101,
  "title": "章节标题",
  "source": { "start_line": 19535, "end_line": 19700 },
  "arc_id": "secret-realm",
  "reading_priority": "must_read",
  "priority_reason": "引入下一场冲突的关键决定。",
  "content_tags": ["battle", "dialogue"],
  "narrative_roles": ["turning_point", "setup"],
  "teaser": "无剧透的阅读引导。",
  "summary": "简洁、允许剧透的本章转述。",
  "key_events": ["事件一", "事件二"],
  "characters_involved": ["hero", "rival"],
  "character_changes": [
    { "character_id": "hero", "change": "作出关键承诺。" }
  ],
  "relationships_changed": ["hero-rival"],
  "foreshadowing": ["mystery-key"],
  "payoffs": [],
  "retain_if_quick_read": ["之后必须记住的最低限度事实。"],
  "evidence_chapters": [99, 100, 101],
  "continuity_in": [100],
  "continuity_out": [102],
  "analysis_status": "final"
}
```

`reading_priority` 只允许使用 `intensive`、`must_read`、`quick_read`。不能把“打斗”“言情”等内容类型放进该字段。`characters_involved` 使用人物稳定 ID，供网站按人物筛选；`evidence_chapters` 记录得出本章判断时实际核对过的相邻/支撑章节；它不是叙事链接。

## 篇章记录

```json
{
  "id": "secret-realm",
  "name": "秘境篇",
  "start_chapter": 95,
  "end_chapter": 140,
  "setup": "该篇章承接了什么。",
  "central_conflict": "这一篇章的核心风险或变化。",
  "turning_points": [101, 118],
  "outcome": "对全书主线造成的结果。"
}
```

## 人物与关系记录

```json
{
  "id": "hero",
  "name": "人物名",
  "one_sentence": "角色、核心欲望/冲突和有意义的状态。",
  "first_chapter": 1,
  "last_confirmed_chapter": 2468,
  "aliases": [],
  "spoiler_level": "full"
}
```

```json
{
  "id": "hero-rival",
  "from": "hero",
  "to": "rival",
  "type": "enmity",
  "one_sentence": "双方为何相连或对立，以及这件事为何重要。",
  "supporting_chapters": [7, 51],
  "status": "resolved"
}
```

字段名保留英文稳定 ID，展示给读者时使用中文文案。这样别名修正、译名调整或程序迭代不会破坏关联。

## 静态网站目录

```text
site/
  index.html
  styles.css
  app.js
  data/
    manifest.json
    arcs.json
    characters.json
    relationships.json
    chapters.json          # 仅包含摘要与筛选所需数据
    text/
      0001.txt             # 按需加载的本章原文
      0002.txt
```

`chapters.json` 必须足够轻量，供浏览器快速筛选。建站器会在不改写源数据的前提下，为每条章节记录追加 `text_asset`，并把完整原文放入逐章文件；只有读者点击“阅读全文”时才加载。如果网站目标是“双击打开”，实现不得依赖会被 `file://` 禁止的 `fetch`；否则需提供明确的本地静态服务器启动方法。

## 建站器边界

`scripts/build_reading_site.py` 的输入为 `guide-project.json` 与规范数据目录，输出为独立 `site/` 目录。它负责校验、复制数据、从本地原文抽取章节全文、写入固定前端模板；它不得根据章节标题推断剧情，也不得创建、修饰或重写摘要、标签、阅读优先级、人物或关系。

示例：

```powershell
uv run --no-project python ./novel-reading-guide/scripts/build_reading_site.py `
  --project ./guide-project.json --output ./site
```

## 批次文件：`data/batches/batch-001.json`

批次工作者直接写入一个 JSON 文件，包含自身负责范围的章节记录，不得写入重叠章节的正式记录。协调者使用 `scripts/merge_batches.py` 合并。

```json
{
  "schema_version": "1.0",
  "batch_id": "batch-001",
  "status": "ready_for_integration",
  "source_sha256": "与 guide-project.json 一致",
  "owned_range": [1, 100],
  "read_range": [1, 102],
  "skeleton_version": "粗扫骨架的版本标识",
  "chapters": ["此批拥有的章节记录"],
  "uncertainties": ["需协调者确认的问题"]
}
```

合并器拒绝缺章、重章、超出 `owned_range` 的记录、与索引不一致的行号及哈希不一致的批次。它只合并章节记录，不生成任何剧情内容。

## 批次交接包

向被委派的工作者提供：

```json
{
  "owned_range": [101, 200],
  "read_range": [99, 202],
  "skeleton_version": "2026-08-29T00:00:00Z",
  "known_arcs": ["..."],
  "known_characters": ["..."],
  "preceding_records": [99, 100],
  "required_output": "仅输出 owned_range 的章节记录"
}
```

工作者将不确定点和对既有结论的修正建议单独报告，不直接修改其他批次的最终记录；由协调者决定是否更新规范数据。
