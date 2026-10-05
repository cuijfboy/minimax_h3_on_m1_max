# h3.c-studio 补丁说明

上游：https://github.com/skaiy/h3.c-studio

本仓库**不包含** Studio 的代码，需要自行 clone 上游。

下面这一处补丁由 [`scripts/patch_studio_ssd.py`](../scripts/patch_studio_ssd.py) 负责打上，
`./deploy.sh --stage studio` 会自动调用（幂等，重复执行不会重复插入）。
文末保留了手工做法，供排查问题时对照。

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

## 本补丁现在会被自动应用

`./deploy.sh --stage studio` 一步做完 Studio 的全部准备（全部幂等）：

1. **clone** 上游（若缺失）
2. **编译引擎** —— 上游仓库不含 `h3` 二进制，脚本执行 `make`
3. **打本补丁** —— 调用 `scripts/patch_studio_ssd.py`
4. **前端依赖** —— `npm install`
5. **后端依赖** —— 创建 `studio/server/.venv` 并安装
   `fastapi` / `uvicorn[standard]` / `pydantic` / `python-multipart`
   （早期版本漏掉这一步，会导致 `./cli/h3studio` 直接报环境缺失）

模型与输出目录的软链由 `./h3-models bind` 负责（`--stage workflows` 会调用）：

~~~bash
h3.c-studio/MiniMax-H3        -> 权重仓库的 MiniMax-H3
h3.c-studio/MiniMax-H3-turbo  -> 权重仓库的 MiniMax-H3-turbo
h3.c-studio/outputs           -> h3.c/outputs
~~~
