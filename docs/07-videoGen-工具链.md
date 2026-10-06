# 07 · videoGen 工具链（清空重建部署记录）

> 本文记录 `/Users/jeffrey/temp/videoGen` 这套 MiniMax H3 视频生成工具链的
> **容器布局、构建方式、模型策略、本地补丁与运维命令**。
> 本次为**清空重建**：容器内只保留 `models/`，其余全部从服务器重新克隆并构建。

---

## 1. 一句话上手

```bash
cd /Users/jeffrey/temp/videoGen/minimax_h3_on_m1_max

./cli/h3gen "一只红狐狸走过雪地" draft   # 本地生成（864×480，约 23 分钟，免费）
./cli/start-comfyui                       # ComfyUI  → http://127.0.0.1:8188
./cli/h3studio                            # 分镜板   → http://127.0.0.1:3000
./h3-models status                        # 模型与绑定状态
```

CLI 会自动读取 `videoGen/h3.conf`（经仓库内软链），**不需要**手动 export `H3_ROOT`。

---

## 2. 容器布局

```
/Users/jeffrey/temp/videoGen/            ← 纯容器：两个目录 + 一个配置文件
├── h3.conf                              唯一配置文件（H3_ROOT / 模型路径 / 行为开关）
├── models/                              ← 唯一权重仓库（H3_MODELS_HOME），300 GB
│   ├── MiniMax-H3/                      原始权重 FL2VA（84 文件，含 LICENSE/README/model_index.json）
│   ├── MiniMax-H3-turbo/                LoRA 折叠权重（APFS 写时复制）
│   ├── loras/                           minimax_h3_turbo_v4_step600_ema.safetensors
│   └── comfy/                           ComfyUI 侧
│       ├── diffusion_models/            z_image_bf16 / z_image_turbo_bf16
│       ├── text_encoders/               qwen_3_4b.safetensors
│       ├── vae/                         ae.safetensors
│       └── upscale_models/              RealESRGAN_x4plus.pth
└── minimax_h3_on_m1_max/                ← 工具链根（H3_ROOT）+ 唯一 git 工作树
    ├── .git/                            工具链仓库 e938ae6
    ├── h3.conf -> ../h3.conf            软链：让按 $REPO/h3.conf 查找的工具零改动可用
    ├── cli/ scripts/ config/ workflows/ docs/ patches/ benchmarks/
    ├── deploy.sh   h3-models
    ├── ComfyUI/                         上游 clone + .venv + custom_nodes + extra_model_paths.yaml
    ├── h3.c/                            上游 clone + 已编译 h3 + h3_shaders.metal + outputs/
    ├── h3.c-studio/                     上游 clone + node_modules + server/.venv
    ├── models/                          → 软链到 ../../models/*（h3-models bind 生成）
    ├── bin/                             ffmpeg / ffprobe（软链到 Homebrew）
    └── logs/                            运行日志与冒烟产物
```

### 为什么还需要 `minimax_h3_on_m1_max/h3.conf` 和 `models/` 两条软链

| 软链 | 原因 |
|---|---|
| `h3.conf -> ../h3.conf` | `deploy.sh` / `h3-models` 写死读 `$REPO/h3.conf`；配置实体放容器根，靠这条链零补丁打通 |
| `models/{MiniMax-H3,MiniMax-H3-turbo}` | 仓库自身的"模型与代码分离"约定：`h3-models bind` 在 `H3_ROOT/models/` 建链接指向真实权重仓库，`cli/h3gen` 按 `$ROOT/models/...` 取模型 |

---

## 3. 版本锁定（本次全部为全新 clone）

| 组件 | 上游 | 锁定 commit |
|---|---|---|
| 工具链骨架 | `cuijfboy/minimax_h3_on_m1_max` | `e938ae6` |
| ComfyUI | `comfyanonymous/ComfyUI` | `4266410` (2026-10-03) |
| H3 引擎 | `antirez/h3.c` | `8974cc0` |
| 分镜板 | `skaiy/h3.c-studio` | `3129440` |
| ComfyUI 节点 | `skaiy/wild-h3c-comfyui` | `e08057d` |

---

## 4. 模型策略

`h3.conf` 关键项：

```bash
H3_ROOT="/Users/jeffrey/temp/videoGen/minimax_h3_on_m1_max"
H3_MODELS_HOME="/Users/jeffrey/temp/videoGen/models"
H3_MODEL_DIR="/Users/jeffrey/temp/videoGen/models/MiniMax-H3"
H3_TURBO_DIR="/Users/jeffrey/temp/videoGen/models/MiniMax-H3-turbo"
COMFY_MODELS_DIR="/Users/jeffrey/temp/videoGen/models/comfy"
MODEL_BINDING="auto"          # h3 侧 config.json + 软链；ComfyUI 侧 extra_model_paths.yaml
AUTO_DOWNLOAD_MODELS="0"      # 永不下载
VERIFY_MODELS="1"
```

