"""从已完成的小说分析数据构建本地静态阅读网站。

此脚本不生成或改写剧情摘要、标签、优先级、人物或关系；这些内容必须已由
AI 批处理写入 data/。当 guide-project.json 指定 per-chapter-assets 时，脚本仅按
已校验的章节行号从本地原文抽取全文，供网站按需加载。

示例：
  uv run --no-project python ./novel-reading-guide/scripts/build_reading_site.py \
    --project ./guide-project.json --output ./site
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_ROOT / "assets" / "site-template"
REQUIRED_DATA_FILES = ("arcs.json", "characters.json", "relationships.json")
PRIORITIES = {"intensive", "must_read", "quick_read"}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"缺少文件：{path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 格式无效：{path}（{error}）") from error


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是对象。")
    return value


def validate_project(project: dict[str, Any]) -> None:
    if project.get("schema_version") != "1.0":
        raise ValueError("仅支持 schema_version 为 1.0 的 guide-project.json。")
    novel = require_mapping(project.get("novel"), "novel")
    if not isinstance(novel.get("id"), str) or not novel["id"].strip():
        raise ValueError("novel.id 必须是非空字符串。")
    if not isinstance(novel.get("title"), str) or not novel["title"].strip():
        raise ValueError("novel.title 必须是非空字符串。")
    source = require_mapping(project.get("source"), "source")
    if not isinstance(source.get("path"), str) or not source["path"].strip():
        raise ValueError("source.path 必须是原文路径。")
    if not isinstance(source.get("encoding"), str) or not source["encoding"].strip():
        raise ValueError("source.encoding 必须明确指定。")
    require_mapping(project.get("coverage"), "coverage")
    analysis = require_mapping(project.get("analysis"), "analysis")
    if analysis.get("status") not in {"not_started", "provisional", "final"}:
        raise ValueError("analysis.status 必须是 not_started、provisional 或 final。")
    require_mapping(project.get("site"), "site")
    if analysis["status"] != "not_started":
        story = require_mapping(project.get("story"), "story")
        for field in ("premise", "overall_summary", "end_state"):
            if not isinstance(story.get(field), str) or not story[field].strip():
                raise ValueError(f"story.{field} 必须是非空字符串。")
        if project["site"].get("full_text_mode") != "per-chapter-assets":
            raise ValueError("正式阅读站必须使用 site.full_text_mode = per-chapter-assets。")


def validate_chapters(chapters: Any) -> list[dict[str, Any]]:
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("chapters.json 必须是非空数组。")
    ids: set[int] = set()
    validated: list[dict[str, Any]] = []
    for position, record in enumerate(chapters, start=1):
        chapter = require_mapping(record, f"chapters[{position}]")
        chapter_id = chapter.get("id")
        if not isinstance(chapter_id, int) or chapter_id <= 0 or chapter_id in ids:
            raise ValueError(f"chapters[{position}].id 必须是唯一的正整数。")
        ids.add(chapter_id)
        for field in ("title", "summary", "teaser", "priority_reason", "arc_id"):
            if not isinstance(chapter.get(field), str) or not chapter[field].strip():
                raise ValueError(f"第 {chapter_id} 章缺少非空字段 {field}。")
        if chapter.get("reading_priority") not in PRIORITIES:
            raise ValueError(f"第 {chapter_id} 章的 reading_priority 无效。")
        for field in ("content_tags", "narrative_roles", "retain_if_quick_read"):
            if field in chapter and not isinstance(chapter[field], list):
                raise ValueError(f"第 {chapter_id} 章的 {field} 必须是数组。")
        source = require_mapping(chapter.get("source"), f"第 {chapter_id} 章 source")
        start_line, end_line = source.get("start_line"), source.get("end_line")
        if not isinstance(start_line, int) or not isinstance(end_line, int) or start_line < 1 or end_line < start_line:
            raise ValueError(f"第 {chapter_id} 章的 source 行号无效。")
        validated.append(chapter)
    return validated


def validate_integrated_data(
    project: dict[str, Any], chapters: list[dict[str, Any]], arcs: list[Any], characters: list[Any], relationships: list[Any], index: list[Any]
) -> None:
    coverage = project["coverage"]
    expected = set(range(coverage.get("start_chapter", 0), coverage.get("end_chapter", -1) + 1))
    if {chapter["id"] for chapter in chapters} != expected:
        raise ValueError("chapters.json 未恰好覆盖 guide-project.json 声明的章节范围。")
    arcs_by_id = {arc.get("id"): arc for arc in arcs if isinstance(arc, dict) and isinstance(arc.get("id"), str)}
    people_by_id = {person.get("id"): person for person in characters if isinstance(person, dict) and isinstance(person.get("id"), str)}
    if not arcs_by_id or not people_by_id:
        raise ValueError("arcs.json 和 characters.json 均须包含带稳定 ID 的记录。")
    index_by_id = {row.get("number"): row for row in index if isinstance(row, dict)}
    status = project["analysis"]["status"]
    for chapter in chapters:
        chapter_id = chapter["id"]
        if chapter["arc_id"] not in arcs_by_id:
            raise ValueError(f"第 {chapter_id} 章引用了不存在的 arc_id。")
        involved = chapter.get("characters_involved")
        if not isinstance(involved, list) or not involved or any(person not in people_by_id for person in involved):
            raise ValueError(f"第 {chapter_id} 章的 characters_involved 无效。")
        if not chapter.get("content_tags") or not chapter.get("narrative_roles"):
            raise ValueError(f"第 {chapter_id} 章必须具有内容标签和叙事作用。")
        if chapter["reading_priority"] == "quick_read" and not chapter.get("retain_if_quick_read"):
            raise ValueError(f"第 {chapter_id} 章为 quick_read，但未给出保留信息。")
        if chapter.get("analysis_status") != status:
            raise ValueError(f"第 {chapter_id} 章的 analysis_status 与项目状态不一致。")
        if not chapter.get("evidence_chapters"):
            raise ValueError(f"第 {chapter_id} 章缺少 evidence_chapters。")
        indexed = index_by_id.get(chapter_id)
        if not indexed or chapter["source"]["start_line"] != indexed.get("start_line") or chapter["source"]["end_line"] != indexed.get("end_line"):
            raise ValueError(f"第 {chapter_id} 章行号与章节索引不一致。")
    for relation in relationships:
        if not isinstance(relation, dict) or relation.get("from") not in people_by_id or relation.get("to") not in people_by_id:
            raise ValueError("relationships.json 包含未知人物 ID。")


def prepare_output(output: Path, replace: bool) -> None:
    if output.exists():
        if not replace:
            raise ValueError(f"输出目录已存在：{output}。如确认覆盖，请添加 --replace。")
        if output.resolve() in {Path(output.anchor).resolve(), Path.cwd().resolve()}:
            raise ValueError("拒绝覆盖磁盘根目录或当前工作目录。")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=False)


def extract_text_assets(
    project: dict[str, Any], project_dir: Path, chapters: list[dict[str, Any]], data_output: Path
) -> dict[int, str]:
    source_info = project["source"]
    source_path = resolve_path(source_info["path"], project_dir)
    if not source_path.is_file():
        raise ValueError(f"找不到原文：{source_path}")
    raw = source_path.read_bytes()
    expected_hash = source_info.get("sha256")
    actual_hash = hashlib.sha256(raw).hexdigest()
    if expected_hash and expected_hash != actual_hash:
        raise ValueError("源文件 SHA-256 与 guide-project.json 不一致；请重新建立索引或更新元信息。")
    try:
        lines = raw.decode(source_info["encoding"]).splitlines(keepends=True)
    except UnicodeDecodeError as error:
        raise ValueError(f"无法按 {source_info['encoding']} 解码原文。") from error
    declared_count = source_info.get("line_count")
    if isinstance(declared_count, int) and declared_count and declared_count != len(lines):
        raise ValueError("源文件行数与 guide-project.json 不一致；请重新建立索引或更新元信息。")

    text_dir = data_output / "text"
    text_dir.mkdir()
    assets: dict[int, str] = {}
    for chapter in chapters:
        start = chapter["source"]["start_line"] - 1
        end = chapter["source"]["end_line"]
        if end > len(lines):
            raise ValueError(f"第 {chapter['id']} 章的行号超出原文范围。")
        filename = f"{chapter['id']:04d}.txt"
        (text_dir / filename).write_text("".join(lines[start:end]), encoding="utf-8")
        assets[chapter["id"]] = f"data/text/{filename}"
    return assets


def build(project_path: Path, output: Path, replace: bool) -> None:
    project_path = project_path.resolve()
    output = output.resolve()
    project = require_mapping(load_json(project_path), "guide-project.json")
    validate_project(project)
    if project["analysis"]["status"] == "not_started":
        raise ValueError("项目尚未完成任何语义分析，不能构建阅读网站。请先生成真实的批次章节数据。")
    project_dir = project_path.parent
    data_config = project.get("data", {})
    if not isinstance(data_config, dict):
        raise ValueError("data 必须是对象。")
    data_dir = resolve_path(data_config.get("directory", "data"), project_dir)
    chapters = validate_chapters(load_json(data_dir / "chapters.json"))

    integrated: dict[str, list[Any]] = {}
    for filename in REQUIRED_DATA_FILES:
        path = data_dir / filename
        value = load_json(path)
        if not isinstance(value, list):
            raise ValueError(f"{path} 必须是数组。")
        integrated[filename] = value
    index_path = data_dir / data_config.get("index_file", "章节定位索引.jsonl")
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    validate_integrated_data(project, chapters, integrated["arcs.json"], integrated["characters.json"], integrated["relationships.json"], index)
    if output in {project_dir, data_dir, project_path}:
        raise ValueError("输出目录不能是项目目录、数据目录或项目配置文件。")

    prepare_output(output.resolve(), replace)
    try:
        shutil.copytree(TEMPLATE_DIR, output, dirs_exist_ok=True)
        data_output = output / "data"
        data_output.mkdir()
        site_chapters = copy.deepcopy(chapters)
        if project["site"].get("full_text_mode") == "per-chapter-assets":
            assets = extract_text_assets(project, project_dir, chapters, data_output)
            for chapter in site_chapters:
                chapter["text_asset"] = assets[chapter["id"]]

        public_project = copy.deepcopy(project)
        public_project["source"].pop("path", None)
        write_json(data_output / "manifest.json", public_project)
        write_json(data_output / "chapters.json", site_chapters)
        for filename, value in integrated.items():
            write_json(data_output / filename, value)
        (output / "README.md").write_text(
            "# 本地阅读网站\n\n"
            "在本目录运行：\n\n"
            "```powershell\n"
            "uv run --no-project python -m http.server 8000 --directory .\n"
            "```\n\n"
            "然后在浏览器打开 `http://localhost:8000`。关闭命令行即可停止服务器。\n",
            encoding="utf-8",
        )
    except Exception:
        if output.exists():
            shutil.rmtree(output)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="从规范小说数据构建本地静态阅读网站。")
    parser.add_argument("--project", type=Path, required=True, help="guide-project.json 路径")
    parser.add_argument("--output", type=Path, required=True, help="输出 site 目录")
    parser.add_argument("--replace", action="store_true", help="明确允许替换已有输出目录")
    args = parser.parse_args()
    build(args.project, args.output, args.replace)


if __name__ == "__main__":
    main()
