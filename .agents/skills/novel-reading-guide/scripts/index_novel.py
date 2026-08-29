"""为章节式 TXT 小说建立章节 → 原文行号索引。

示例（PowerShell）：
  uv run --no-project python ./novel-reading-guide/scripts/index_novel.py \
    "./小说.txt" --limit 100 --output-dir "./输出目录"

脚本只读取原小说，输出 UTF-8 BOM 的 CSV、JSONL 和索引说明 JSON。
默认识别形如“第12章 标题”或“第十二章 标题”的章节标题。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


CHAPTER_RE = re.compile(r"^\s*第\s*([0-9一二三四五六七八九十百千万零〇两]+)\s*章(?:\s+(.*?))?\s*$")
CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    start_line: int
    end_line: int


def parse_chapter_number(value: str) -> int:
    if value.isascii() and value.isdigit():
        return int(value)

    total = 0
    current = 0
    for character in value:
        if character in CHINESE_DIGITS:
            current = CHINESE_DIGITS[character]
        elif character in CHINESE_UNITS:
            unit = CHINESE_UNITS[character]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
        else:
            raise ValueError(f"不支持的章节数字：{value}")
    return total + current


def read_lines(source: Path) -> tuple[list[str], str]:
    raw = source.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding).splitlines(), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("无法以 UTF-8 或 GB18030 解码此小说文件。")


def find_chapters(lines: list[str]) -> list[Chapter]:
    headings: list[tuple[int, int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        matched = CHAPTER_RE.match(line)
        if matched:
            headings.append((line_number, parse_chapter_number(matched.group(1)), (matched.group(2) or "").strip()))

    if not headings:
        raise ValueError("未找到类似"第1章 标题"或"第一章 标题"的章节标题；请按该小说的标题格式调整 CHAPTER_RE。")

    numbers = [heading[1] for heading in headings]
    if any(later <= earlier for earlier, later in zip(numbers, numbers[1:])):
        raise ValueError("检测到重复或倒序章节号；请调整 CHAPTER_RE，避免把正文误识别为章节标题。")

    chapters: list[Chapter] = []
    for position, (start_line, number, title) in enumerate(headings):
        end_line = headings[position + 1][0] - 1 if position + 1 < len(headings) else len(lines)
        chapters.append(Chapter(number, title, start_line, end_line))
    return chapters


def write_outputs(source: Path, limit: int, output_dir: Path, replace: bool = False) -> None:
    lines, encoding = read_lines(source)
    all_chapters = find_chapters(lines)
    selected = all_chapters[:limit] if limit else all_chapters
    targets = [output_dir / name for name in ("索引说明.json", "章节定位索引.csv", "章节定位索引.jsonl")]
    if any(target.exists() for target in targets) and not replace:
        raise ValueError("索引文件已存在；确认重建后请添加 --replace。")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source_path": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_encoding": encoding,
        "source_line_count": len(lines),
        "detected_chapter_count": len(all_chapters),
        "exported_chapter_count": len(selected),
    }
    (output_dir / "索引说明.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (output_dir / "章节定位索引.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["章节", "标题", "起始行", "结束行", "行数"])
        writer.writeheader()
        for chapter in selected:
            writer.writerow({
                "章节": chapter.number,
                "标题": chapter.title,
                "起始行": chapter.start_line,
                "结束行": chapter.end_line,
                "行数": chapter.end_line - chapter.start_line + 1,
            })

    with (output_dir / "章节定位索引.jsonl").open("w", encoding="utf-8") as file:
        for chapter in selected:
            file.write(json.dumps(asdict(chapter), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="为 TXT 小说建立章节 → 原文行号导航。")
    parser.add_argument("source", type=Path, help="小说 TXT 文件")
    parser.add_argument("--limit", type=int, default=0, help="仅导出前 N 章；0 表示全部")
    parser.add_argument("--output-dir", type=Path, required=True, help="输出目录")
    parser.add_argument("--replace", action="store_true", help="明确允许覆盖已有索引文件")
    args = parser.parse_args()
    write_outputs(args.source, args.limit, args.output_dir, args.replace)


if __name__ == "__main__":
    main()
