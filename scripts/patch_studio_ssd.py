#!/usr/bin/env python3
"""给 h3.c-studio 打上 32GB 机器必需的 --ssd-streaming 补丁（幂等）。

    python3 scripts/patch_studio_ssd.py <h3.c-studio>/studio/server/main.py

背景：DiT 全驻留需 37-45 GiB，而 M1 Max 32GB 的 Metal 单缓冲上限只有 18.7 GiB，
不加 --ssd-streaming 必然分配失败。Studio 跑的是它自己的引擎副本
（H3_ENGINE_DIR 指向 h3.c-studio/），不受 wild-h3c-comfyui 那处补丁影响，
所以必须单独打。详见 patches/h3-c-studio.md。

退出码：0 = 已打上或本来就有；1 = 文件不存在或锚点找不到（上游改了结构）。
"""

import sys
from pathlib import Path

ANCHOR = '           "-o", str(OUTPUTS / out_name)]\n'
PATCH = ANCHOR + (
    '    # --- local patch (deploy.sh): 32GB 统一内存必须启用 SSD 流式 ----------\n'
    '    # Metal 单缓冲上限 18.7 GiB < DiT 满驻留 37-45 GiB，不加必然分配失败。\n'
    '    # 默认开启；H3_SSD_STREAMING=0 可关闭。\n'
    '    if os.environ.get("H3_SSD_STREAMING", "1") != "0":\n'
    '        cmd.append("--ssd-streaming")\n'
    '    # --- end local patch --------------------------------------------------\n'
)
MARKER = "H3_SSD_STREAMING"


def main(argv):
    if len(argv) != 2:
        print("用法: python3 scripts/patch_studio_ssd.py <main.py 路径>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.is_file():
        print(f"❌ 找不到 {path}", file=sys.stderr)
        return 1

    src = path.read_text(encoding="utf-8")
    if MARKER in src:
        print(f"✅ 补丁已存在，跳过：{path}")
        return 0
    if ANCHOR not in src:
        print(f"❌ 锚点未找到，上游可能已改结构：{path}", file=sys.stderr)
        print("   请参考 patches/h3-c-studio.md 手工插入", file=sys.stderr)
        return 1

    path.write_text(src.replace(ANCHOR, PATCH, 1), encoding="utf-8")
    print(f"✅ 已打上 --ssd-streaming 补丁：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
