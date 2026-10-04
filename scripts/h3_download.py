#!/usr/bin/env python3
"""MiniMax-H3 FL2VA downloader for ModelScope (resumable, parallel)."""
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

MODEL = "MiniMax/MiniMax-H3"
REV = "master"
DEST = os.environ.get("H3_MODEL_DIR", os.path.join(os.environ.get("H3_MODELS_HOME", os.path.expanduser("~/minimax-h3-models")), "MiniMax-H3"))
API = f"https://modelscope.cn/api/v1/models/{MODEL}/repo/files?Revision={REV}"
RES = f"https://modelscope.cn/models/{MODEL}/resolve/{REV}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131 Safari/537.36"
WORKERS = 6

def api(root):
    url = f"{API}&Root={root}"
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=40) as r:
        d = json.load(r)
    return d.get("Data", {}).get("Files", [])

def walk(root=""):
    files, dirs = [], []
    for f in api(root):
        p, t = f.get("Path"), f.get("Type")
        if t == "tree":
            dirs.append(p)
        elif t == "blob":
            files.append((p, f.get("Size") or 0))
    for d in dirs:
        files.extend(walk(d))
    return files

def human(n):
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024: return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"

def fetch(item):
    path, size = item
    local = os.path.join(DEST, path)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    if os.path.exists(local) and os.path.getsize(local) == size:
        return (path, size, size, "skip")
    url = f"{RES}/{path}"
    tmp = local + ".part"
    for attempt in range(4):
        cmd = ["curl", "-sL", "--fail", "-A", UA, "-C", "-", "-o", tmp,
               "--retry", "3", "--retry-delay", "3", "--connect-timeout", "30",
               "--max-time", "7200", url]
        r = subprocess.run(cmd)
        got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        if got == size:
            os.replace(tmp, local)
            return (path, size, got, "ok")
        if r.returncode == 0 and got >= size:
            os.replace(tmp, local)
            return (path, size, got, "ok")
        time.sleep(3)
    got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    return (path, size, got, "FAIL")

def main():
    print("Fetching manifest from ModelScope...", flush=True)
    root_files = [(p, s) for p, s in walk("") if p in ("model_index.json", "LICENSE", "README.md")]
    fl2va = walk("FL2VA")
    manifest = root_files + fl2va
    total = sum(s for _, s in manifest)
    print(f"Manifest: {len(manifest)} files, {human(total)} total", flush=True)
    with open(os.path.join(os.environ.get("H3_ROOT", "."), "logs", "h3_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)

    done = [0]; bytes_done = [0]; t0 = time.time(); fails = []
    big = sorted(manifest, key=lambda x: -x[1])
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for path, size, got, status in ex.map(fetch, big):
            done[0] += 1; bytes_done[0] += got
            if status == "FAIL": fails.append(path)
            el = time.time() - t0
            rate = bytes_done[0] / el if el > 0 else 0
            pct = 100.0 * bytes_done[0] / total
            eta = (total - bytes_done[0]) / rate if rate > 0 else 0
            print(f"[{done[0]}/{len(big)}] {pct:5.1f}%  {human(bytes_done[0])}/{human(total)}  "
                  f"{human(rate)}/s  ETA {eta/60:.0f}min  {status:4s} {path}", flush=True)
    print(f"DONE bytes={human(bytes_done[0])} fails={len(fails)}", flush=True)
    for f in fails: print("  FAILED:", f, flush=True)

if __name__ == "__main__":
    main()
