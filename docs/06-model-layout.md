# 模型解耦与共享

> 为什么模型不放在部署目录里，以及怎么在多个部署之间共享一份 177 GB 的权重。

---

## 1. 为什么要把模型独立出来

MiniMax H3 的权重有 **134 GiB**（折叠后另加 58 GiB），ComfyUI 侧的 Z-Image 还要 33 GiB。
把它们塞进部署目录会带来三个问题：

| 问题 | 后果 |
|---|---|
| 删部署 = 删模型 | 想重装一次 ComfyUI，得重新下 177 GB |
| 无法多版本共存 | 测试新版和稳定版要用两份模型 |
| 备份边界模糊 | 不知道哪些该备份 |

**所以本方案把它们分开：**

~~~
H3_MODELS_HOME  (~/minimax-h3-models)     ← 权重，177 GB，可放外置盘
└── ...

H3_ROOT  (~/minimax-h3)                   ← 代码，几百 MB，随时可删
└── ...
~~~

---

## 2. 模型仓库的目录结构

~~~
H3_MODELS_HOME/
├── MiniMax-H3/                134 GiB   原始权重（FL2VA）
│   └── FL2VA/
│       ├── transformer/       61.7 GiB  DiT
│       ├── text_encoder/      62.1 GiB  Qwen3-VL
│       ├── video_vae/          9.7 GiB
│       ├── audio_vae/          0.6 GiB
│       ├── processor/  tokenizer/
├── MiniMax-H3-turbo/          134 GiB   折叠后（APFS 写时复制，实际只多占 58 GiB）
├── loras/                     744 MiB   Turbo LoRA
└── comfy/                               ComfyUI 侧
    ├── diffusion_models/      z_image_turbo_bf16 / z_image_bf16
    ├── text_encoders/         qwen_3_4b
    ├── vae/                   ae.safetensors
    └── upscale_models/        RealESRGAN_x4plus.pth
~~~

> `MiniMax-H3-turbo` 是用 LoRA 折叠出来的等价权重（提速 1.71×）。
> 在 APFS 上由于写时复制，它只额外占 58 GiB 而不是完整的 134 GiB。

---

## 3. 模型是怎么被找到的

`scripts/h3_models.py` 按下面的优先级解析：

| 顺序 | 来源 | 说明 |
|---|---|---|
| 1 | `h3.conf` 里显式指定 | `H3_MODEL_DIR` / `H3_TURBO_DIR` / `COMFY_MODELS_DIR`，**校验通过才采用** |
| 2 | `MODEL_SEARCH_PATHS` 下按名字搜 | `find -maxdepth 4 -type d -name "MiniMax-H3-turbo"` |
| 3 | `H3_MODELS_HOME` | 默认位置（也是下载目标） |
| 4 | 都没有 | `AUTO_DOWNLOAD_MODELS=1` 则下载，否则报错并给指引 |

查看当前解析结果：

~~~bash
./h3-models status
~~~

~~~
模型仓库  /Users/me/minimax-h3-models
──────────────────────────────────────────────────
MiniMax-H3          134.2 GiB  ✅ 84/84 文件匹配   (配置指定)
MiniMax-H3-turbo    134.2 GiB  ✅ 84/84 文件匹配   (配置指定)
comfy 模型                     ✅ 5/5             (搜索找到)
~~~

---

## 4. 两种绑定方式

解析出路径之后，还要让 **h3.c 引擎**和 **ComfyUI** 知道去哪找。

### 4.1 h3.c 侧

h3.c 用命令行参数指定模型：`h3 -d MODEL_DIR`。
ComfyUI 节点把它封装在 `config.json` 的 `model_dir` 里。

~~~json
{
  "h3_binary": "/path/to/h3.c/h3",
  "model_dir": "/path/to/MiniMax-H3-turbo"
}
~~~

同时，`H3_ROOT/models/MiniMax-H3-turbo` 会建一个**符号链接**指向真实位置，
让标准布局保持自洽 —— 任何按常规路径找模型的工具都能直接用。

> **这两种方式是互补的**：链接断了 config 还在，config 丢了链接还在。
> 由 `MODEL_BINDING=auto` 默认同时启用。

### 4.2 ComfyUI 侧

ComfyUI 原生支持外部模型目录，通过 `extra_model_paths.yaml`：

~~~yaml
h3_shared:
    base_path: /path/to/comfy
    diffusion_models: diffusion_models/
    text_encoders: text_encoders/
    vae: vae/
    upscale_models: upscale_models/
~~~

由 `h3_models.py` 自动生成。

> ⚠️ **ComfyUI 侧不能两种方式同时用** —— `extra_model_paths.yaml` 和
> `ComfyUI/models/` 下的符号链接如果都指向同一批文件，
> 模型会在下拉框里**出现两次**。所以这里只能二选一，默认用 yaml。

---

## 5. 三种绑定模式

在 `h3.conf` 里设 `MODEL_BINDING`：

| 模式 | h3.c 侧 | ComfyUI 侧 | 适用场景 |
|---|---|---|---|
| **`auto`**（默认） | 符号链接 **+** config.json | `extra_model_paths.yaml` | 一般情况，h3 侧双保险 |
| `link` | 符号链接 | **子目录**符号链接 | 想让布局完全自洽、工具无关 |
| `config` | config.json | `extra_model_paths.yaml` | 模型在只读盘上，不能建链接 |

切换后重建绑定：

~~~bash
./h3-models bind
~~~

---

## 6. 常见用法

### 6.1 多个部署共享一份模型

~~~bash
# 正式部署
H3_ROOT=~/minimax-h3 ./deploy.sh

# 测试部署 —— 复用同一份模型，零下载
H3_ROOT=/tmp/h3-test \
H3_MODEL_DIR=~/minimax-h3-models/MiniMax-H3 \
H3_TURBO_DIR=~/minimax-h3-models/MiniMax-H3-turbo \
COMFY_MODELS_DIR=~/minimax-h3-models/comfy \
AUTO_DOWNLOAD_MODELS=0 ./deploy.sh
~~~

### 6.2 模型放在外置盘

~~~bash
H3_MODELS_HOME=/Volumes/SSD/minimax-h3-models ./deploy.sh
~~~

### 6.3 迁移已有模型

~~~bash
# 1. 移动（同盘用 mv，跨盘用 rsync）
rsync -a --progress ~/minimax-h3-models/ /Volumes/SSD/minimax-h3-models/

# 2. 更新配置
echo 'H3_MODELS_HOME="/Volumes/SSD/minimax-h3-models"' >> h3.conf

# 3. 重建绑定
./h3-models bind
./h3-models status      # 确认
~~~

### 6.4 校验完整性

~~~bash
./h3-models verify
~~~

对照 `config/models.manifest.json` 逐文件核对字节数（MiniMax-H3 有 84 个文件）。
大小不符通常意味着下载中断，重新下载即可。

---

## 7. 磁盘占用速查

| 项 | 体积 |
|---|---|
| MiniMax-H3（原始） | 134 GiB |
| MiniMax-H3-turbo（折叠） | +58 GiB（APFS 写时复制） |
| LoRA | 744 MiB |
| comfy/（Z-Image 相关） | 33 GiB |
| 部署目录（代码 + venv + node_modules） | 约 3 GiB |
| **合计** | **约 228 GiB** |

> `deploy.sh` 在下载前会检查磁盘，少于 250 GB 直接报错并给出建议。
