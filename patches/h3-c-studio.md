# h3.c-studio 补丁说明

上游：https://github.com/skaiy/h3.c-studio

本仓库**不包含** Studio 的代码，需要自行 clone 上游。下面这一处补丁
`deploy.sh` **不会**自动打，必须单独处理。

---

## 补丁内容

**文件**：`studio/server/main.py`
**位置**：`job_command()` 里组装完 `-o` 输出参数之后

~~~diff
            "-o", str(OUTPUTS / out_name)]
+    # --- local patch: 32GB 统一内存必须启用 SSD 流式 ----------------------
+    # 本机 max Metal buffer 仅 18.7 GiB，而 DiT 满驻留需 37-45 GiB，
+    # 不开启 --ssd-streaming 必然分配失败。默认开启，H3_SSD_STREAMING=0 可关闭。
+    if os.environ.get("H3_SSD_STREAMING", "1") != "0":
+        cmd.append("--ssd-streaming")
+    # --- end local patch --------------------------------------------------
     if req.frames is not None:
         cmd += ["--frames", str(req.frames)]
~~~

---

## 为什么必须改

与 [`wild-h3c-comfyui.md`](wild-h3c-comfyui.md) 是同一个根因：DiT 全驻留需要
**37–45 GiB**，而 M1 Max 32GB 的 **Metal 单缓冲上限只有 18.7 GiB**。

Studio 跑的是它自己的引擎副本（`H3_ENGINE_DIR` 指向 `h3.c-studio/`，
用的是该目录下的 `h3` 二进制与 `h3_shaders.metal`），
**不受 ComfyUI 节点那处补丁的影响，必须单独打**。

不打的表现：在分镜板点"生成"→ 文本编码器加载完之后显存分配失败，
白等几分钟才报内存错误。

---

## 怎么打

~~~bash
cd "$H3_ROOT/h3.c-studio"
python3 - <<'PY'
from pathlib import Path

p = Path("studio/server/main.py")
s = p.read_text(encoding="utf-8")
anchor = '           "-o", str(OUTPUTS / out_name)]\n'
patch = anchor + (
    '    # --- local patch: 32GB 统一内存必须启用 SSD 流式 ----------------------\n'
    '    if os.environ.get("H3_SSD_STREAMING", "1") != "0":\n'
    '        cmd.append("--ssd-streaming")\n'
    '    # --- end local patch --------------------------------------------------\n'
)

if "H3_SSD_STREAMING" in s:
    print("补丁已存在，跳过")
elif anchor in s:
    p.write_text(s.replace(anchor, patch, 1), encoding="utf-8")
    print("补丁已应用")
else:
    raise SystemExit("锚点未找到 —— 上游可能已改结构，请手工插入")
PY
~~~

---

## 幂等与开关

- 脚本先检查 `H3_SSD_STREAMING` 是否已存在，重复执行不会重复插入。
- 需要临时关闭（例如换到 64GB+ 机器想跑满驻留）：`H3_SSD_STREAMING=0 ./cli/h3studio`。

---

## deploy.sh 覆盖不到的其他几件事

Studio 相关还有两件 `deploy.sh` 不管、必须手工做的事：

1. **编译引擎**：上游仓库不含 `h3` 二进制，需要 `cd h3.c-studio && make`。
2. **后端依赖**：`studio/server/.venv`（`fastapi` / `uvicorn[standard]` /
   `pydantic` / `python-multipart`）不会被自动创建，
   否则 `./cli/h3studio` 会直接报环境缺失。
