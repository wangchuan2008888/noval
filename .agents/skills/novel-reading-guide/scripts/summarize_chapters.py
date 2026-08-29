"""通用小说章节 AI 批处理与深度摘要生成工具。

本脚本符合 Skill 自动化边界规范：
- 不硬编码任何小说名称、章节范围、人物或目录；
- 输入由 --project guide-project.json 及命令行参数提供；
- 采用通用 OpenAI 兼容接口，支持任意大模型（如 LongCat, DeepSeek, Qwen, Claude, GPT 等）；
- 自动检测环境变量与 OpenCode 本地配置；
- 支持多线程并发加速、自动批次初始化、断点续传与网页端秒级实时同步。

示例：
  python summarize_chapters.py --project guide-project.json --start 1 --end 100 --workers 5
  python summarize_chapters.py --project guide-project.json --chapters 12,15,18
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Windows 控制台编码保护
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

file_lock = threading.Lock()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def detect_llm_config() -> tuple[str, str, str]:
    """多级检测 LLM 接口配置：命令行 > 环境变量 > OpenCode 本地配置。"""
    api_base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("LLM_MODEL")

    if api_base and api_key and model:
        return api_base.rstrip("/"), api_key, model

    # 尝试从 OpenCode 配置文件读取
    home = Path.home()
    possible_configs = [
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".config" / "opencode" / "opencode.json",
        home / ".opencode" / "opencode.json",
        Path("opencode.jsonc"),
        Path("opencode.json")
    ]

    for cfg_path in possible_configs:
        if cfg_path.exists():
            try:
                text = cfg_path.read_text(encoding="utf-8")
                text = re.sub(r"//.*?\n|/\*.*?\*/", "", text, flags=re.S)
                cfg = json.loads(text)
                providers = cfg.get("provider", {})
                for _, p_info in providers.items():
                    opts = p_info.get("options", {})
                    base_url = opts.get("baseURL")
                    key = opts.get("apiKey")
                    models = p_info.get("models", {})
                    model_name = next(iter(models.keys())) if models else p_info.get("model")
                    if base_url and key:
                        if not api_base:
                            api_base = base_url
                        if not api_key:
                            api_key = key
                        if not model and model_name:
                            model = model_name
                        break
            except Exception:
                continue

    # 默认回退
    api_base = (api_base or "https://api.longcat.chat/openai/v1").rstrip("/")
    if not api_base.endswith("/v1") and not api_base.endswith("/openai"):
        api_base = f"{api_base}/v1"
    api_key = api_key or "ak_2bm1ls74r9dQ5XE78S3zs2x09Fc0J"
    model = model or "LongCat-2.0"
    return api_base, api_key, model


def parse_and_repair_json(raw_text: str) -> dict:
    """智能容错 JSON 解析器：自动修复尾部截断与 markdown 包裹。"""
    raw_text = raw_text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    candidate = m.group(1) if m else raw_text

    try:
        data = json.loads(candidate)
        if "summary" in data:
            return data
    except Exception:
        pass

    # 自动补齐闭合符号
    brace_m = re.search(r"(\{.*)", candidate, re.DOTALL)
    if brace_m:
        truncated = brace_m.group(1).strip()
        for suffix in ['"}', '"]}', '"\n  ]\n}', '"]\n}', '}']:
            try:
                data = json.loads(truncated + suffix)
                if "summary" in data:
                    return data
            except Exception:
                pass

    # 正则提取兜底
    sum_m = re.search(r'"summary"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', raw_text)
    if sum_m:
        summary_val = sum_m.group(1).encode().decode('unicode_escape', errors='ignore')
        events = []
        ev_part = raw_text[raw_text.find('"key_events"'):raw_text.find('"retain_if_quick_read"') if '"retain_if_quick_read"' in raw_text else len(raw_text)]
        for ev in re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', ev_part):
            if ev not in ["key_events", "summary"]:
                events.append(ev)

        retains = []
        if '"retain_if_quick_read"' in raw_text:
            for r in re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', raw_text[raw_text.find('"retain_if_quick_read"'):]):
                if r not in ["retain_if_quick_read"]:
                    retains.append(r)

        return {
            "summary": summary_val,
            "key_events": events[:3],
            "retain_if_quick_read": retains[:2]
        }

    return {}


def call_llm(novel_title: str, ch_id: int, ch_title: str, text: str, api_base: str, api_key: str, model: str, max_tokens: int = 650) -> dict:
    """通用 LLM 章节深度精读请求。"""
    prompt = f"""阅读小说《{novel_title}》第 {ch_id} 章《{ch_title}》正文，直接撰写 200~300 字连贯剧情总结。

【本章正文】：
{text}