### `models/` 里什么算"模型文件"

`models/` 共 178 个文件，除权重外还有大量 `.json`/`.py`/`.txt`，它们**都是模型的一部分**：

| 类别 | 数量 | 说明 |
|---|---|---|
| 权重 | 63 `.safetensors` + 1 `.pth` | transformer / video_vae / audio_vae 分片、z-image、qwen、ae、RealESRGAN |
| 模型定义 | 48 `.py` + 50 `.json` + 6 `.txt` + 2 `.yaml` | diffusers 布局：`FL2VA/tokenizer/tokenizer.json`、`FL2VA/transformer/config.json`、`processor/vocab.json`、`audio_vae/dac_*.py`… 引擎实际要读 |
| 随权重发布的文档 | 2 `LICENSE` + 2 `README.md` | 被 `config/models.manifest.json` 收录，删除会导致 `h3-models verify` 报缺失 |

> 因此除 macOS 的 `.DS_Store` 外，`models/` 中不应再删除任何文件。
> 校验：`./h3-models verify`；绑定：`./h3-models bind`。
> ⚠️ ComfyUI 侧**不要**同时用 yaml 和 `ComfyUI/models/` 下的软链，否则下拉框会出现两次；本方案统一用 yaml。

---

## 5. 本地补丁清单

### 5.1 32GB 内存必需：SSD 流式（两处）

DiT 满驻留需 37–45 GiB，而 Metal 单缓冲上限 18.7 GiB，**不加 `--ssd-streaming` 必然 OOM**。

1. `h3.c-studio/studio/server/main.py`（源码 6 行，上游没有）：
   ```python
   if os.environ.get("H3_SSD_STREAMING", "1") != "0":
       cmd.append("--ssd-streaming")
   ```
2. `ComfyUI/custom_nodes/wild-h3c-comfyui/nodes.py`：`ssd_streaming` 默认值 `False → True`
   （由 `deploy.sh --stage nodes` 自动打）

### 5.2 CLI / 脚本根目录自解析

```bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$REPO_ROOT/h3.conf" ]; then . "$REPO_ROOT/h3.conf"; fi
ROOT="${H3_ROOT:-$REPO_ROOT}"
```

落在 `cli/h3gen`、`cli/h3studio`、`cli/start-comfyui`；`scripts/comfy_lib.py` 有同款 Python 实现（供 `cli/comfy-2k` / `cli/comfy-contextir`）。

### 5.3 曾经的手工补做项 —— 现已全部自动化

这 6 项在早期部署里都是缺口（首次搭建时全靠手工完成），现已并入部署流程：

| # | 事项 | 现在由谁负责 |
|---|---|---|
| 1 | `cd h3.c-studio && make`（上游不含 `h3` 二进制） | `deploy.sh --stage studio` |
| 2 | Studio 后端 venv（fastapi / uvicorn / pydantic / python-multipart） | `deploy.sh --stage studio` |
| 3 | Studio 的 `--ssd-streaming` 补丁（见 5.1） | `scripts/patch_studio_ssd.py`，由 `--stage studio` 调用（幂等） |
| 4 | CLI 根目录自解析（见 5.2） | 已在源码中修复 |
| 5 | `h3.c-studio/{MiniMax-H3,MiniMax-H3-turbo,outputs}` 软链 | `./h3-models bind`（`--stage workflows` 调用） |
| 6 | `bin/{ffmpeg,ffprobe}` 软链 | `deploy.sh --stage deps` |

**端到端验证**：删掉 `h3.c-studio/h3`、`studio/server/.venv`、`bin/ffprobe`、
`h3.c-studio/MiniMax-H3-turbo` 后执行 `./deploy.sh --stage deps,studio,workflows`，
四项全部自动重建，服务恢复正常。

---

## 6. 常用命令

```bash
# 生成视频（免费本地）
./cli/h3gen "提示词" smoke      # 512×512  22 帧   约 2.5 分钟
./cli/h3gen "提示词" draft      # 864×480  124 帧  约 23 分钟
./cli/h3gen "提示词" quality    # 1344×768 124 帧  约 92 分钟
./cli/h3gen "提示词" base20     # 原始权重 20 步

# 服务
./cli/start-comfyui             # ComfyUI      :8188
./cli/h3studio                  # Studio 前端  :3000 / 后端 :8765

# 官方 API 工具（需 .comfy_api_key，按官方计费）
./cli/comfy-contextir "中文想法" > prompt.txt
./cli/comfy-2k 视频.mp4 "$(cat prompt.txt)"

# 模型
./h3-models status | verify | bind | paths
```

---

