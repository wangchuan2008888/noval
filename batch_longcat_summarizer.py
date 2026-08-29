"""LongCat-2.0 批量小说章节精读与深度摘要队列脚本（含智能JSON容错修复与失败重试）。"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# 保证 Windows 控制台 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 配置信息
BASE_DIR = Path(__file__).resolve().parent
TXT_PATH = BASE_DIR / "谁说没灵根不能修仙的？.txt"
INDEX_PATH = BASE_DIR / "data" / "章节定位索引.jsonl"
BATCH_DIR = BASE_DIR / "data" / "batches"
PROJECT_PATH = BASE_DIR / "guide-project.json"
DATA_CHAPTERS_PATH = BASE_DIR / "data" / "chapters.json"
SITE_CHAPTERS_PATH = BASE_DIR / "site" / "data" / "chapters.json"

# LongCat API 配置
API_KEY = "ak_2bm1ls74r9dQ5XE78S3zs2x09Fc0J"
BASE_URL = "https://api.longcat.chat/openai/v1"
MODEL_NAME = "LongCat-2.0"

# 文件写入锁
file_lock = threading.Lock()


def load_index() -> dict[int, dict]:
    index = {}
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                index[item["number"]] = item
    return index


def get_chapter_text(ch_id: int, index: dict, lines: list[str]) -> str:
    if ch_id not in index:
        return ""
    info = index[ch_id]
    s_line = info["start_line"] - 1
    e_line = info["end_line"]
    return "".join(lines[s_line:e_line]).strip()


def parse_and_repair_json(raw_text: str) -> dict:
    """智能容错 JSON 解析器：自动修复尾部截断，或通过正则提取 summary/key_events。"""
    raw_text = raw_text.strip()
    
    # 尝试提取 ```json 块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    candidate = m.group(1) if m else raw_text
    
    # 1. 尝试直接标准解析
    try:
        data = json.loads(candidate)
        if "summary" in data:
            return data
    except Exception:
        pass

    # 2. 尝试提取 { 开头到结尾并自动补齐引号和花括号
    brace_m = re.search(r"(\{.*)", candidate, re.DOTALL)
    if brace_m:
        truncated_json = brace_m.group(1).strip()
        # 尝试补齐常见的截断形式
        for suffix in ['"}', '"]}', '"\n  ]\n}', '"]\n}', '}']:
            try:
                data = json.loads(truncated_json + suffix)
                if "summary" in data:
                    return data
            except Exception:
                pass

    # 3. 兜底方案：正则直接提取 "summary": "..."
    sum_m = re.search(r'"summary"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', raw_text)
    if sum_m:
        summary_val = sum_m.group(1).encode().decode('unicode_escape', errors='ignore')
        
        # 提取 key_events
        events = []
        ev_m = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', raw_text[raw_text.find('"key_events"'):raw_text.find('"retain_if_quick_read"') if '"retain_if_quick_read"' in raw_text else len(raw_text)])
        for ev in ev_m:
            if ev not in ["key_events", "summary"]:
                events.append(ev)

        # 提取 retain_if_quick_read
        retains = []
        if '"retain_if_quick_read"' in raw_text:
            ret_m = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', raw_text[raw_text.find('"retain_if_quick_read"'):])
            for r in ret_m:
                if r not in ["retain_if_quick_read"]:
                    retains.append(r)

        return {
            "summary": summary_val,
            "key_events": events[:3],
            "retain_if_quick_read": retains[:2]
        }

    return {}


def call_longcat_api(ch_id: int, title: str, text: str, max_retries: int = 3) -> dict:
    """调用 LongCat-2.0 生成深度剧情总结（充足 max_tokens 缓冲 + 智能容错）。"""
    prompt = f"""阅读修仙小说《谁说没灵根不能修仙的？》第 {ch_id} 章《{title}》正文，直接撰写 200~300 字连贯剧情总结。

【本章正文】：
{text}

【要求】：
1. 严禁原句断句拼接，必须是理解后重新撰写的连贯故事。
2. 摘要（summary）必须包含：开篇动机、核心交锋/关键突破、重大转折与本章结局。
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
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "你是高效的小说摘要专家。直接输出紧凑JSON格式总结，禁止输出任何思维链、思考过程或多余废话。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 650,  # 充足缓冲，避免 400 token 被截断
        "temperature": 0.3,
        "thinking": {"type": "disabled"},
        "extra_body": {"thinking": {"type": "disabled"}}
    }

    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                content = resp_data["choices"][0]["message"]["content"].strip()
                
                parsed = parse_and_repair_json(content)
                if parsed and "summary" in parsed and parsed["summary"]:
                    return parsed
        except Exception as err:
            time.sleep(1.0 * attempt)

    return {}