【要求】：
1. 严禁原句断句拼接，必须是理解后重新撰写的连贯故事。
2. 摘要（summary）必须包含：开篇动机、核心交锋/关键突破/重要对话、重大转折与本章结局。
3. 提取 1~3 条核心事件（key_events）。
4. 提取 1~2 条跳读需掌握的核心事实（retain_if_quick_read）。

请严格返回以下纯 JSON 格式：
```json
{{
  "summary": "200~300字连贯剧情总结...",
  "key_events": ["第{ch_id}章：核心事件1", "交锋：..."],
  "retain_if_quick_read": ["主线事实：...", "核心线索：..."]
}}
```"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是专业的小说分析助读专家。直接输出紧凑JSON格式总结，禁止输出任何思维链、思考过程或多余废话。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "thinking": {"type": "disabled"},
        "extra_body": {"thinking": {"type": "disabled"}}
    }

    url = f"{api_base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                content = resp_data["choices"][0]["message"]["content"].strip()
                parsed = parse_and_repair_json(content)
                if parsed and parsed.get("summary"):
                    return parsed
        except Exception:
            time.sleep(1.0 * attempt)

    return {}


def update_chapter_data(batch_dir: Path, data_chapters_path: Path, site_chapters_path: Path, ch_id: int, info: dict, result: dict, batch_size: int = 100):
    """线程安全地更新或创建批次文件，并秒级同步网站前端数据。"""
    batch_idx = (ch_id - 1) // batch_size + 1
    batch_dir.mkdir(parents=True, exist_ok=True)
    batch_file = batch_dir / f"batch-{batch_idx:03d}.json"

    with file_lock:
        # 1. 读入或初始化 batch-*.json
        if batch_file.exists():
            bdata = json.loads(batch_file.read_text(encoding="utf-8"))
        else:
            b_start = (batch_idx - 1) * batch_size + 1
            b_end = batch_idx * batch_size
            bdata = {
                "schema_version": "1.0",
                "batch_index": batch_idx,
                "owned_range": [b_start, b_end],
                "read_range": [max(1, b_start - 2), b_end + 2],
                "chapters": []
            }

        found = False
        for ch in bdata.get("chapters", []):
            if ch["id"] == ch_id:
                if result.get("summary"):
                    ch["summary"] = result["summary"]
                if isinstance(result.get("key_events"), list):
                    ch["key_events"] = result["key_events"]
                if isinstance(result.get("retain_if_quick_read"), list):
                    ch["retain_if_quick_read"] = result["retain_if_quick_read"]
                ch["analysis_status"] = "final"
                found = True
                break

        if not found:
            new_record = {
                "id": ch_id,
                "title": info["title"],
                "source": {"start_line": info["start_line"], "end_line": info["end_line"]},
                "reading_priority": "quick_read",
                "priority_reason": "过渡与推进章节：可根据摘要快速阅读，掌握核心事实即可。",
                "content_tags": ["adventure", "dialogue", "progression"],
                "narrative_roles": ["progression"],
                "teaser": f"围绕《{info['title']}》展开，推进故事主线发展。",
                "summary": result.get("summary", ""),
                "key_events": result.get("key_events", []),
                "characters_involved": [],
                "character_changes": [],
                "relationships_changed": [],
                "foreshadowing": [],
                "payoffs": [],
                "retain_if_quick_read": result.get("retain_if_quick_read", []),
                "evidence_chapters": [ch_id],
                "continuity_in": [ch_id - 1] if ch_id > 1 else [],
                "continuity_out": [ch_id + 1],
                "analysis_status": "final"
            }
            bdata["chapters"].append(new_record)
            bdata["chapters"].sort(key=lambda x: x["id"])

        batch_file.write_text(json.dumps(bdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # 2. 实时更新 data/chapters.json 与 site/data/chapters.json
        for target in [data_chapters_path, site_chapters_path]:
            if target and target.exists():
                try:
                    cdata = json.loads(target.read_text(encoding="utf-8"))
                    c_found = False
                    for ch in cdata:
                        if ch["id"] == ch_id:
                            if result.get("summary"):
                                ch["summary"] = result["summary"]
                            if isinstance(result.get("key_events"), list):
                                ch["key_events"] = result["key_events"]
                            if isinstance(result.get("retain_if_quick_read"), list):
                                ch["retain_if_quick_read"] = result["retain_if_quick_read"]
                            ch["analysis_status"] = "final"
                            c_found = True
                            break
                    if not c_found:
                        cdata.append(new_record)
                        cdata.sort(key=lambda x: x["id"])
                    target.write_text(json.dumps(cdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description="通用小说章节 AI 批处理与深度摘要生成工具")
    parser.add_argument("--project", type=Path, default=Path("guide-project.json"), help="guide-project.json 路径")
    parser.add_argument("--start", type=int, help="起始章节编号 (默认项目起始章)")
    parser.add_argument("--end", type=int, help="结束章节编号 (默认项目结束章)")
    parser.add_argument("--chapters", type=str, help="指定章节列表 (逗号分隔，如 1,2,5)")
    parser.add_argument("--workers", type=int, default=5, help="并发线程数 (默认 5)")
    parser.add_argument("--api-base", type=str, help="OpenAI 兼容 API Base URL")
    parser.add_argument("--api-key", type=str, help="API Key")
    parser.add_argument("--model", type=str, help="模型名称")
    parser.add_argument("--max-tokens", type=int, default=650, help="单章最大输出 Token (默认 650)")
    parser.add_argument("--sync-site", action="store_true", default=True, help="是否实时同步至 site/ 静态阅读站")
    args = parser.parse_args()

    project_path = args.project.resolve()
    if not project_path.exists():
        print(f"❌ 找不到项目配置文件: {project_path}")
        sys.exit(1)

    project = load_json(project_path)
    project_dir = project_path.parent

    novel_title = project.get("novel", {}).get("title", "小说")
    source_cfg = project.get("source", {})
    source_path = resolve_path(source_cfg.get("path", "小说.txt"), project_dir)
    source_encoding = source_cfg.get("encoding", "utf-8")

    data_cfg = project.get("data", {})
    data_dir = resolve_path(data_cfg.get("directory", "data"), project_dir)
    index_path = data_dir / data_cfg.get("index_file", "章节定位索引.jsonl")
    batch_dir = data_dir / "batches"
    batch_size = project.get("analysis", {}).get("batch_size", 100)
    data_chapters_path = data_dir / "chapters.json"
    site_chapters_path = (project_dir / "site" / "data" / "chapters.json") if args.sync_site else None

    # 检测或覆盖 API 配置
    def_base, def_key, def_model = detect_llm_config()
    api_base = args.api_base or def_base
    api_key = args.api_key or def_key
    model = args.model or def_model

    print("=" * 65)
    print(f"  📖 通用小说章节 AI 深度摘要生成器")
    print(f"  小说: 《{novel_title}》 | 模型: {model}")
    print(f"  接口: {api_base} | 并发线程: {args.workers}")
    print("=" * 65)

    # 读取索引与正文
    index = {}
    with index_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                index[item["number"]] = item

    with source_path.open("r", encoding=source_encoding, errors="ignore") as f:
        all_lines = f.readlines()

    coverage = project.get("coverage", {})
    start_ch = args.start or coverage.get("start_chapter", 1)
    end_ch = args.end or coverage.get("end_chapter", len(index))

    if args.chapters:
        target_ids = [int(x.strip()) for x in args.chapters.split(",") if x.strip().isdigit() and int(x.strip()) in index]
    else:
        target_ids = [cid for cid in range(start_ch, end_ch + 1) if cid in index]

    total_tasks = len(target_ids)
    print(f"\n已规划待处理章节: 共 {total_tasks} 章 (第 {start_ch} ~ {end_ch} 章)")
    start_time = time.time()
    completed = 0
    failed_ids = []

    def _worker(cid: int) -> tuple[int, bool, str]:
        info = index[cid]
        c_title = info["title"]
        s_line = info["start_line"] - 1
        e_line = info["end_line"]
        text = "".join(all_lines[s_line:e_line]).strip()

        res = call_llm(novel_title, cid, c_title, text, api_base, api_key, model, args.max_tokens)
        if res and res.get("summary"):
            update_chapter_data(batch_dir, data_chapters_path, site_chapters_path, cid, info, res, batch_size)
            return cid, True, f"第 {cid} 章《{c_title}》总结成功 ({len(res['summary'])} 字)"
        else:
            return cid, False, f"第 {cid} 章《{c_title}》总结失败"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_id = {executor.submit(_worker, cid): cid for cid in target_ids}
        for future in concurrent.futures.as_completed(future_to_id):
            cid, success, msg = future.result()
            completed += 1
            if not success:
                failed_ids.append(cid)
            elapsed = time.time() - start_time
            speed = elapsed / completed if completed > 0 else 0
            remain = (total_tasks - completed) * speed
            status_tag = "[成功]" if success else "[失败]"
            print(f"   [{completed}/{total_tasks}] {status_tag} {msg} | 进度: {completed/total_tasks*100:.1f}% | 预计剩余: {remain/60:.1f}分")

    total_time = time.time() - start_time
    success_count = total_tasks - len(failed_ids)
    print("\n" + "=" * 65)
    print(f"🎉 任务全部完成！成功: {success_count}/{total_tasks} ({success_count/total_tasks*100:.1f}%)，耗时: {total_time/60:.1f} 分钟。")
    if failed_ids:
        print(f"⚠️ 以下章节失败，可执行以下命令重试：\npython .agents/skills/novel-reading-guide/scripts/summarize_chapters.py --project {args.project} --chapters {','.join(map(str, failed_ids))}")
    print("=" * 65)


if __name__ == "__main__":
    main()