## 7. 端口

| 服务 | 端口 | 启动方式 |
|---|---|---|
| ComfyUI | 8188 | `./cli/start-comfyui` |
| H3 Studio 前端 (vite) | 3000 | `./cli/h3studio` |
| H3 Studio 后端 (FastAPI) | 8765 | 由 `cli/h3studio` 连带启动 |

> 旧部署 `/Users/jeffrey/temp/comfyui` 的服务已停止；其模型路径仍通过反向软链指向 `videoGen/models`。

### 7.1 服务生命周期（实测踩过的坑）

**服务不会自动随开机或会话启动**，进程消失后要手动拉起来：

```bash
cd /Users/jeffrey/temp/videoGen/minimax_h3_on_m1_max
./cli/start-comfyui     # 前台运行，Ctrl+C 停止
./cli/h3studio          # 同上，同时拉起前端与后端
```

想让它脱离终端长期运行：

```bash
nohup ./cli/start-comfyui > logs/comfyui.log 2>&1 &
nohup ./cli/h3studio      > logs/studio.log  2>&1 &
```

一键体检：

```bash
for p in 8188 3000 8765; do
  lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null && echo "$p OK" || echo "$p 需要重启"
done
```

**注意 `cli/h3studio` 走的是 `npm run dev`（`scripts/dev.js`）**：它同时拉起
vite(:3000) 与 uvicorn(:8765)，并且**子进程被杀后父进程会重新拉起**
（实测：只杀 vite，父进程会在 :3001 上重生一个，形成幽灵服务）。
要真正停掉 Studio，停父进程：

```bash
pkill -f "scripts/dev.js"
```

日志位置：`logs/comfyui.log`、`logs/studio.log`；出图记录在 `ComfyUI/output/`。
本机这两个服务目前以**脱离会话**方式运行（PPID=1），关掉终端不影响它们。

---

## 8. 验证记录（2026-10-05 清空重建后实测）

### 8.1 模型

| 项 | 结果 |
|---|---|
| MiniMax-H3 | ✅ 84/84 · 134.2 GiB |
| MiniMax-H3-turbo | ✅ 84/84 · 134.2 GiB |
| comfy（z-image ×2 / qwen / ae / esrgan） | ✅ 5/5 |
| `.DS_Store` 清理 | 4 个已删，此后 models 全程未再变动 |

### 8.2 冒烟测试

```bash
./cli/h3gen "A red fox walks through fresh snow in a pine forest. …" smoke
```

**146 秒**（11:15:39 → 11:18:05），产物 `h3.c/outputs/h3-smoke-20261005-111539.mp4`：
h264 512×512 @24fps + AAC 32 kHz 立体声，0.925 s，270,182 字节。
抽帧目视：红狐行走于雪地松林，与提示词一致。

### 8.3 服务

| 检查 | 结果 |
|---|---|
| ComfyUI `:8188/system_stats` | 200 · ComfyUI 0.38.0 |
| Studio `:3000` / `:8765/docs` | 200 / 200 |
| 进程 cwd | 三个进程全部位于 `minimax_h3_on_m1_max/…` |
| 模型下拉去重 | diffusion_models 2 / text_encoders 1 / vae 1 / upscale_models 1 —— 各一次 |

### 8.4 容器终态

```
$ ls -A /Users/jeffrey/temp/videoGen
h3.conf
minimax_h3_on_m1_max
models
```

---

## 9. 重建与回滚

整套工具链**可从服务器完整重建**（模型权重不受影响）：

```bash
cd /Users/jeffrey/temp/videoGen
mv minimax_h3_on_m1_max /tmp/old-toolchain            # 或直接删除
git clone https://github.com/cuijfboy/minimax_h3_on_m1_max.git minimax_h3_on_m1_max
# 再按本文第 3 节锁定 SHA 克隆 ComfyUI / h3.c / h3.c-studio / wild-h3c-comfyui
# 然后补 5.1–5.3 的补丁，最后 ./deploy.sh --stage models,fold,nodes,workflows
```

> `models/` 自始至终未参与重建；`h3.conf` 可沿用。
> 本次清空重建前的文档、基线快照与冒烟产物备份在
> `/Users/jeffrey/temp/videogen-backup-20261005-111239/`。

---

## 10. 性能参考（上游 README 实测，M1 Max 32GB）

| 档位 | 分辨率 | 帧数 | 耗时 |
|---|---|---|---|
| smoke | 512×512 | 22 | 146 s（本次实测） |
| draft | 864×480 | 124 (5.17s) | 约 23 分钟 |
| quality | 1344×768 | 124 | 约 92 分钟 |
| 三镜串联 | 864×480 | 440 (18.33s) | 约 91 分钟 |

约 **12 秒/帧**（480p）。批量不省时间。
