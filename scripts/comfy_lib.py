#!/usr/bin/env python3
"""Shared helpers for calling ComfyUI partner (API) nodes from the CLI."""
import json, os, time, urllib.request, urllib.error, shutil
from pathlib import Path

BASE = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")
def _resolve_root() -> Path:
    """自解析根目录：环境变量 H3_ROOT > 同目录 h3.conf > 本文件上一级（仓库根）。"""
    env = os.environ.get("H3_ROOT", "").strip()
    if env:
        return Path(env).expanduser()
    root = Path(__file__).resolve().parent.parent
    conf = root / "h3.conf"
    if conf.is_file():
        for line in conf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("H3_ROOT="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return Path(val).expanduser()
    return root


ROOT = _resolve_root()
KEY_FILE = ROOT / ".comfy_api_key"


def api_key():
    k = os.environ.get("COMFY_API_KEY", "").strip()
    if not k and KEY_FILE.exists():
        k = KEY_FILE.read_text().strip()
    return k or None


def require_key():
    k = api_key()
    if not k:
        raise SystemExit(
            "❌ 未找到 Comfy API Key。\n"
            "   1) 到 https://platform.comfy.org/login 生成（格式 comfyui-xxxx）\n"
            f"   2) 写入 {KEY_FILE}（建议 chmod 600），或设置环境变量 COMFY_API_KEY\n"
            "   注意：这是 Comfy 账户的 API Key，不是 MiniMax 官方 key。"
        )
    return k


def _post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read())


def run_graph(graph, timeout=1800, label=""):
    """Queue an API-format graph and wait for it to finish. Returns history entry."""
    payload = {"prompt": graph}
    k = api_key()
    if k:
        payload["extra_data"] = {"api_key_comfy_org": k}
    try:
        resp = _post("/prompt", payload)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        try:
            d = json.loads(body)
            err = d.get("error", {})
            raise SystemExit(f"❌ 排队失败: {err.get('type')} — {str(err.get('message'))[:300]}\n"
                             f"   node_errors={json.dumps(d.get('node_errors') or {}, ensure_ascii=False)[:400]}")
        except json.JSONDecodeError:
            raise SystemExit(f"❌ 排队失败 HTTP {e.code}: {body[:300]}")

    pid = resp["prompt_id"]
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        try:
            h = _get(f"/history/{pid}")
        except Exception:
            time.sleep(3); continue
        if pid in h:
            entry = h[pid]
            st = entry.get("status", {})
            if st.get("status_str") == "error":
                msgs = st.get("messages", [])
                detail = ""
                for m in msgs:
                    if m[0] == "execution_error":
                        d = m[1]
                        detail = f"{d.get('node_type')}: {d.get('exception_message')}"
                raise SystemExit(f"❌ 执行失败{(' ['+label+']') if label else ''}: {detail[:600]}")
            return entry
        # 进度
        try:
            q = _get("/queue")
            running = q.get("queue_running") or []
            if running:
                cur = f"执行中 ({len(q.get('queue_pending') or [])} 排队)"
                if cur != last:
                    print(f"  {cur}...", flush=True); last = cur
        except Exception:
            pass
        time.sleep(4)
    raise SystemExit("❌ 超时")


def output_path(entry):
    """Locate the first produced file under ComfyUI/output."""
    out_dir = ROOT / "ComfyUI" / "output"
    files = []
    for nid, out in (entry.get("outputs") or {}).items():
        for key in ("text", "images", "videos", "gifs", "result"):
            for item in (out.get(key) or []):
                if isinstance(item, dict):
                    sub = item.get("subfolder", "")
                    fn = item.get("filename")
                    if fn:
                        p = out_dir / sub / fn
                        # LoadVideo 的回显也会带 filename，但它指向 input/，不是产物
                        if p.exists():
                            files.append(p)
    return files