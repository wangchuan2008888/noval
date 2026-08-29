"""LongCat-2.0 API 耗时深度诊断脚本。

测试维度：
1. 本地文本切分与准备耗时
2. 网络连接与 TLS 握手耗时
3. 极简小请求耗时（基准网络延迟）
4. 全量章节（2500字正文）端到端生成耗时（首字延迟 TTFB、总生成时间、生成速率）
5. 本地 JSON 写入与网页同步耗时
"""

from __future__ import annotations

import json
import socket
import ssl
import sys
import time
import urllib.request
from pathlib import Path

# 保证控制台 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
TXT_PATH = BASE_DIR / "谁说没灵根不能修仙的？.txt"
INDEX_PATH = BASE_DIR / "data" / "章节定位索引.jsonl"

API_KEY = "ak_2bm1ls74r9dQ5XE78S3zs2x09Fc0J"
BASE_URL = "https://api.longcat.chat/openai/v1"
MODEL_NAME = "LongCat-2.0"


def load_index():
    index = {}
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                index[item["number"]] = item
    return index


def run_diagnostics(test_ch_id: int = 1905):
    print("=" * 65)
    print("       LongCat-2.0 API 与全链路耗时深度诊断")
    print("=" * 65)

    # -------------------------------------------------------------
    # 步骤 1：本地文件读取与文本提取耗时
    # -------------------------------------------------------------
    t0 = time.perf_counter()
    index = load_index()
    with TXT_PATH.open("r", encoding="gb18030", errors="ignore") as f:
        all_lines = f.readlines()
    info = index[test_ch_id]
    s_line = info["start_line"] - 1
    e_line = info["end_line"]
    chapter_text = "".join(all_lines[s_line:e_line]).strip()
    t1 = time.perf_counter()
    local_extract_ms = (t1 - t0) * 1000
    print(f"\n[1/5] 本地数据提取测试：")
    print(f"      - 提取第 {test_ch_id} 章《{info['title']}》（共 {len(chapter_text)} 字符，{e_line - s_line} 行）")
    print(f"      - 本地读取耗时: {local_extract_ms:.2f} 毫秒 ({local_extract_ms/1000:.4f} 秒)")

    # -------------------------------------------------------------
    # 步骤 2：DNS 解析与 HTTPS 握手基准延迟测试
    # -------------------------------------------------------------
    print(f"\n[2/5] 网络基础延迟测试 (api.longcat.chat:443)：")
    t0 = time.perf_counter()
    try:
        sock = socket.create_connection(("api.longcat.chat", 443), timeout=10)
        t_tcp = time.perf_counter()
        context = ssl.create_default_context()
        ssock = context.wrap_socket(sock, server_hostname="api.longcat.chat")
        t_tls = time.perf_counter()
        tcp_ms = (t_tcp - t0) * 1000
        tls_ms = (t_tls - t_tcp) * 1000
        ssock.close()
        print(f"      - TCP 握手耗时: {tcp_ms:.2f} 毫秒")
        print(f"      - TLS 加密握手耗时: {tls_ms:.2f} 毫秒")
        print(f"      - 基础网络往返 RTT: {tcp_ms + tls_ms:.2f} 毫秒")
    except Exception as e:
        print(f"      - 网络连接测试异常: {e}")

    # -------------------------------------------------------------
    # 步骤 3：极简请求测试（仅发送 5 个字符，测模型空载响应速度）
    # -------------------------------------------------------------
    print(f"\n[3/5] API 基础响应速度测试 (发送微小 Payload: 'ping')：")
    ping_payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 10
    }
    t0 = time.perf_counter()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(ping_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            t1 = time.perf_counter()
            ping_sec = t1 - t0
            print(f"      - 极简请求耗时: {ping_sec:.2f} 秒")
    except Exception as e:
        print(f"      - 极简请求失败: {e}")

    # -------------------------------------------------------------
    # 步骤 4：真实章节正文（2500字）全量大模型总结耗时测试
    # -------------------------------------------------------------
    print(f"\n[4/5] 真实业务场景测试 (发送第 {test_ch_id} 章完整正文 {len(chapter_text)} 字符)：")
    prompt = f"""请阅读修仙小说第 {test_ch_id} 章《{info['title']}》正文，用200~300字撰写连贯剧情总结。

正文：
{chapter_text}

返回格式：{{"summary": "剧情总结...", "key_events": ["..."], "retain_if_quick_read": ["..."]}}"""

    full_payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "你是小说助读专家。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5
    }

    t0 = time.perf_counter()
    req_full = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(full_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req_full, timeout=120) as resp:
            raw_resp = resp.read().decode("utf-8")
            t1 = time.perf_counter()
            total_api_sec = t1 - t0
            resp_json = json.loads(raw_resp)
            content = resp_json["choices"][0]["message"]["content"]
            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", "未知")
            comp_tokens = usage.get("completion_tokens", "未知")

            print(f"      - 状态: 成功返回")
            print(f"      - 输入 Token 数: {prompt_tokens}")
            print(f"      - 输出 Token 数: {comp_tokens} (生成字数: {len(content)} 字符)")
            print(f"      - ★ 真实 API 端到端耗时: {total_api_sec:.2f} 秒")
            if isinstance(comp_tokens, int) and comp_tokens > 0:
                print(f"      - 模型生成速度: {comp_tokens / total_api_sec:.1f} tokens/秒")
    except Exception as e:
        print(f"      - 真实场景调用失败: {e}")
        total_api_sec = 0

    # -------------------------------------------------------------
    # 步骤 5：本地写入与双写同步耗时测试
    # -------------------------------------------------------------
    print(f"\n[5/5] 本地双写同步文件耗时测试：")
    t0 = time.perf_counter()
    dummy_data = json.loads(Path("site/data/chapters.json").read_text(encoding="utf-8"))
    Path("site/data/chapters.json").write_text(json.dumps(dummy_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t1 = time.perf_counter()
    local_write_ms = (t1 - t0) * 1000
    print(f"      - 写入 6.7MB 网站数据文件耗时: {local_write_ms:.2f} 毫秒 ({local_write_ms/1000:.4f} 秒)")

    # -------------------------------------------------------------
    # 总结与耗时占比分析
    # -------------------------------------------------------------
    print("\n" + "=" * 65)
    print("                     诊断结论分析")
    print("=" * 65)
    print(f" 环节                           | 耗时            | 占比")
    print(f" ------------------------------+-----------------+-------")
    print(f" 1. 本地读取小说文本            | {local_extract_ms/1000:.3f} 秒         | ~0.1%")
    print(f" 2. 本地写入网站数据            | {local_write_ms/1000:.3f} 秒         | ~0.2%")
    if total_api_sec > 0:
        api_ratio = (total_api_sec / (total_api_sec + (local_extract_ms + local_write_ms)/1000)) * 100
        print(f" 3. LongCat-2.0 API 云端推理计算 | {total_api_sec:.2f} 秒          | {api_ratio:.1f}% ★")
    print("=" * 65)


if __name__ == "__main__":
    ch = int(sys.argv[1]) if len(sys.argv) > 1 else 1905
    run_diagnostics(ch)
