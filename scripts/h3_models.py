#!/usr/bin/env python3
"""模型解析、校验与绑定。

模型仓库与部署目录分离：仓库里放着 165 GiB 权重，部署目录只有代码。
本模块负责把两者接起来，并把结果告诉 h3.c 引擎和 ComfyUI。

    python3 scripts/h3_models.py status     # 解析 + 校验 + 绑定状态
    python3 scripts/h3_models.py verify     # 只校验
    python3 scripts/h3_models.py bind       # 重建绑定
    python3 scripts/h3_models.py paths      # 只打印解析出的路径（给 shell 用）
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "config" / "models.manifest.json"

H3_ROOT = Path(os.environ.get("H3_ROOT", Path.home() / "minimax-h3"))
H3_MODELS_HOME = Path(os.environ.get("H3_MODELS_HOME", Path.home() / "minimax-h3-models"))
BINDING = os.environ.get("MODEL_BINDING", "auto")

# ComfyUI 侧的四个模型子目录
COMFY_SUBDIRS = ["diffusion_models", "text_encoders", "vae", "upscale_models"]


def search_roots():
    raw = os.environ.get("MODEL_SEARCH_PATHS", "")
    return [Path(p).expanduser() for p in raw.split(":") if p.strip()]


def human(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def find_dir(name, roots, maxdepth=4):
    """在 roots 下按名字找目录，先看直接子目录，再逐层 glob。"""
    for root in roots:
        if not root.is_dir():
            continue
        direct = root / name
        if direct.is_dir():
            return direct
        for depth in range(1, maxdepth + 1):
            hits = sorted(root.glob("/".join(["*"] * depth) + "/" + name))
            if hits:
                return hits[0]
    return None


def resolve(name, explicit_var):
    """解析一个模型目录。返回 (路径 或 None, 来源说明)。"""
    explicit = os.environ.get(explicit_var, "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        return (p, "配置指定") if p.is_dir() else (None, f"配置指定但不存在: {p}")

    found = find_dir(name, search_roots())
    if found:
        return found, "搜索找到"

    candidate = H3_MODELS_HOME / name
    if candidate.is_dir():
        return candidate, "模型仓库"

    return None, "未找到"


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def spec_files(m, name):
    """取某个模型的逐文件清单；支持 same_layout_as 引用。"""
    spec = m.get(name, {})
    if spec.get("files"):
        return spec["files"]
    ref = spec.get("same_layout_as")
    if ref:
        return m.get(ref, {}).get("files", [])
    return []


def verify_dir(path, spec, files=None):
    """按清单校验目录。返回 (匹配数, 总数, 问题列表)。"""
    files = files if files is not None else spec.get("files")
    if not files:
        return (0, 0, [("(清单只有总大小，未逐文件校验)", "")])
    problems = []
    for rel, size in files:
        f = path / rel
        if not f.exists():
            problems.append((rel, "缺失"))
        elif f.stat().st_size != size:
            problems.append((rel, f"大小 {f.stat().st_size} != {size}"))
    return len(files) - len(problems), len(files), problems


def verify_files(path, spec):
    """校验一组散放的文件（ComfyUI 侧）。"""
    problems = []
    for e in spec["entries"]:
        f = path / e["path"]
        if not f.exists():
            problems.append((e["path"], "缺失"))
        elif f.stat().st_size != e["bytes"]:
            problems.append((e["path"], f"大小 {f.stat().st_size} != {e['bytes']}"))
    total = len(spec["entries"])
    return total - len(problems), total, problems


# ---------------------------------------------------------------- 绑定


def bind_h3_config(turbo_dir, model_dir):
    """写 h3.c 节点的 config.json。"""
    node = H3_ROOT / "ComfyUI" / "custom_nodes" / "wild-h3c-comfyui"
    if not node.is_dir():
        return False, f"节点目录不存在: {node}"
    (node / "config.json").write_text(
        json.dumps({"h3_binary": str(H3_ROOT / "h3.c" / "h3"),
                    "model_dir": str(turbo_dir or model_dir)}, indent=2) + "\n",
        encoding="utf-8")
    return True, str(node / "config.json")


def bind_h3_link(turbo_dir, model_dir):
    """在 H3_ROOT/models/ 下建符号链接，让标准布局自洽。"""
    link_root = H3_ROOT / "models"
    link_root.mkdir(parents=True, exist_ok=True)
    made = []
    for name, target in (("MiniMax-H3", model_dir), ("MiniMax-H3-turbo", turbo_dir)):
        if not target:
            continue
        link = link_root / name
        if link.is_symlink():
            if link.resolve() == Path(target).resolve():
                made.append((str(link), "已存在"))
                continue
            link.unlink()
        elif link.exists():
            made.append((str(link), "已存在实体目录，跳过"))
            continue
        link.symlink_to(target)
        made.append((str(link), "已创建"))
    return True, made


def bind_comfy_yaml(comfy_dir):
    """写 ComfyUI 的 extra_model_paths.yaml。"""
    cfg = H3_ROOT / "ComfyUI" / "extra_model_paths.yaml"
    if not (H3_ROOT / "ComfyUI").is_dir():
        return False, "ComfyUI 目录不存在"
    lines = ["# 由 scripts/h3_models.py 生成，请勿手工编辑",
             "h3_shared:",
             f"    base_path: {comfy_dir}"]
    for d in COMFY_SUBDIRS:
        lines.append(f"    {d}: {d}/")
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, str(cfg)


def bind_comfy_link(comfy_dir):
    """把 ComfyUI 的模型子目录换成指向仓库的符号链接。"""
    target_root = H3_ROOT / "ComfyUI" / "models"
    if not target_root.is_dir():
        return False, "ComfyUI/models 不存在"
    made = []
    for d in COMFY_SUBDIRS:
        src = comfy_dir / d
        if not src.is_dir():
            continue
        link = target_root / d
        if link.is_symlink():
            made.append((str(link), "已存在"))
            continue
        if link.is_dir() and any(link.iterdir()):
            made.append((str(link), "已有文件，跳过（避免覆盖）"))
            continue
        if link.is_dir():
            link.rmdir()
        link.symlink_to(src)
        made.append((str(link), "已创建"))
    return True, made


def do_bind(model_dir, turbo_dir, comfy_dir):
    report = []
    if BINDING in ("auto", "link") and turbo_dir:
        report.append(("h3  链接", *bind_h3_link(turbo_dir, model_dir)))
    if BINDING in ("auto", "config") and turbo_dir:
        report.append(("h3  配置", *bind_h3_config(turbo_dir, model_dir)))
    if comfy_dir:
        if BINDING == "link":
            report.append(("CF  链接", *bind_comfy_link(comfy_dir)))
        else:
            report.append(("CF  配置", *bind_comfy_yaml(comfy_dir)))
    return report


# ---------------------------------------------------------------- 命令


def gather():
    """解析所有模型位置。"""
    m = manifest()
    model_dir, src_model = resolve("MiniMax-H3", "H3_MODEL_DIR")
    turbo_dir, src_turbo = resolve("MiniMax-H3-turbo", "H3_TURBO_DIR")

    explicit_comfy = os.environ.get("COMFY_MODELS_DIR", "").strip()
    comfy_dir, src_comfy = None, "未找到"
    if explicit_comfy and Path(explicit_comfy).expanduser().is_dir():
        comfy_dir, src_comfy = Path(explicit_comfy).expanduser(), "配置指定"
    else:
        for root in [H3_MODELS_HOME / "comfy", *[r / "comfy" for r in search_roots()],
                     H3_ROOT / "ComfyUI" / "models"]:
            if (root / "diffusion_models").is_dir() or (root / "text_encoders").is_dir():
                comfy_dir, src_comfy = root, "搜索找到"
                break
    return m, (model_dir, src_model), (turbo_dir, src_turbo), (comfy_dir, src_comfy)


def cmd_status():
    m, (model_dir, s1), (turbo_dir, s2), (comfy_dir, s3) = gather()
    print(f"模型仓库  {H3_MODELS_HOME}")
    print("-" * 58)
    for label, path, src in (("MiniMax-H3", model_dir, s1),
                             ("MiniMax-H3-turbo", turbo_dir, s2)):
        if not path:
            print(f"{label:24s} {'':>12s}  ❌ {src}")
            continue
        files = spec_files(m, label)
        ok, tot, probs = verify_dir(path, m.get(label, {}), files) if files else (0, 0, [])
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        mark = "✅" if not probs else "❌"
        detail = f"{ok}/{tot} 文件匹配" if tot else "未逐文件校验"
        print(f"{label:24s} {human(size):>12s}  {mark} {detail}   ({src})")
        print(f"{'':24s} {'':>12s}     {path}")
        for rel, why in probs[:3]:
            print(f"{'':24s} {'':>12s}     · {rel}: {why}")

    print()
    if comfy_dir:
        ok, tot, probs = verify_files(comfy_dir, m["comfy"])
        mark = "✅" if not probs else "❌"
        print(f"{'comfy 模型':24s} {'':>12s}  {mark} {ok}/{tot}   ({s3})")
        print(f"{'':24s} {'':>12s}     {comfy_dir}")
        for rel, why in probs:
            print(f"{'':24s} {'':>12s}     · {rel}: {why}")
    else:
        print(f"{'comfy 模型':24s} {'':>12s}  ❌ {s3}")

    print()
    print("绑定状态")
    print("-" * 58)
    node_cfg = H3_ROOT / "ComfyUI/custom_nodes/wild-h3c-comfyui/config.json"
    if node_cfg.is_file():
        cur = json.loads(node_cfg.read_text()).get("model_dir")
        want = str(turbo_dir or model_dir or "")
        print(f"h3  配置   节点 config.json                      "
              f"{'✅ 一致' if cur == want else '⚠️  不一致'}")
    else:
        print("h3  配置   节点 config.json                      ❌ 未生成")

    for name in ("MiniMax-H3", "MiniMax-H3-turbo"):
        link = H3_ROOT / "models" / name
        if link.is_symlink():
            state = "✅" if link.exists() else "❌ 悬空"
            print(f"h3  链接   models/{name:24s} {state} → {os.readlink(link)}")
        else:
            print(f"h3  链接   models/{name:24s} （未创建）")

    yml = H3_ROOT / "ComfyUI/extra_model_paths.yaml"
    print(f"CF  配置   extra_model_paths.yaml                 "
          f"{'✅ 存在' if yml.is_file() else '（未创建）'}")
    return 0


def cmd_verify():
    m, (model_dir, _), (turbo_dir, _), (comfy_dir, _) = gather()
    bad = 0
    for label, path in (("MiniMax-H3", model_dir), ("MiniMax-H3-turbo", turbo_dir)):
        if not path:
            print(f"❌ {label}: 未找到"); bad += 1; continue
        files = spec_files(m, label)
        if not files:
            print(f"⚠️  {label}: 清单无逐文件信息，跳过"); continue
        ok, tot, probs = verify_dir(path, m.get(label, {}), files)
        print(f"{'✅' if not probs else '❌'} {label}: {ok}/{tot} 文件匹配  {path}")
        for rel, why in probs[:10]:
            print(f"     · {rel}: {why}")
        bad += bool(probs)
    if comfy_dir:
        ok, tot, probs = verify_files(comfy_dir, m["comfy"])
        print(f"{'✅' if not probs else '❌'} comfy: {ok}/{tot} 文件匹配  {comfy_dir}")
        for rel, why in probs:
            print(f"     · {rel}: {why}")
        bad += bool(probs)
    else:
        print("❌ comfy: 未找到"); bad += 1
    return 1 if bad else 0


def cmd_bind():
    _, (model_dir, _), (turbo_dir, _), (comfy_dir, _) = gather()
    for label, ok, detail in do_bind(model_dir, turbo_dir, comfy_dir):
        print(f"{'✅' if ok else '❌'} {label}: {detail}")
    return 0


def cmd_paths():
    _, (model_dir, _), (turbo_dir, _), (comfy_dir, _) = gather()
    print(f"H3_MODEL_DIR={model_dir or ''}")
    print(f"H3_TURBO_DIR={turbo_dir or ''}")
    print(f"COMFY_MODELS_DIR={comfy_dir or ''}")
    return 0 if all((model_dir, turbo_dir, comfy_dir)) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "verify", "bind", "paths"])
    a = ap.parse_args()
    return {"status": cmd_status, "verify": cmd_verify,
            "bind": cmd_bind, "paths": cmd_paths}[a.command]()


if __name__ == "__main__":
    sys.exit(main())
