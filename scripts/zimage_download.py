#!/usr/bin/env python3
"""下载 Z-Image 文生图所需的 4 个文件（ModelScope，并行 + 断点续传）。"""
import json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

DEST = os.environ.get("COMFY_MODELS_DIR", os.path.join(os.environ.get("H3_ROOT", os.path.expanduser("~/minimax-h3")), "ComfyUI", "models"))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131 Safari/537.36"
WORKERS = 4

# (仓库, 仓库内路径, 本地目标目录)
FILES = [
    ("Comfy-Org/z_image_turbo", "split_files/diffusion_models/z_image_turbo_bf16.safetensors", "diffusion_models"),
    ("Comfy-Org/z_image",       "split_files/diffusion_models/z_image_bf16.safetensors",       "diffusion_models"),
    ("Comfy-Org/z_image_turbo", "split_files/text_encoders/qwen_3_4b.safetensors",             "text_encoders"),
    ("Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors",                              "vae"),
]


def remote_size(repo, path):
    """从 ModelScope API 拿远端文件大小（用于校验）。"""
    d = os.path.dirname(path)
    url = f"https://modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Root={d}"
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=40) as r:
        data = json.load(r)
    for f in (data.get("Data") or {}).get("Files", []):
        if f.get("Path") == path:
            return f.get("Size") or 0
    return 0


def human(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.2f}{u}"
        n /= 1024
    return f"{n:.2f}TB"


def fetch(item):
    repo, path, subdir = item
    name = os.path.basename(path)
    local = os.path.join(DEST, subdir, name)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    try:
        size = remote_size(repo, path)
    except Exception as e:
        return (name, 0, 0, f"API_ERR({e})")
    if os.path.exists(local) and size and os.path.getsize(local) == size:
        return (name, size, size, "skip")
    url = f"https://modelscope.cn/models/{repo}/resolve/master/{path}"
    tmp = local + ".part"
    for attempt in range(4):
        subprocess.run(["curl", "-sL", "--fail", "-A", UA, "-C", "-", "-o", tmp,
                        "--retry", "3", "--retry-delay", "3",
                        "--connect-timeout", "30", "--max-time", "7200", url])
        got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        if size and got == size:
            os.replace(tmp, local)
            return (name, size, got, "ok")
        if not size and got > 0:
            os.replace(tmp, local)
            return (name, 0, got, "ok(no-size)")
        time.sleep(3)
    got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    return (name, size, got, "FAIL")


def main():
    print("解析远端文件大小...", flush=True)
    total = 0
    for repo, path, _ in FILES:
        try:
            s = remote_size(repo, path)
        except Exception:
            s = 0
        total += s
        print(f"  {os.path.basename(path):46s} {human(s)}", flush=True)
    print(f"合计 {human(total)}", flush=True)

    t0 = time.time()
    done = [0]; got_total = [0]; fails = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for name, size, got, status in ex.map(fetch, FILES):
            done[0] += 1; got_total[0] += got
            el = time.time() - t0
            rate = got_total[0] / el if el > 0 else 0
            print(f"[{done[0]}/{len(FILES)}] {human(got_total[0])}/{human(total)}  "
                  f"{human(rate)}/s  {status:12s} {name}", flush=True)
            if status.startswith("FAIL") or status.startswith("API_ERR"):
                fails.append(name)
    print(f"DONE 用时 {time.time()-t0:.0f}s  fails={len(fails)}", flush=True)
    for f in fails:
        print("  FAILED:", f, flush=True)


if __name__ == "__main__":
    main()