def update_chapter_in_batch_and_site(ch_id: int, result: dict):
    """加锁保存单章摘要至批次文件，并实时秒级同步到网页端 chapters.json。"""
    batch_idx = (ch_id - 1) // 100 + 1
    batch_file = BATCH_DIR / f"batch-{batch_idx:03d}.json"
    if not batch_file.exists():
        return

    with file_lock:
        # 1. 更新 batch-XXX.json
        bdata = json.loads(batch_file.read_text(encoding="utf-8"))
        for ch in bdata.get("chapters", []):
            if ch["id"] == ch_id:
                if "summary" in result and result["summary"]:
                    ch["summary"] = result["summary"]
                if "key_events" in result and isinstance(result["key_events"], list):
                    ch["key_events"] = result["key_events"]
                if "retain_if_quick_read" in result and isinstance(result["retain_if_quick_read"], list):
                    ch["retain_if_quick_read"] = result["retain_if_quick_read"]
                ch["analysis_status"] = "final"
                break
        batch_file.write_text(json.dumps(bdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # 2. 实时同步更新 data/chapters.json 与 site/data/chapters.json
        for target_path in [DATA_CHAPTERS_PATH, SITE_CHAPTERS_PATH]:
            if target_path.exists():
                try:
                    cdata = json.loads(target_path.read_text(encoding="utf-8"))
                    for ch in cdata:
                        if ch["id"] == ch_id:
                            if "summary" in result and result["summary"]:
                                ch["summary"] = result["summary"]
                            if "key_events" in result and isinstance(result["key_events"], list):
                                ch["key_events"] = result["key_events"]
                            if "retain_if_quick_read" in result and isinstance(result["retain_if_quick_read"], list):
                                ch["retain_if_quick_read"] = result["retain_if_quick_read"]
                            ch["analysis_status"] = "final"
                            break
                    target_path.write_text(json.dumps(cdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except Exception:
                    pass


def process_single_chapter(ch_id: int, index: dict, lines: list[str]) -> tuple[int, bool, str]:
    if ch_id not in index:
        return ch_id, False, "未在索引中找到"
    
    info = index[ch_id]
    title = info["title"]
    text = get_chapter_text(ch_id, index, lines)
    
    res = call_longcat_api(ch_id, title, text)
    if res and "summary" in res and res["summary"]:
        update_chapter_in_batch_and_site(ch_id, res)
        return ch_id, True, f"第 {ch_id} 章《{title}》总结成功 ({len(res['summary'])} 字，网页已同步)"
    else:
        return ch_id, False, f"第 {ch_id} 章《{title}》总结失败"


def run_pipeline(start_ch: int, end_ch: int, workers: int = 5, specific_list: list[int] = None):
    print("=" * 65)
    if specific_list:
        print(f"  [启动] LongCat-2.0 针对性补跑：共 {len(specific_list)} 个失败章节")
    else:
        print(f"  [启动] LongCat-2.0 批量摘要任务：第 {start_ch} 章 ~ 第 {end_ch} 章")
    print(f"  模式: 关闭推理 | max_tokens=650 + JSON容错 | 并发线程: {workers}")
    print("=" * 65)

    print("\n1. 正在加载全书索引与正文...")
    index = load_index()
    with TXT_PATH.open("r", encoding="gb18030", errors="ignore") as f:
        all_lines = f.readlines()
    print(f"   全文加载完成，共 {len(all_lines)} 行。\n")

    if specific_list:
        chapter_ids = [cid for cid in specific_list if cid in index]
    else:
        chapter_ids = [cid for cid in range(start_ch, end_ch + 1) if cid in index]

    total_tasks = len(chapter_ids)
    completed = 0
    start_time = time.time()

    print(f"2. 启动 {workers} 个工作线程并发处理 {total_tasks} 个章节...")

    failed_ids = []

    if workers <= 1:
        for cid in chapter_ids:
            _, success, msg = process_single_chapter(cid, index, all_lines)
            completed += 1
            if not success:
                failed_ids.append(cid)
            elapsed = time.time() - start_time
            speed = elapsed / completed if completed > 0 else 0
            remain = (total_tasks - completed) * speed
            status_tag = "[成功]" if success else "[失败]"
            print(f"   [{completed}/{total_tasks}] {status_tag} {msg} | 预计剩余: {remain/60:.1f}分钟")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_id = {executor.submit(process_single_chapter, cid, index, all_lines): cid for cid in chapter_ids}
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
    print("\n" + "=" * 65)
    success_count = total_tasks - len(failed_ids)
    print(f"[完成] 全部执行完毕！成功: {success_count}/{total_tasks} ({success_count/total_tasks*100:.1f}%)，总耗时: {total_time/60:.1f} 分钟。")
    if failed_ids:
        print(f"以下章节处理失败，可使用 --chapters {','.join(map(str, failed_ids))} 重试：")
        print(failed_ids)
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="LongCat-2.0 批量小说章节摘要处理工具")
    parser.add_argument("--start", type=int, default=1905, help="起始章节编号 (默认 1905)")
    parser.add_argument("--end", type=int, default=2438, help="结束章节编号 (默认 2438)")
    parser.add_argument("--workers", type=int, default=5, help="并发线程数 (默认 5)")
    parser.add_argument("--chapters", type=str, default="", help="指定重试的章节列表，逗号分隔，如 2116,2126,2136")
    args = parser.parse_args()

    specific = [int(x.strip()) for x in args.chapters.split(",") if x.strip().isdigit()] if args.chapters else None
    run_pipeline(args.start, args.end, args.workers, specific)


if __name__ == "__main__":
    main()
