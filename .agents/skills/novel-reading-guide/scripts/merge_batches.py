"""校验并合并已完成的小说章节批次；绝不生成剧情内容。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def fail(message: str) -> None:
    raise ValueError(message)


def merge(project_path: Path, replace: bool = False) -> None:
    project_path = project_path.resolve()
    project = load_json(project_path)
    if project.get("schema_version") != "1.0":
        fail("仅支持 schema_version 1.0。")
    project_dir = project_path.parent
    data_config = project.get("data", {})
    if not isinstance(data_config, dict):
        fail("data 必须是对象。")
    data_dir = resolve(data_config.get("directory", "data"), project_dir)
    index_path = data_dir / data_config.get("index_file", "章节定位索引.jsonl")
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    index_by_id = {row["number"]: row for row in index}
    coverage = project.get("coverage", {})
    start, end = coverage.get("start_chapter"), coverage.get("end_chapter")
    if not isinstance(start, int) or not isinstance(end, int) or end < start:
        fail("coverage 的章节范围无效。")
    expected_ids = set(range(start, end + 1))
    if not expected_ids <= set(index_by_id):
        fail("索引未覆盖项目声明的章节范围。")
    batch_dir = data_dir / "batches"
    batch_paths = sorted(batch_dir.glob("batch-*.json"))
    if not batch_paths:
        fail("未找到 data/batches/batch-*.json。")

    records: dict[int, dict[str, Any]] = {}
    source_hash = project.get("source", {}).get("sha256")
    for path in batch_paths:
        batch = load_json(path)
        if batch.get("schema_version") != "1.0" or batch.get("status") != "ready_for_integration":
            fail(f"批次不可合并：{path.name}")
        if source_hash and batch.get("source_sha256") != source_hash:
            fail(f"批次源哈希不一致：{path.name}")
        owned = batch.get("owned_range")
        read = batch.get("read_range")
        if not (isinstance(owned, list) and len(owned) == 2 and all(isinstance(x, int) for x in owned)):
            fail(f"owned_range 无效：{path.name}")
        if not (isinstance(read, list) and len(read) == 2 and read[0] <= owned[0] <= owned[1] <= read[1]):
            fail(f"read_range 未覆盖 owned_range：{path.name}")
        owned_ids = set(range(owned[0], owned[1] + 1))
        chapters = batch.get("chapters")
        if not isinstance(chapters, list) or {chapter.get("id") for chapter in chapters if isinstance(chapter, dict)} != owned_ids:
            fail(f"批次未恰好输出 owned_range：{path.name}")
        for chapter in chapters:
            chapter_id = chapter["id"]
            if chapter_id in records:
                fail(f"章节 {chapter_id} 被多个批次拥有。")
            indexed = index_by_id.get(chapter_id)
            source = chapter.get("source", {})
            if not indexed or source.get("start_line") != indexed["start_line"] or source.get("end_line") != indexed["end_line"]:
                fail(f"章节 {chapter_id} 的原文行号与索引不一致。")
            records[chapter_id] = chapter

    if set(records) != expected_ids:
        missing = sorted(expected_ids - set(records))
        extra = sorted(set(records) - expected_ids)
        fail(f"批次覆盖不完整；缺失={missing[:10]}，范围外={extra[:10]}")
    output = data_dir / "chapters.json"
    if output.exists() and not replace:
        fail("chapters.json 已存在；确认替换后请添加 --replace。")
    output.write_text(json.dumps([records[number] for number in sorted(records)], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已合并 {len(records)} 章至 {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="校验并合并小说章节批次。")
    parser.add_argument("--project", type=Path, required=True, help="guide-project.json 路径")
    parser.add_argument("--replace", action="store_true", help="明确允许覆盖 chapters.json")
    args = parser.parse_args()
    merge(args.project, args.replace)


if __name__ == "__main__":
    main()
