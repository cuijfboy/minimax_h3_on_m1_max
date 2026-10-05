# MiniMax H3 本地部署方案

> 📖 **只想用、不想看原理？** → 请直接看 [MiniMax-H3-使用手册.md](MiniMax-H3-使用手册.md)（493 行，含两个平台的具体操作步骤）
>
> **Apple M1 Max 32GB · macOS 27 · 个人学习 / 研究用途**
> 文档版本 **v3.0** —— 本版**全部结论已在本机实跑验证**，不再包含推算值
> 目标机器：`$H3_ROOT`

---

## 0. 结论速览（TL;DR）

### 0.1 实测结论（本机已跑通）

| 问题 | 实测结论 |
|---|---|
| **32GB 的 M1 Max 能跑 MiniMax H3 吗？** | ✅ **能，且体验可用**。480p / 5.17 秒 / 带立体声，**22 分 57 秒/条**，零 swap，峰值内存 11.17 GB |
| 用哪条路线？ | ✅ **h3.c（C + Metal）**。已实际部署并跑通三个基准；MLX 路线经查证在本机**不可行** |
| 关键技术是什么？ | `--ssd-streaming`：DiT 常驻从 32.8 GiB 降到 **3.25 GiB**，这是 32GB 能跑通的根本原因 |
| 文本编码器（50GB）怎么办？ | **无需处理**。h3.c 分阶段流式加载，实测峰值仅 **2.729 GiB** |
| Turbo 加速有效吗？ | ✅ **1.71× 总加速**（39:14 → 22:57），且是 50 层全质量，画质肉眼无差别 |
| 磁盘实际占用？ | 原始权重 **134 GB** + Turbo 折叠增量 **58 GB** = **192 GB**（可用 872 GB） |
| 下载走哪个源？ | **ModelScope 唯一可用**，实测 **34.4 MB/s**，134.2 GB 约 65 分钟下完，0 失败 |
| **ComfyUI 是最好的方案吗？** | ❌ **不是**。Apple Silicon 上只能走 PyTorch `mps`，是所有路线中最慢的。价值在生态，不在 H3 出片 |
| 最需要提前知道的？ | **许可证**：H3 采用 Community License，商用需付费授权；本方案按个人研究用途组织 |

### 0.2 本机实测性能总表

| 基准 | 配置 | 总耗时 | 峰值内存 | swap |
|---|---|---|---|---|
| **B1 冒烟** | 512×512 / 22帧(0.92s) / 20步 / 45层 / reuse2 | **3 分 49 秒** | 10.59 GB | 0 |
| **B2 平衡档** | 864×480 / 124帧(5.17s) / 20步 / 45层 / reuse2 | **39 分 14 秒** | 11.17 GB | 0 |
| **B3 草稿档** ⭐ | 864×480 / 124帧(5.17s) / **6步 Turbo** / **50层** | **22 分 57 秒** | 11.17 GB | 0 |
| **B4 成品档** 🏆 | **1344×768** / 124帧(5.17s) / **6步 Turbo** / **50层** | **1 小时 31 分 25 秒** | **12.71 GB** | **0** |
| **B5 768p 短测** | 1344×768 / 22帧(0.92s) / 6步 Turbo / 50层 | 8 分 34 秒 | 11.44 GB | 0 |

> **性能阶梯（全部零 swap）**：草稿 23 分钟 → 成品 91 分钟，约 **4×** 代价换 2.5× 像素量。
> **768p 不是内存瓶颈**：峰值仅比 480p 高 1.5 GB，因为 SSD 流式把 DiT 压在 5.73 GiB、视频 VAE 走分块。

---

## 1. 目标与范围

### 1.1 目标
在本机（Apple Silicon、32 GB 统一内存）上本地运行 **MiniMax H3**（开源权重、视频 + 原生立体声同步生成），产出可复现的部署、启动与调优流程。

### 1.2 本期范围
- ✅ MiniMax H3 **FL2VA**（文生视频 / 首帧 / 首尾帧）
- ✅ **多路线对比选型**（第 4 章），并按最优组合落地
- ✅ 国内镜像加速通道
- ✅ 基准测试与默认档位固化
- ⏸️ Ref2VA（参考图/视频/音频锁身份与声音）——后续按需追加
- ⏸️ 可选：MiniMax Music 3（本地音乐生成，14.3 GB，见 9.6）

### 1.3 非目标
- ❌ MiniMax-M2 / M1 / Text-01 文本大模型本地部署（230B / 456B MoE，32 GB 物理不可行）——建议走官方 API
- ❌ 2K 输出与 H3-Context-IR / H3-Regenerate-2K：**属托管服务，未开源**，本地上限 768p 短边
- ❌ 对外提供服务 / 商用交付

---

## 2. 本机环境核查（实测）

| 项目 | 实测值 | 评估 |
|---|---|---|
| 芯片 | Apple M1 Max（10 核 CPU / **32 核 GPU**） | 无矩阵单元，int8/fp8 原生 kernel 不可用 |
| 统一内存 | **32 GB** | ⚠️ 全案唯一硬约束 |
| 系统 | macOS 27.0.1（26A434），Metal 4 | ✅ 满足 Metal 4 / 4.1 编译要求 |
| 磁盘 | 1 TB SSD（APPLE SSD AP1024R），**可用 872 GB** | ✅ 充裕 |
| GPU 可接线内存上限 | `iogpu.wired_limit_mb = 0`（自动 ≈ 75%，即约 24 GB） | ⚠️ **26 GB 级峰值需手动上调**，见 9.4 |
| 构建工具 | CLT 27.0.0（xcodebuild / make / clang ✅） | ⚠️ **Metal 编译器缺失**，需补装 |
| Python | 仅系统 3.9.6 | 按需安装（ComfyUI 路线需要） |
| 其他 | Homebrew 7.0.7 ✅、git 2.54 ✅、node v24.21 ✅ | 无 ffmpeg / cmake / ninja / uv / git-lfs |

### 网络可达性（实测）

| 目标 | 结果 | 用途 |
|---|---|---|
| huggingface.co | ❌ HTTP 000 | 完全不可用 |
| hf-mirror.com | ⚠️ API/元数据 ✅；`resolve` 返回 308 + 0 字节 | **不能下载文件**，仅可查元数据 |
| modelscope.cn | ✅ HTTP 200，**实测 14.46 MB/s** | **模型下载主通道** |
| github.com | ✅ 200（个别仓库 000） | 代码 |
| gh-proxy.com / ghfast.top / ghproxy.net | ✅ 200 | GitHub 加速 |

---

## 3. 调研结论：MiniMax 开源权重全景

### 3.1 全景

| 模型 | 能力 | 规模 | 本机可行性 |
|---|---|---|---|
| **MiniMax H3**（Hailuo 3.0） | 视频 + **原生立体声**单次前向联合生成；768p / 24fps / ≤15s；文/图/视频/音频多模态上下文 | DiT **33.1B**（含 13B AdaLN 分支）+ **Qwen3-VL-32B** 文本编码器 + 视频 VAE + 音频 VAE | ⚠️ 可行但吃力 |
| **MiniMax Music 3** | 完整歌曲 ≤5 分钟，32kHz 立体声 | 8B + 0.6B LLM + 2.4B Flow + 123M VAE | ✅ 相对轻松（14.3 GB） |
| MiniMax-M2 / M1 / Text-01 | 文本 / 多模态 LLM | 230B / 456B MoE | ❌ 32 GB 不可行 |

### 3.2 H3 的能力边界

**能做**：一次前向同时产出画面 + 32 kHz 立体声（对白、音效、音乐同步），输出单个 MP4；多模态上下文（文/图/视频/音频参考可组合）；精确文字渲染；768 短边 / 24 fps / 最长约 15 秒。

**不能做**：2K 直出（需托管服务）；本地一键商用（见 3.4）；在 32 GB 上"随手就跑"。

### 3.3 权重矩阵（ModelScope 实测文件与体积）

#### A. Comfy-Org 转换 / 量化档（目录结构与 ComfyUI `models/` 一一对应）

**扩散模型** — `models/diffusion_models/`

| 文件 | 体积 | 评价 |
|---|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 20.97 GB | Comfy 路线推荐档 |
| `minimax_h3_fl2va_pruned_w6a8.safetensors` | 15.98 GB | 内存最紧时降级 |
| `minimax_h3_fl2va_pruned_fp8_scaled.safetensors` | 20.96 GB | 需 FP8 原生硬件，MPS 上是模拟，**不选** |
| `minimax_h3_fl2va_pruned_bf16.safetensors` | 40.23 GB | 质量档，32 GB 需重度流式 |
| `minimax_h3_fl2va_int8_convrot.safetensors` | 34.04 GB | 非 pruned，偏大 |
| `minimax_h3_fl2va_bf16.safetensors` | 66.28 GB | 满血，本机不可行 |

**文本编码器** — `models/text_encoders/`（Qwen3-VL-32B）

| 文件 | 体积 |
|---|---|
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 15.69 GB（Comfy 官方模板默认） |
| `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | 27.14 GB |
| `qwen3vl_32b_minimax_h3_bf16.safetensors` | 51.51 GB |

**VAE**：`minimax_h3_video_vae_fp16` 5.21 GB + `minimax_h3_audio_vae_fp32` 0.61 GB（`video_vae_int8_convrot` 2.81 GB 可替代）

**Turbo LoRA** — `models/loras/`

| 文件 | 体积 |
|---|---|
| `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` | 1.96 GB |
| `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | 1.96 GB |
| `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | 1.96 GB（Ref2VA 用） |

**Comfy 路线合计 ≈ 44.4 GB**

#### B. GGUF 量化档（`leejet/MiniMax-H3-GGUF`，供 stable-diffusion.cpp / ComfyUI-GGUF）

| 文件 | 体积 |
|---|---|
| `minimax_h3_fl2va_pruned-Q4_K_M.gguf` | **11.42 GB** |
| `minimax_h3_fl2va-Q4_K_M.gguf` | 18.78 GB |
| `qwen3vl_32b_minimax_h3-Q4_K_M.gguf` | **18.22 GB** |
| `qwen3vl_32b_minimax_h3-Q2_K_M.gguf` | 13.10 GB |

**sd.cpp 路线合计 ≈ 35.5 GB**（pruned Q4 DiT + Q4 文本编码器 + 两个 VAE）

#### C. 官方 BF16 分片（h3.c 引擎专用）

| 路径 | 体积 |
|---|---|
| `MiniMax/MiniMax-H3` → `FL2VA/` | **≈ 134 GB** |
| `MiniMax/MiniMax-H3` → `Ref2VA/` | ≈ 134 GB（本期不下） |

> ⚠️ **会导致白下 134 GB 的坑**：h3.c **必须**用官方 `MiniMaxAI/MiniMax-H3` 分片。Comfy-Org 重打包的单文件 safetensors 数据段偏移不是 8 字节对齐，在 h3.c 中会**静默解码成全屏花屏 / 黑屏（音频正常）**。两套权重必须分目录存放。

#### D. MLX 4-bit / 8-bit（mlx-serve 路线）

| 档位 | 下载 | 运行峰值 |
|---|---|---|
| 8-bit | 69 GB | 44 GB |
| **4-bit** | **40 GB** | **26 GB** ✅ 官方称适配 32 GB Mac |

### 3.4 许可证与合规（个人研究用途）

- MiniMax H3 权重适用 **MiniMax H3 Community License Agreement**，**不是开源许可证**。
- 截至 2026-08-26 版本，**美国、欧盟、英国、韩国为排除地区**，需单独授权。
- **商用生成内容需购买商业授权**，Comfy 是官方转售商；Comfy Cloud 生成的内容已含商用权利。
- 本方案定位**个人学习 / 研究用途**，不对外服务、不商用。下载前请复核 ModelScope 仓库内的 LICENSE。

---

## 4. 方案对比与选型：ComfyUI 是不是最优解？

### 4.1 直接回答

**不是。** 在这台机器上，ComfyUI 是「生态最强、速度最差」的一条路。

原因很具体：ComfyUI 在 Apple Silicon 上只能走 PyTorch 的 `mps` 后端，而 MPS 对这个负载既慢又占内存。H3 是一个 33B 的 DiT + 32B 文本编码器，PyTorch/MPS 会常驻远超模型所需的统一内存，且没有针对 Metal 的算子优化。

社区项目 h3c-studio 的作者把这件事总结得很准确：

> "Video diffusion on Apple Silicon is underserved. ComfyUI has no first-class MLX support, so it runs these models through PyTorch's `mps` backend — slow for this workload, and holding far more unified memory than the model needs. h3.c is a native Metal implementation for MiniMax-H3 with no PyTorch or MLX in the loop."
> —— janishar/h3c-studio

Comfy-Org 官方模型仓库的讨论区里也有一条标题直白的话题：**"Not supported for Apple silicon"**。H3 要能在 M 系芯片上跑，靠的是社区补丁（AppleSilicon-FP8、GGUF、SolAttn-MPS），而不是官方支持。

### 4.2 七条可用路线对比矩阵

| # | 路线 | 引擎 | 磁盘 | 运行峰值 | 相对速度 | 画质 | 界面 | 成熟度 |
|---|---|---|---|---|---|---|---|---|
| **1** | **h3.c + h3.c-studio** | C + Metal（原生） | 134 GB | ~2 GB DiT 常驻（SSD 流式） | ⭐⭐⭐⭐⭐ **最快** | **BF16 满血** | ⭐ 专用 Web UI（中英双语 / 进度 / 成片库 / 链式分镜） | 高（M1 Ultra、M4 Pro、M5 Air 均有实测） |
| 2 | h3.c（纯 CLI） | 同上 | 134 GB | 同上 | ⭐⭐⭐⭐⭐ | BF16 | 终端 | 高 |
| 3 | mlx-serve (MLX 4-bit) | MLX | **40 GB** | **26 GB** | ⭐⭐⭐ | 4-bit，略软 | ⭐ Web UI + iOS App；有**中文一键安装包** | 高（ddalcu 活跃迭代） |
| 4 | stable-diffusion.cpp (GGUF) | C++ / ggml + Metal | **35.5 GB** | ⭐ **最低**（`--offload-to-cpu`） | ⭐⭐ 待实测 | Q4_K_M | CLI | 中（2026-08-04 Day-1 支持） |
| 5 | h3.c + Wild H3C（ComfyUI 桥） | C + Metal | 134 GB | 同上 + ComfyUI 开销 | ⭐⭐⭐⭐ | BF16 | ComfyUI 节点 | 中 |
| 6 | **ComfyUI 原生（PyTorch/MPS）** | PyTorch MPS | 44 GB | ~24 GB | ⭐ **最慢**（32 GB 机器实测单条 20 步 **1 小时 32 分**） | INT8/NVFP4 | ⭐⭐⭐⭐⭐ **生态最强** | 依赖社区插件 |
| 7 | DiffSynth-Studio (MPS/NF4) | PyTorch MPS | ~40 GB | 未实测 | 未知 | NF4 | Python 脚本 | 低（个人整理） |

### 4.3 各路线的一句话点评

- **h3.c（路线 1/2）**：本机**唯一能称得上"可用"的速度**。M1 Ultra 上比 Swift/MLX 路线快 **2.15×**、省 **44%** 内存。缺点是要下 134 GB、且必须开 `--ssd-streaming`。
- **h3.c-studio（路线 1）**：为 h3.c 做的**专用 Web UI**（React + FastAPI / Go 两个实现），有提示词工作台、逐阶段进度、成片库、**链式分镜**（把上一段的末帧一键喂给下一段）。比"把 h3.c 塞进 ComfyUI"顺手得多。
- **MLX 4-bit（路线 3）**：**磁盘最省 + 唯一有中文一键包**的路线。官方明确说 4-bit 版"fits a 32 GB Mac"。代价是 4-bit 画质略软、速度约为 h3.c 的一半。
- **sd.cpp（路线 4）**：**磁盘第二省、内存最省**（支持 `--offload-to-cpu` 和 graph-cut 分块）。适合内存极度紧张时兜底，但 H3 支持刚落地，Mac 实测数据稀缺，**需要自己先跑基准**。
- **ComfyUI（路线 5/6）**：**只有在需要它的生态时才值得**——LoRA、Fun-ControlNet、Multiframe 多帧参考、以及大量非 H3 的图像/视频模型。单纯为了"生成 H3 视频"，它是最差选择。

### 4.4 推荐架构（v3.0 已按实测修正）

**原 v2.0 的"T0 MLX 快通层"已被实测否决**（见 13.6）。修正后的架构是**单主力 + 可选生态**：

~~~
┌─────────────────────────────────────────────────────────────┐
│  T1 主力层 ｜ h3.c Metal（唯一实用解）                        │
│  134 GB 原始权重 + 58 GB Turbo 折叠                          │
│  SSD 流式 · BF16 满血 · 零 swap · 峰值 11.17 GB              │
│  ✅ 实测：480p/5.17s = 22分57秒（Turbo 6步/50层全质量）        │
│  界面：h3.c-studio / h3c-studio（专用 Web UI）                │
└──────────────────────────┬──────────────────────────────────┘
                           │ 按需叠加
┌──────────────────────────▼──────────────────────────────────┐
│  T2 生态层 ｜ ComfyUI（可选，且因 API 额度而更有价值）          │
│  44 GB · PyTorch/MPS · 最慢但生态最全                         │
│  作用：① LoRA / Fun-ControlNet / 多帧参考 / 其他模型           │
│        ② 用已有 Comfy 额度跑 Context-IR 提示词增强             │
└─────────────────────────────────────────────────────────────┘

❌ T0 MLX 路线：文本编码器需 50.3 GB 常驻，32 GB 物理不可行
   兜底备选：stable-diffusion.cpp（GGUF 35.5 GB，内存最省）
~~~

### 4.5 什么情况下才该装 ComfyUI

| 场景 | 是否需要 ComfyUI |
|---|---|
| 只想生成 H3 视频（文生 / 图生 / 首尾帧） | ❌ 不需要，h3.c-studio 更好 |
| 想用 LoRA 调风格 / 角色 | ✅ 需要（h3.c 只能离线折叠 LoRA） |
| 想用 Fun-ControlNet 驱动或视频修补 | ✅ 需要（Comfy 独有） |
| 想在时间轴上锚定多个参考帧 | ✅ 需要（Multiframe Reference，Comfy 独有） |
| 还想跑 SDXL / Flux / Qwen-Image / Wan 等其他模型 | ✅ 需要 |
| **想用已购的 Comfy 额度做提示词增强（Context-IR）** | ✅ 需要（见 4.6） |
| 磁盘只剩不到 100 GB | ❌ 别装 |

### 4.6 用 ComfyUI 已购额度做提示词增强（不需要 MiniMax 官方 key）

ComfyUI 的额度是 **Comfy 账户体系**，与 MiniMax 官网 `api.minimax.io` **不通用**。但 ComfyUI 内置了对应节点：

**`MinimaxHailuo03ContextIRNode`** —— 官方描述：

> This node uses MiniMax H3 Context IR to analyze your text description and any attached media, then produces a stronger, structured video prompt. The returned prompt is designed to be connected to the prompt input of a MiniMax H3 video node.

| 输入 | 输出 |
|---|---|
| `prompt`（粗略描述）、`duration`(4–15)、`ratio`、可选首/尾帧、可选参考图/视频/音频 | **一个字符串**（结构化增强提示词） |

**推荐用法（省额度）**：只跑 Context-IR 节点（纯文本请求，消耗极小）→ 复制输出 → 喂给**本地 h3.c** 生成。重计算留在本地，额度只花在便宜的文本环节。

⚠️ **必须注意**：增强提示词会**按位置引用媒体**（`<Picture 1>`、`<Video 1>`）。若在节点里挂了参考图，本地生成时必须挂**同样的图、同样的顺序**，否则引用会对不上。

> 这与"文本编码器"是两件事：Context-IR 是 **text→text 的提示词改写**；文本编码器（Qwen3-VL-32B）是 **text→hidden states 的条件网络**，属于推理图的一部分，无法用任何 API 替代。详见 13.6。

### 4.7 本地 768P 是不是"最终质量"？—— 是，但相对官方完整链路是上游产物

这是部署前必须搞清楚的问题，官方文档给出了明确答案。

#### 官方明确：开源版**不含**两个环节

> The open release contains H3-Base FL2VA and Ref2VA. **It does not contain H3-Context-IR or H3-Regenerate-2K.** A self-hosted H3-Base service therefore does not reproduce the complete MiniMax Platform Context-IR and 2K workflow.
> —— MiniMax 官方自托管指南

| 环节 | 本地开源 | 官方服务 |
|---|---|---|
| H3-Base 生成（768P 短边） | ✅ | ✅ |
| **H3-Context-IR**（前置：上下文理解 → 结构化提示词） | ❌ | ✅ `POST /v2/h3_context_ir` |
| **H3-Regenerate-2K**（后置：768P → 2K 再生成） | ❌ | ✅ Video Regeneration API |

**结论**：本地 `1344×768` **就是开源权重的最终输出规格**（不是刻意降质的中间物，而是 H3-Base 的原生画布），但相对官方完整工作流，它确实处在 **2K 再生成的上游**。

#### 关键：官方 2K 再生成的输入规格 = 本地产出规格

官方 API 描述原文：

> **Regenerate a source video that meets the MiniMax-H3 768P output specifications into a 2K video.**

ComfyUI 内置节点 `MinimaxHailuo03RegenerateNode`：

> It uploads the **unmodified 768P video and the exact prompt used to generate it**, starts a MiniMax H3 regeneration job, and returns the re-rendered 2K video.

| 输入 | 要求 |
|---|---|
| `video` | **未修改**的 MiniMax H3 768P 输出；**24 FPS；4–15 秒**；2K 输出不接受 |
| `prompt` | 生成原片时使用的**原始提示词**（不可为空） |
| `first_frame` / `last_frame` | 原生成若用过，需附上同样的 |
| `resolution` | `2K` |
| `watermark` | 是否加 AIGC 水印（默认 false） |

#### 推荐的经济链路

~~~
本地 h3.c 无限次迭代（零边际成本）
      ↓ 选定最终版（1344×768 / 24fps / 5.17s ✅ 完全合规）
      ↓
ComfyUI MinimaxHailuo03RegenerateNode → 2K
（用已有 Comfy 额度，只为成品付费）
~~~

⚠️ **四个约束**：
1. 必须是**未修改**原片（不能二次压缩、不能改帧率）
2. **时长必须 4–15 秒** —— 124 帧（5.17s）✅ 合规；22 帧（0.92s）冒烟片 ❌ 不合规
3. 必须提供原始提示词
4. 原生成若用了首/尾帧或参考素材，需一并附上

#### 本地上采样的替代方案（不等价）

ComfyUI 里也可用通用超分（SeedVR2 / RealESRGAN）把 768P 拉到 2K：
- **通用超分** = 插值放大，**不增加真实细节**
- **H3-Regenerate-2K** = 用 H3 **重新渲染**，会补充细节

两者质量不在一个量级，不要混为一谈。

---

## 5. 可行性判断：32 GB 的边界在哪

### 5.1 社区实测数据（按路线）

**h3.c Metal 引擎**

| 机器 | 配置 | 结果 | 峰值 |
|---|---|---|---|
| M1 Ultra 128GB | 512×512 / 22 帧 / 20 步 / layers45·reuse2 | **总 125 秒**（去噪 86.6s） | 32.8 GiB |
| M1 Ultra 128GB | 768×416 / 141 帧（5.9s）/ 15 步 | **15 分 14 秒** | 34.1 GiB |
| M1 Ultra 128GB | 768×416 / 243 帧（10.1s）/ 15 步 | 34 分 28 秒 | 35.2 GiB |
| M3 Max 128GB | 864×480 / 4.5s / Turbo 5 步 | **约 13 分钟** | — |
| M3 Max 128GB | 864×480 / 3s / **vPipe** Turbo + sol_attn | **约 6.3 分钟**（h3.c 同参数 10.7 min） | — |
| M3 Max 128GB | 1344×768 / 0.9s / 4 步 | 约 4 分钟 | — |
| M4 Pro **24GB**（`--ssd-streaming` + Turbo 折叠） | 832×480 / 124 帧 / 6 步 | **19.4 分钟** | 有 swap |
| M4 Pro 24GB（同上） | 1344×768 / 124 帧 / 6 步 | 75.5 分钟 | 有 swap |
| M5 Air **32GB**（`--ssd-streaming`） | 用户实测**成功出片** | — | — |

**MLX / mlx-serve**

| 机器 | 配置 | 结果 |
|---|---|---|
| M4 Max | 1344×768 / 124 帧 | **约 50 分钟**（开启 fast recipe，约为关闭时的 2.8× 加速） |
| M4 Max | 1344×768 / 209 帧 | 近 2 小时 |
| M3 Ultra | 864×480 / 5s（32 GB 内存档：MLX Core4-pruned resident） | **216.6 秒**，峰值 24.70 GB |

**ComfyUI 原生（PyTorch / MPS）**

| 机器 | 配置 | 结果 |
|---|---|---|
| 32 GB Apple Silicon Mac | Ref2VA / 20 步 / res_multistep·simple | 采样 **1:28:51**，总计 1:32:07，**无 OOM** |

> 该成功报告用的正是 `pruned_int8_convrot` + Qwen3-VL-32B `Q4_K_M` GGUF + **ComfyUI-AppleSilicon-FP8** + ComfyUI-GGUF 的组合——即第 4 章路线 6。

### 5.2 本机实测性能（M1 Max 32GB）—— 已跑通

> v2.0 的推算值已被实测取代。原推算 480p/5s Turbo 需 20–30 分钟，**实测 22 分 57 秒**，吻合。

| 路线 | 场景 | **实测耗时** | 峰值内存 | swap |
|---|---|---|---|---|
| **h3.c** | 512×512 / 22 帧（0.92s）/ 20 步 / 45层 reuse2 | **3 分 49 秒** | 10.59 GB | 0 |
| **h3.c** | 864×480 / 124 帧（5.17s）/ 20 步 / 45层 reuse2 | **39 分 14 秒** | 11.17 GB | 0 |
| **h3.c** ⭐ | 864×480 / 124 帧（5.17s）/ **6 步 Turbo / 50 层全质量** | **22 分 57 秒** | 11.17 GB | 0 |
| **h3.c** | 1344×768 / 22 帧（0.92s）/ 6 步 Turbo / 50 层 | **8 分 34 秒** | 11.44 GB | 0 |
| **h3.c** 🏆 | **1344×768** / 124 帧（5.17s）/ **6 步 Turbo / 50 层** | **1 小时 31 分 25 秒** | **12.71 GB** | **0** |
| MLX 4-bit | — | ❌ **不可行**（编码器需 50.3 GB 常驻） | — | — |
| ComfyUI | 480p / 124 帧 | 未测（生态层，非主力） | — | — |
| 任意 | 243 帧长片 | ⚠️ 未测，预计超线性增长 | — | — |

**经验公式（用于估算，实测校准）**：
- 单次 DiT 前向 ≈ **202 s @ 864×480 / 124 帧 / 45 层**，≈ **209 s @ 50 层**
- 去噪总时长 ≈ 前向次数 × 单次前向耗时；前向次数 = `steps / reuse`（Turbo 折叠后 reuse 必须为 1）
- 视频 VAE 解码固定 ≈ **105 s @ 124 帧**；文本编码器 ≈ 9 s；DiT 加载 ≈ 9 s
- **去噪占端到端 91–94%**，是唯一值得优化的环节

**常用档位速查**（全部实测）：

| 档位 | 配置 | **实测耗时** | 用途 |
|---|---|---|---|
| `smoke` | 512×512 / 22 帧 / 6 步 | ~2 分钟 | 链路验证 |
| `draft` ⭐ | 864×480 / 124 帧 / Turbo 6 步 | **22 分 57 秒** | 日常迭代（零边际成本，放心多跑） |
| `quality` 🏆 | **1344×768** / 124 帧 / Turbo 6 步 | **1 小时 31 分 25 秒** | 成品交付 |

> 已封装为 `./h3gen "提示词" [smoke|draft|quality|base20]`，见第 15 章。

---

## 6. 目录规划与磁盘预算

~~~
$H3_ROOT/
├── h3.c/                          # T1 主力：Metal 引擎（git clone + make）
│   └── h3                         # 编译产物
├── h3-studio/                     # T1 主力：专用 Web UI（:7870）
├── models/
│   ├── MiniMax-H3/                # T1：官方 BF16 分片（FL2VA/ ≈134GB）
│   └── mlx/                       # T0：MLX 4-bit（≈40GB）
├── ComfyUI/                       # T2 生态层（可选）
│   ├── .venv/
│   ├── custom_nodes/
│   └── models/                    # T2：量化档（≈44GB）
├── sd.cpp/                        # 兜底：GGUF 引擎（可选）
├── logs/                          # 基准与运行日志
└── MiniMax-H3-本地部署方案.md       # 本文档
~~~

### 分档磁盘预算

| 组合 | 磁盘 | 说明 |
|---|---|---|
| **T0 最小可用** | **≈ 45 GB** | MLX 4-bit + 工具链 |
| **T0 + 兜底** | ≈ 85 GB | 再加 sd.cpp GGUF |
| **T0 + T1（推荐）** | **≈ 185 GB** | MLX 4-bit + h3.c 官方分片 |
| T0 + T1 + T2 | ≈ 235 GB | 再加 ComfyUI 与量化档 |
| 全量 + Ref2VA | ≈ 400 GB | 含两套 Ref2VA 权重 |

可用 **872 GB**，所有组合均充裕。

---

## 7. 国内镜像加速方案（全部本机实测）

### 7.1 实测结果

| 用途 | 源 | 实测 | 结论 |
|---|---|---|---|
| **模型下载** | `modelscope.cn` | ✅ **14.46 MB/s**（HTTP 206） | ⭐ **主通道** |
| 模型元数据 | `hf-mirror.com` | ⚠️ API ✅ / `resolve` 308 + 0B | 仅查元数据，**不要用它下载** |
| 模型下载 | `huggingface.co` | ❌ HTTP 000 | 禁用 |
| PyPI | `mirrors.aliyun.com` | ✅ 200 | ⭐ 主 |
| PyPI | `mirrors.cloud.tencent.com` / `mirrors.ustc.edu.cn` / `repo.huaweicloud.com` | ✅ 200 | 备 |
| PyPI | `pypi.tuna.tsinghua.edu.cn` | ❌ 403 | 不用 |
| Homebrew | `mirrors.ustc.edu.cn/homebrew-bottles` | ✅ 200 | ⭐ 主 |
| Homebrew | `mirrors.aliyun.com/homebrew/homebrew-bottles` | ✅ 200 | 备 |
| GitHub 代理 | `gh-proxy.com` | ✅ 200 | ⭐ 主 |
| GitHub 代理 | `ghfast.top` / `ghproxy.net` | ✅ 200 | 备 |
| GitHub 代理 | `hub.gitmirror.com` | ❌ 000 | 不用 |

### 7.2 环境变量模板（写入 `~/.zshrc`）

~~~bash
# ---- MiniMax H3 部署环境 ----
export WORKDIR="$H3_ROOT"

# 模型下载：ModelScope 为主
export MODELSCOPE_CACHE="$WORKDIR/.cache/modelscope"
# HuggingFace 兜底：只用于查元数据（本网络 resolve 不可用）
export HF_ENDPOINT="https://hf-mirror.com"

# Homebrew 国内源
export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"
export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"

# GitHub 加速（按需加前缀，不设全局 git 配置）
export GH_PROXY="https://gh-proxy.com"
~~~

### 7.3 关键认知

1. **ModelScope 是唯一可用的模型通道**，所有大文件都从这里下。
2. Comfy-Org 量化档、官方 BF16 分片、GGUF、MLX 4-bit **在 ModelScope 上都有镜像**（已逐一验证）。
3. GitHub 代理只加在 `git clone` 的 URL 前缀上：`git clone https://gh-proxy.com/https://github.com/antirez/h3.c.git`
4. `hf-mirror.com` 的 `resolve` 在本网络拿不到字节，**不要在脚本里依赖它下载**。

---

## 8. 分阶段实施

> 每阶段都有**验证点**。上一阶段不过，不要进入下一阶段。

### Phase 0 — 系统准备（约 30 分钟）

#### 0.1 补装 Metal 编译器（T1 h3.c 必需）

~~~bash
# 方式一：独立组件下载（Xcode 26+ / CLT 26+）
xcodebuild -downloadComponent MetalToolchain
xcrun -sdk macosx metal --version        # 验证
~~~

若方式一不可用，退路是安装完整 Xcode 后：

~~~bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -downloadComponent MetalToolchain
~~~

> **影响范围**：T1（h3.c）**强依赖**；T0（MLX）与 T2（ComfyUI）不依赖。
> T2 也不需要 `ninja`——它只对 M5 的原生 kernel 有用，M1 Max 用不到。

#### 0.2 Homebrew 国内源 + 依赖

~~~bash
source ~/.zshrc                            # 先写入 7.2 的环境变量
brew install python@3.12 ffmpeg cmake
/opt/homebrew/opt/python@3.12/bin/python3.12 -V
ffmpeg -version | head -1
~~~

#### 0.3 目录结构

~~~bash
export WORKDIR="$H3_ROOT"
mkdir -p "$WORKDIR"/{models/mlx,logs}
~~~

**✅ 验证点**：`xcrun metal --version` 有输出；`ffmpeg -version` 正常。

---

### ~~Phase 1 — T0 快通层：MLX 4-bit~~ ❌ 已实测否决

**不要再走这条路。** 经本机查证（详见 13.6），MLX 路线在 32 GB 上有硬障碍：

| 检查项 | 结果 |
|---|---|
| PipeNetwork 4-bit transformer | 磁盘 25.28 GB / 常驻 11.45 GB ✅ 本身没问题 |
| **其文本编码器** | **需 50.3 GB 常驻** ❌ —— 32 GB 物理不可能 |
| 管线 CLI 选项 | 逐个检查 `generate.py`：**无编码器量化/流式开关** |
| mlx-serve 优化版（唯一能塞进 26 GB 的） | 权重仅在 HuggingFace；ModelScope 无镜像；`pull` 直连与挂 hf-mirror 均实测失败 |
| **对照：h3.c 文本编码器** | **峰值仅 2.729 GiB** ✅ |

> 如果你的机器是 **64 GB 或以上**，MLX 路线（mlx-serve / MiniMax-H3-Mac-Easy）仍然值得考虑——它的优势是磁盘只要 40 GB。但 **32 GB 请直接跳到 Phase 2**。

**保留的参考资料**（仅限 ≥64 GB 机器）：

~~~bash
# 中文一键包（MLX 4-bit，约 41 GB）
git clone https://gh-proxy.com/https://github.com/Tsing-Z-QZ/MiniMax-H3-Mac-Easy.git
# 从 Releases 下载 zip 并双击「安装MiniMax-H3.command」
~~~
- 作者建议 **48 GB 以上**内存；模型可放移动硬盘；中文视频工作台

---

### Phase 2 — T1 主力层：h3.c Metal + h3.c-studio（约 3–6 小时，134 GB）

#### 2.1 下载官方 FL2VA 分片（≈134 GB，实测速率下约 2.6 小时）

~~~bash
cd $H3_ROOT
modelscope download --model MiniMax/MiniMax-H3 \
  --include "FL2VA/*" "model_index.json" \
  --local_dir $H3_ROOT/models/MiniMax-H3
~~~

> ⚠️ **必须用这套官方分片**，不要用 Comfy-Org 单文件替代（会花屏）。

#### 2.2 编译 h3.c 并校验

~~~bash
cd $H3_ROOT
git clone https://gh-proxy.com/https://github.com/antirez/h3.c.git
cd h3.c && make -j8

# 秒级校验权重目录（不加载权重）
./h3 --info -d $H3_ROOT/models/MiniMax-H3
~~~

> 若报 `cannot compile h3_shaders.metal`，说明从错误目录启动——`h3` 按自身所在目录查找着色器，务必保留整个源码目录。

#### 2.3 冒烟测试（512×512 / 22 帧）

~~~bash
cd $H3_ROOT/h3.c && mkdir -p outputs

./h3 --profile \
  -d $H3_ROOT/models/MiniMax-H3 \
  -p "A red fox walks through fresh snow in a pine forest. Medium tracking shot, natural winter light, realistic fur, soft footsteps and wind." \
  --width 512 --height 512 --frames 22 --steps 20 \
  --layers 45 --reuse 2 --ssd-streaming \
  -o outputs/smoke-fox.mp4
~~~

**h3.c 参数速查**

| 参数 | 作用 | 本机建议 |
|---|---|---|
| `--ssd-streaming` | 只常驻 2 个 DiT block，其余从 SSD 流式读；DiT 存储 ~36 GiB → ~2 GiB | **32 GB 必开**（前向慢 26–84%） |
| `--layers N` | 只跑前 N 个 block（共 50） | 草稿 45，成品 50 |
| `--reuse N` | 每 N 步复用速度估计 | 草稿 2，成品 1（**Turbo 折叠后必须 1**） |
| `--steps N` | 真实去噪次数 | 20（基准）/ 5–6（Turbo 折叠后） |
| `--show` | 终端逐帧预览 | 本机**不要开**，额外约 10 GiB |

#### 2.4 折叠 Turbo LoRA（20 步 → 5–6 步）

~~~bash
python3 tools/fold_turbo_lora.py --help      # 按实际参数使用

./h3 --profile -d $H3_ROOT/models/MiniMax-H3 \
  -p "<提示词>" --width 864 --height 480 --frames 124 \
  --steps 6 --layers 50 --reuse 1 --ssd-streaming \
  -o outputs/draft-480p.mp4
~~~

> Turbo v4 适配器来自 `larryvrh/MiniMax-H3-Turbo-Lora`（Apache-2.0）。APFS 写时复制，每个折叠变体实际只占约 2–3 GB。
> ⚠️ 蒸馏后的采样计划**不能**与 `--reuse`/`--core-reuse` 混用。

#### 2.5 装 h3.c-studio（专用 Web UI）

两个活跃实现，任选：

~~~bash
# 方案 A：skaiy/h3.c-studio（React + FastAPI，中英双语，Apache-2.0）
git clone https://gh-proxy.com/https://github.com/skaiy/h3.c-studio.git

# 方案 B：syydaniel/minimax-h3-studio（一键安装 + 权重下载 + Web UI :7870）
git clone https://gh-proxy.com/https://github.com/syydaniel/minimax-h3-studio.git
cd minimax-h3-studio && ./install.sh
~~~

功能：结构化提示词工作台（场景/动作/镜头/影调/声音）、首尾帧与有序参考素材上传、逐阶段进度（文本编码 → 去噪 → VAE 解码）、成片库、**链式分镜**（一键把上一段末帧作为下一段首帧）。

> ⚠️ `syydaniel/minimax-h3-studio` 默认按 **DiT 常驻 37–45 GiB** 设计，官方建议 64 GB+。**32 GB 机器要手动改用 `--ssd-streaming`**，不要直接用它的默认配置。

**✅ 验证点**：Web UI 能打开；512×512 冒烟片生成成功；`--profile` 显示峰值远低于 32 GiB。

---

### Phase 3（可选）— T2 生态层：ComfyUI

**仅在需要 LoRA / Fun-ControlNet / 多帧参考 / 跑其他模型时才做这一步。**

~~~bash
cd $H3_ROOT
git clone https://gh-proxy.com/https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate

pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
pip config set global.trusted-host mirrors.aliyun.com
python -m pip install -U pip wheel setuptools
pip install torch torchvision torchaudio
pip install -r requirements.txt

python -c "import torch; print('MPS:', torch.backends.mps.is_available())"   # 期望 True
~~~

启动：

~~~bash
python main.py --use-pytorch-cross-attention --listen 127.0.0.1 --port 8188
~~~

> ⚠️ **绝对不要加** `--force-fp16` / `--fp16-unet` / `--fp16-text-enc`。
> 错误精度会在第一步产生 NaN / 花屏，最终表现为 `SaveVideo: avcodec_send_frame() returned 22`。`--bf16-vae` 可保留。

自定义节点：

~~~bash
cd custom_nodes
git clone https://gh-proxy.com/https://github.com/ltdrdata/ComfyUI-Manager.git
git clone https://gh-proxy.com/https://github.com/city96/ComfyUI-GGUF.git
git clone https://gh-proxy.com/https://github.com/pawel-mazurkiewicz/ComfyUI-AppleSilicon-FP8.git
git clone https://gh-proxy.com/https://github.com/yshenaw/ComfyUI-SolAttn-MPS.git
cd ComfyUI-AppleSilicon-FP8 && ../../.venv/bin/pip install -r requirements.txt && cd ..
~~~

**AppleSilicon-FP8 在本机的真实作用（务必理解预期）**

| 层 | M1 Max 是否启用 |
|---|---|
| 兼容层：让 FP8/INT8 量化模型**能加载不崩溃** | ✅ **本机装它的唯一理由** |
| 融合 RMSNorm / RoPE | ✅ |
| Metal flash-attention | ✅ |
| 原生 int8 / int4 / fp8 矩阵内核 | ❌ 需要 M5 的矩阵单元 + Metal 4.0/4.1，**不会启用**（惰性，不报错） |

下载量化权重：

~~~bash
pip install -U modelscope
cd $H3_ROOT/ComfyUI

modelscope download --model Comfy-Org/MiniMax-H3 \
  --include "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors" \
            "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" \
            "vae/minimax_h3_video_vae_fp16.safetensors" \
            "vae/minimax_h3_audio_vae_fp32.safetensors" \
            "loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors" \
  --local_dir ./models
~~~

**✅ 验证点**：`http://127.0.0.1:8188` 界面正常；日志有 AppleSilicon-FP8 能力摘要；H3 模板能出一个带声音的 480p 短片。

---

### Phase 4（可选）— 兜底：stable-diffusion.cpp（35.5 GB）

内存最省的一条路，适合 MLX/h3.c 都跑不动时兜底：

~~~bash
git clone https://gh-proxy.com/https://github.com/leejet/stable-diffusion.cpp.git
cd stable-diffusion.cpp
cmake -B build -DGGML_METAL=ON && cmake --build build --config Release -j8

# 权重（ModelScope）
modelscope download --model leejet/MiniMax-H3-GGUF \
  --include "minimax_h3_fl2va_pruned-Q4_K_M.gguf" "qwen3vl_32b_minimax_h3-Q4_K_M.gguf" \
  --local_dir ./models
# VAE 从 Comfy-Org/MiniMax-H3 的 vae/ 取
~~~

关键参数：`--offload-to-cpu`（把权重放 CPU 侧）、`--diffusion-fa`（Flash Attention 省内存）、`--rng cpu`（可复现）、`--cfg-scale 1.0`。

> H3 支持是 2026-08-04 Day-1 加入的，**Mac 实测数据稀缺**，请先跑小分辨率基准再投入。

---

### Phase 5 — 加速与调优

#### 5.1 提速杠杆（按收益排序）

| 优先级 | 手段 | 预期收益 | 代价 |
|---|---|---|---|
| 1 | **降低分辨率 / 帧数** | 近线性 | 画质下降 ⭐ 先做 |
| 2 | **Turbo LoRA（20→5/6 步）** | ~3× | 极低频人声/耳语、硬切可能劣化 |
| 3 | **vPipe 引擎**（h3.c 的替代后端） | 实测 **1.4–1.7×** | 需额外编译与补丁 |
| 4 | **Sol-Attn**（T2 用 MPS 版；h3.c 侧走 sol_attn） | ~1.4×，**已验证逐位无损** | 需装 |
| 5 | `--layers 45` + `--reuse 2`（草稿档） | 中等 | 细节略降 |
| 6 | Sage Attention | 有提升 | **额外占显存**，32 GB 慎用 |
| 7 | 量化 | **只买"装得下"，不买速度** | 同参数量计算量不变 |

> **重要认知**：量化不会让同一模型变快——只有"从装不下变成装得下"才会带来数量级提升（避免逐层 offload 的换入换出）。两个都能装下的档位之间，速度差异是噪声。

#### 5.2 内存与散热

~~~bash
sysctl iogpu.wired_limit_mb                 # 查看当前 GPU 可接线上限（本机为 0 = 自动 ≈24GB）

# MLX 4-bit 峰值 26 GB > 默认 24 GB，可能触发换页；必要时临时上调（重启失效）
sudo sysctl iogpu.wired_limit_mb=28672      # 28 GB
~~~

- 长任务前关闭浏览器 / 其他大内存应用
- M1 Max 长时间满载会热降频；1–3 小时的任务建议加强散热
- 用 `--profile`（h3.c）或活动监视器记录峰值 footprint，纳入 Phase 6 基准表

#### 5.3 提示词要点（影响重跑次数 = 实际成本）

- 描述**一个连续镜头**：主体、动作、镜头运动、光线、需保持一致的元素
- **明确写出声音**；不需要对白/音乐时写 `no speech` / `no music`
- 5 秒内避免多剪辑与互不相关的场景
- 时长与提示词匹配：15 秒的描述塞进 124 帧会变成"快进片"

---

### Phase 6 — 基准测试与默认档位固化

固定 prompt 与 seed，跑下面四组，记录到 `logs/benchmark.md`：

| # | 路线 | 配置 | 记录项 |
|---|---|---|---|
| B1 | h3.c | 512×512 / 22 帧 / 20 步 / layers45·reuse2 / SSD 流式 | wall、峰值内存、swap |
| B2 | h3.c | 864×480 / 124 帧 / 6 步 Turbo / layers50·reuse1 | wall、峰值内存、swap |
| B3 | MLX 4-bit | 864×480 / 5s / Turbo | wall、峰值内存 |
| B4 | ComfyUI（若装） | 864×480 / 124 帧 / 4 步 Turbo + Sol-Attn | wall、峰值内存 |

**验收标准**：B1 ≤ 10 分钟；B2 ≤ 35 分钟；B3 能完成不崩；B4 无 OOM。

**据此固化默认档位**：日常草稿用 h3.c 的 480p/Turbo6；需要 LoRA/ControlNet 时切 ComfyUI；MLX 作为低磁盘备用。

---

### Phase 7（可选）— MiniMax Music 3

本机**性价比最高**的 MiniMax 模型：

| 项 | 值 |
|---|---|
| 权重体积 | **≈ 14.3 GB**（DiT 4.9 GB + pruned int8 文本编码器 9.2 GB + DAV 音频 VAE 0.2 GB） |
| 能力 | 完整歌曲 ≤5 分钟，32 kHz / 16-bit 立体声，支持 `[Verse]` `[Chorus]` 等段落标签与结构化 Caption |
| ComfyUI 要求 | **≥ 0.33.0**，模板库自带 Music 3 工作流 |
| 下载 | `modelscope download --model MiniMax/MiniMax-Music3 --local_dir ./models` |
| 建议 | 首次把 `max_duration` 设为 60 秒快速验证；长曲开启分块音频 VAE 解码 |

---

## 9. 参数速查卡

### 9.1 硬约束（写错必失败）

| 约束 | 规则 |
|---|---|
| 分辨率 | 短边 768 基准；宽高**必须是 32 的倍数**；面积 ≤ 768×1344；原生 16:9 = **1344×768** |
| ⚠️ 分辨率陷阱 | 不要用 1.0 MP 档，会解析成 1376×768 **超出上限**；用 0.98 MP |
| 帧数 | 吸附到 **17k+5** 网格：5, 22, 39, 56, 73, 90, 107, **124**, 141, …, 243 |
| 时长 | 24 fps；124 帧 = 5.17s；开权重上限约 15s |
| ComfyUI 启动 | 禁用 `--force-fp16` / `--fp16-unet` / `--fp16-text-enc` |
| h3.c 权重 | **只能**用官方 `MiniMaxAI/MiniMax-H3` 分片 |

### 9.2 ComfyUI 模板默认参数

~~~
UNETLoader          minimax_h3_fl2va_pruned_int8_convrot.safetensors
CLIPLoader          qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors | type: minimax
KSamplerSelect      res_multistep
BasicScheduler      simple, steps 20, denoise 1.0
BasicGuider         （无负面输入，CFG 等效 1.0）
Resolution Selector 0.98 MP 或 1344 × 768
MiniMaxH3ImageToVideo  length 124, ref_image_size: match
CreateVideo         24 fps, bit_depth 8
~~~

**值得 A/B 的只有两个旋钮**：`scheduler`（`beta`/`normal` vs `simple`）、`ref_image_size`（迭代 `match`，成品 `max`）。
**不要动**：steps 20、denoise 1.0、`BasicGuider`。

---

## 10. 风险登记册与排障手册

### 10.1 风险登记册

| ID | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | **许可证**：排除地区 + 商用需付费授权 | 🔴 高 | 限定个人学习/研究；不对外服务；下载前复核 LICENSE |
| R2 | **32 GB 低于舒适线**：高分辨率/长片触发 swap | 🔴 高 | h3.c 强制 `--ssd-streaming`；MLX 上调 `iogpu.wired_limit_mb`；先用 480p/124 帧 |
| R3 | **耗时预期落差** | 🟠 中 | 用最小冒烟档建立基线；Turbo 低步数；先定画面再升规格 |
| R4 | **h3.c 权重格式坑** → 花屏/黑屏（音频正常） | 🟠 中 | 只用官方分片；两套权重分目录 |
| R5 | **M1 无矩阵单元**，原生 int8/fp8 kernel 不可用 | 🟡 低 | 已知预期非故障；兼容层 + 融合 RMSNorm/RoPE 仍生效 |
| R6 | **热降频**（1–3 小时满载） | 🟡 低 | 加强散热；分批跑 |
| R7 | **网络**：HF 不可达，镜像失效风险 | 🟠 中 | ModelScope 为主；PyPI/brew 备多套源 |
| R8 | **路线碎片化**：社区项目迭代快，可能失维护 | 🟠 中 | 优先选活跃项目（h3.c / mlx-serve）；锁定版本与 commit |
| R9 | **sd.cpp 的 H3 支持较新**，Mac 数据稀缺 | 🟡 低 | 仅作兜底；先小分辨率验证 |
| R10 | **磁盘**：全量约 235–400 GB | 🟡 低 | 872 GB 可用；按第 6 章分档取舍 |

### 10.2 排障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 画面全花 / 全黑但**有声音** | h3.c 读到未 8 字节对齐的重打包权重 | 换官方 `MiniMax/MiniMax-H3` 分片 |
| `cannot compile h3_shaders.metal` | 从错误目录启动 `h3` | 保留完整源码目录，从 `h3.c/` 内启动 |
| h3.c 生成中 OOM | 未开流式或分辨率过高 | 加 `--ssd-streaming`；降分辨率/帧数；`--layers 45` |
| MLX 生成中途卡顿/换页 | 峰值 26 GB 超过默认 24 GB 可接线上限 | `sudo sysctl iogpu.wired_limit_mb=28672`；关闭其他大内存应用 |
| `RuntimeError: Undefined type Float8_e4m3fn` | MPS 不支持 FP8 类型 | 装 **ComfyUI-AppleSilicon-FP8** |
| `No backend can handle 'dequantize_int8_embedding'` | INT8 嵌入无 MPS 后端 | 同上 |
| `SaveVideo: avcodec_send_frame() returned 22` | 精度配置错误导致 NaN/花屏 | 去掉 `--force-fp16`/`--fp16-unet`/`--fp16-text-enc` |
| `MPSGraph ... larger than INT_MAX` | MPS 图维度上限 | 降分辨率/帧数；升级 ComfyUI 与 AppleSilicon-FP8 |
| 帧数不被接受 | 未落在 `17k+5` 网格 | 改用 124 / 141 / 158 等合法值 |
| 分辨率报错 | 用了 1.0 MP 档或非 32 倍数 | 用 0.98 MP 或 1344×768 |
| ComfyUI 启动挂起 | 历史版本 ninja 阻塞式内核编译 | 不装 ninja；升级 AppleSilicon-FP8 |
| 下载中断 | 网络抖动 | ModelScope 支持断点续传，重跑同命令即可 |

---

## 11. 实施检查清单

- [ ] **Phase 0** Metal 工具链 ✅ / python@3.12 ✅ / ffmpeg ✅ / 目录结构 ✅
- [ ] **Phase 1 (T0)** MLX 4-bit 模型就位 ✅ / 256×256 带声音冒烟片 ✅
- [ ] **Phase 2 (T1)** FL2VA 134 GB 下载完成 ✅ / h3.c 编译 + `--info` 校验 ✅ / 512×512 冒烟片 ✅ / Turbo 折叠 ✅ / Web UI 可用 ✅
- [ ] **Phase 3 (T2, 可选)** ComfyUI 启动 + MPS ✅ / AppleSilicon-FP8 摘要 ✅ / H3 480p 带声音出片 ✅
- [ ] **Phase 4 (可选)** sd.cpp 编译 + GGUF 就位 ✅
- [ ] **Phase 5** vPipe / Sol-Attn 至少启用一项 ✅
- [ ] **Phase 6** 基准表 B1–B4 完成 ✅ / 默认档位固化 ✅
- [ ] **合规** 已确认个人学习/研究用途 ✅ / 已复核 LICENSE ✅

---

## 12. 附录

### 12.1 模型（ModelScope，全部实测 200）

| 仓库 | 内容 | 体积 |
|---|---|---|
| `Comfy-Org/MiniMax-H3` | ComfyUI 量化档 + Turbo LoRA + Fun-ControlNet | 按需，约 44 GB |
| `MiniMax/MiniMax-H3` | 官方 BF16 分片（h3.c 专用） | 134 GB（FL2VA） |
| `MiniMax/MiniMax-Music3` | Music 3 | 14.3 GB |
| `leejet/MiniMax-H3-GGUF` | GGUF（sd.cpp / ComfyUI-GGUF） | 35.5 GB |
| `ddalcu/MiniMax-H3-MLX-4bit` / `mlx-community/MiniMax-H3-4bit` | MLX 4-bit | 40 GB |
| `Abiray/MiniMax-H3-GGUF` | GGUF + 现成工作流 JSON | — |
| `larryvrh/MiniMax-H3-Turbo-Lora` | Turbo 蒸馏适配器（Apache-2.0） | — |

### 12.2 代码仓库（经 gh-proxy.com 可达）

| 仓库 | 用途 | 层 |
|---|---|---|
| `antirez/h3.c` | **C + Metal 原生引擎** | T1 核心 |
| `skaiy/h3.c-studio` | h3.c 专用 Web UI（React + FastAPI，中英双语） | T1 |
| `syydaniel/minimax-h3-studio` | h3.c 一键安装 + Web UI + vPipe | T1 |
| `janishar/h3c-studio` | h3.c 的 Go 版 Web UI | T1 |
| `ddalcu/mlx-serve` | MLX 推理服务（含 H3 视频 + iOS App） | T0 |
| `Tsing-Z-QZ/MiniMax-H3-Mac-Easy` | MLX 中文一键安装包 | T0 |
| `comfyanonymous/ComfyUI` | 主程序 | T2 |
| `ltdrdata/ComfyUI-Manager` | 节点管理 | T2 |
| `city96/ComfyUI-GGUF` | GGUF 模型加载 | T2 |
| `pawel-mazurkiewicz/ComfyUI-AppleSilicon-FP8` | MPS 上跑 FP8/INT8 的兼容层 | T2 |
| `yshenaw/ComfyUI-SolAttn-MPS` | Apple Silicon 无损稀疏注意力 | T2 |
| `skaiy/wild-h3c-comfyui` | h3.c ↔ ComfyUI 桥接节点 | T2 |
| `leejet/stable-diffusion.cpp` | C++/GGUF 引擎（Day-1 支持 H3） | 兜底 |
| `EvolvingLMMs-Lab/MacOS-H3-Speedrun` | Apple Silicon MLX 内存分档工作流 | 参考 |

### 12.3 关键文档

- ComfyUI H3 官方教程：`https://docs.comfy.org/tutorials/video/minimax/minimax-h3`
- MiniMax 官方自托管指南：`https://platform.minimax.io/docs/guides/local-deploy-h3.md`
- H3 性能与最佳配置报告（社区汇编，含 17 份现场报告）：`wildminder/awesome-minimax-H3` → `guides/minimax-h3-performance.md`
- h3.c 实测 issue：#17（M1 Ultra 完整画像 + 两条负面结果）、#18 / #51（M4 Pro 24GB）、#30（M5 Air 32GB 成功）、#14（Turbo LoRA 离线折叠）
- mlx-serve 发布说明 v26.8.2（H3 视频 + 4-bit 内存口径）

### 12.4 本机实测基准（已完成，详见第 13 章）

| # | 路线 | 配置 | 耗时 | 峰值内存 | swap | 日期 |
|---|---|---|---|---|---|---|
| B1 | h3.c | 512×512 / 22f / 20 步 / 45层 reuse2 | **229.16 s** | 10.59 GB | 0 | 2026-10-03 |
| B2 | h3.c | 864×480 / 124f / 20 步 / 45层 reuse2 | **2354.40 s** | 11.17 GB | 0 | 2026-10-03 |
| B3 | h3.c + Turbo | 864×480 / 124f / **6 步 / 50 层全质量** | **1377.50 s** | 11.17 GB | 0 | 2026-10-03 |
| B4 | h3.c + Turbo | **1344×768** / 124f / 6 步 / 50 层 | **5485.13 s** | 12.71 GB | 0 | 2026-10-03 |
| B5 | h3.c + Turbo | 1344×768 / 22f / 6 步 / 50 层 | 514.31 s | 11.44 GB | 0 | 2026-10-03 |
| B6 | MLX 4-bit | — | ❌ 不可行 | — | — | 已否决 |
| B7 | ComfyUI | — | 未测 | — | — | 待定 |

**实测产物**（`h3.c/outputs/`）：
- `smoke-fox.mp4` — 512×512 / 0.92 s / 247 KB
- `bench-480p.mp4` — 864×480 / 5.175 s / 1.76 MB（平衡档 20 步）
- `bench-480p-turbo.mp4` — 864×480 / 5.175 s / 2.15 MB（Turbo 6 步全质量）
- `bench-768p-22f.mp4` — 1344×768 / 0.92 s
- **`bench-768p-124f.mp4`** — **1344×768 / 5.175 s / 4.17 MB / 6.4 Mbps（成品档）**

全部含 **32 kHz 立体声 AAC**，可直接播放。成品档 5.175 秒也**符合官方 2K 再生成的 4–15 秒要求**（见 4.7）。

---

## 13. 本机实测记录（2026-10-03）

> 以下全部为本机（Apple M1 Max 32GB / macOS 27.0.1）真实运行数据，非推算。

### 13.1 环境与设备

| 项 | 实测值 |
|---|---|
| 设备 | Apple M1 Max（applegpu_g13s） |
| 物理内存 | 32.0 GiB |
| **recommended GPU set** | **25.0 GiB** |
| **max Metal buffer** | **18.7 GiB**（单缓冲区硬上限） |
| Apple GPU family | 7 |
| Metal 4 | yes |
| `iogpu.wired_limit_mb` | 0（自动） |

### 13.2 权重与工具链

| 项 | 结果 |
|---|---|
| FL2VA 下载 | **134.2 GB / 84 文件 / 0 失败**，6 并发，**34.4 MB/s**，约 65 分钟 |
| 权重清单校验 | Qwen3-VL 62.133 GiB（14 文件 1058 张量）/ FL2VA DiT 61.728 GiB（13 文件 535 张量）/ video VAE 9.700 GiB / audio VAE 0.564 GiB |
| h3.c 编译 | `make -j8` 通过，**不需要 Metal 工具链**（着色器运行时编译） |
| ffmpeg | 静态 arm64 9.0.2（evermeet 的 x86_64 版需 Rosetta，已弃用） |
| Turbo LoRA | `minimax_h3_turbo_v4_step600_ema.safetensors` **0.73 GB** |
| LoRA key 匹配预校验 | **259/259** 目标模块全部命中（qkv_proj 52 / fc1 52 / fc2 52 / out_proj 52 / AdaLN linear 51） |
| Turbo 折叠 | 13 分片全部处理，**259/259 adapter pairs**；APFS 写时复制，实际新增 **58 GB** |

### 13.3 分阶段实测（三个基准）

| 阶段 | B1 冒烟 | B2 平衡档 | B3 Turbo 全质量 |
|---|---|---|---|
| Qwen 文本编码器 | 9.489 s / **2.729 GiB** | 9.489 s / 2.729 GiB | 8.899 s / 2.729 GiB |
| DiT 加载（SSD 流式） | 9.709 s / 3.470 GiB | 9.709 s / 3.470 GiB | 8.634 s / 3.251 GiB |
| **DiT Euler 去噪** | ≈190 s | **2224.886 s** / 3.470 GiB | **1253.455 s** / 3.251 GiB |
| 音频 VAE 解码 | 4.118 s / 0.282 GiB | 1.435 s / 0.283 GiB | 0.969 s / 0.283 GiB |
| 视频 VAE 解码 | 13.139 s / 9.454 GiB | 107.571 s / 9.408 GiB | 104.064 s / 9.408 GiB |
| **端到端** | **229.16 s（3:49）** | **2354.40 s（39:14）** | **1377.50 s（22:57）** |
| 峰值 footprint | 10.59 GB | 11.17 GB | 11.17 GB |
| 最大 RSS | 7.70 GB | 11.51 GB | 11.05 GB |
| **swaps** | **0** | **0** | **0** |

> 关键观察：**去噪占端到端时间的 91–94%**，是唯一值得优化的环节。视频 VAE 解码固定约 105 秒（480p/124 帧）、283 秒（768p/124 帧），不可忽略但无法通过步数优化。

**768p 成品档（B4/B5）分阶段实测**：

| 阶段 | B5 短测（22 帧） | **B4 成品档（124 帧）** |
|---|---|---|
| Qwen 文本编码器 | 9.304 s / 2.729 GiB | 9.284 s / **2.729 GiB** |
| DiT 加载（SSD 流式） | 9.039 s / 2.334 GiB | 9.210 s / **5.726 GiB** |
| **DiT Euler 去噪** | **451.590 s**（6 步） | **5180.356 s**（6 步，均 863 s/步） |
| 音频 VAE 解码 | 0.777 s / 0.282 GiB | 0.983 s / 0.283 GiB |
| 视频 VAE 解码 | 42.615 s / 9.554 GiB | **282.811 s** / 9.554 GiB |
| **端到端** | **514.31 s（8:34）** | **5485.13 s（1:31:25）** |
| 峰值 footprint | 11.44 GB | **12.71 GB** |
| 最大 RSS | 9.73 GB | 12.42 GB |
| **swaps** | **0** | **0** |

> **768p 的关键结论**：峰值内存只比 480p 高 1.5 GB。原因是 SSD 流式让 DiT 常驻仅 5.726 GiB，而视频 VAE 走分块解码（峰值 9.554 GiB，与 480p 相同）。
> **代价几乎全在计算，不在内存** —— 单步成本从 480p 的 209 秒涨到 768p 的 863 秒（4.1×，略超像素量 2.5×，符合注意力随序列长度超线性的预期）。

### 13.4 加速效果（B2 → B3）

| 维度 | B2 平衡档 | B3 Turbo | 变化 |
|---|---|---|---|
| 去噪步数 | 20 步（reuse2 → **11 次前向**） | **6 步**（reuse1 → 6 次前向） | −45% |
| DiT 层数 | 45 / 50 | **50 / 50** | **全质量** |
| 去噪耗时 | 2224.9 s | 1253.5 s | **1.78× 加速** |
| 端到端 | 2354.4 s | 1377.5 s | **1.71× 加速** |
| 单次前向 | 202.3 s（45 层） | 208.9 s（50 层） | 每层成本相当 |

**关键结论**：Turbo 折叠在**提升到 50 层全质量的同时**还快了 1.71×，是纯收益。

### 13.5 输出质量验证

| 检查项 | 方法 | 结果 |
|---|---|---|
| 视频规格 | ffprobe | 864×480 / h264 / 24 fps / 5.175 s ✅ |
| **原生立体声** | ffprobe | AAC / **32000 Hz / 2 声道** ✅ |
| 音频非静音 | `volumedetect` | mean −38.5 dB / max −23.7 dB ✅ |
| **真立体声**（非单声道复制） | 左右声道相关系数 | **+0.595** ✅ |
| **时间连贯性** | 相邻帧差 vs 首末帧差 | **11.55 « 61.17** ✅ |
| 画面质量 | 人工抽帧 | 狐狸毛发、雪地、松林细节完整，BF16 满血质量 ✅ |
| 帧数正确性 | 解码计数 | 124 帧 ✅ |

### 13.6 T0（MLX 路线）否决依据

| 检查项 | 实测/查证结果 |
|---|---|
| PipeNetwork 4-bit transformer | 磁盘 25.28 GB，**常驻仅 11.45 GB** ✅（AdaLN 预计算省 13B 参数） |
| **其文本编码器需求** | **50.3 GB 常驻**（Qwen3-VL-32B 截断到 0–49 层） ❌ |
| 管线 CLI 选项 | 逐个检查 `generate.py` 的 `add_argument`：**无编码器量化/流式选项** |
| mlx-serve 优化版 | 号称 4-bit 26 GB 可跑 32GB Mac，但权重仅在 HuggingFace |
| ModelScope 镜像 | `ddalcu/MiniMax-H3-MLX-*` 无镜像（实测 files API 返回空） |
| `mlx-serve pull` | 直连 HF ❌；挂 `HF_ENDPOINT=hf-mirror` 仍 ❌（60 秒无字节） |
| **对照：h3.c 文本编码器** | **峰值 2.729 GiB**（分阶段流式） ✅ |

**结论**：MLX 参考管线在 32 GB 上物理不可行；唯一可行的 mlx-serve 构建在国内网络下不可得。**T0 路线否决，T1（h3.c）是 32GB 的唯一实用解。**

### 13.7 踩坑记录

| 坑 | 现象 | 解决 |
|---|---|---|
| Homebrew 沙箱不可写 | `brew install ffmpeg` 失败 | 完全绕开 brew，用静态 arm64 二进制 |
| 静态 ffmpeg 架构不符 | `Bad CPU type in executable` | evermeet.cx 是 x86_64；改用 martin-riedl.de 的 arm64 构建 |
| USTC brew 镜像 bottle 校验失败 | `Couldn't find manifest matching bottle checksum` | 放弃 brew |
| h3.c 疑似需要 Metal 工具链 | `xcrun metal` 报错 | **实际不需要**，着色器运行时编译，直接 `make` 即可 |
| 日志块缓冲导致看不到进度 | 日志停在 `denoise 0/20` | 用 `ps -o time=` 的 CPU 时间增量判断进度，而非日志 |
| 折叠工具不在主线 | `h3.c/tools/` 不存在 | 从 `syydaniel/minimax-h3-studio` 取 `fold_turbo_lora.py` |

---

## 14. 日常使用：`h3gen` 包装脚本

已固化在 `$H3_ROOT/h3gen`，把实测最优参数与正确 PATH（arm64 ffmpeg）都封装好了。

~~~bash
cd $H3_ROOT

./h3gen "A red fox walks through fresh snow in a pine forest."            # 默认 draft 档
./h3gen "提示词" smoke        # 512×512 / 22帧  → ~2 分钟，链路验证
./h3gen "提示词" draft        # 864×480 / 124帧 → ~23 分钟，日常迭代 ⭐
./h3gen "提示词" quality      # 1344×768 / 124帧 → ~91 分钟，成品交付 🏆
./h3gen "提示词" base20       # 原始权重 20 步平衡档（质量对照用）

# 自定义（画布须为 32 的倍数，面积 ≤ 768×1344；帧数须落在 17k+5 网格）
./h3gen "提示词" custom --width 1344 --height 768 --frames 124 --steps 6
~~~

脚本做的事：
1. 自动设置 `PATH` 指向 arm64 `ffmpeg`/`ffprobe`
2. 按档位选择模型（`MiniMax-H3-turbo` 折叠版 / `MiniMax-H3` 原始版）与参数
3. 加时间戳输出到 `h3.c/outputs/`，跑完自动 ffprobe 打印规格与总耗时

**推荐工作流**：
~~~
h3gen "想法1" draft   → 23 分钟看效果
h3gen "想法2" draft   → 换个思路再试（零边际成本，随便跑）
        ↓ 选定满意的
h3gen "最终提示词" quality → 91 分钟出成品
        ↓ 需要 2K 时
ComfyUI MinimaxHailuo03RegenerateNode（用已有额度，见 4.7）
~~~

> **注意**：送 2K 再生成时必须用**原始提示词**和**未修改的原片**，且时长需在 4–15 秒。`draft`/`quality` 都是 124 帧（5.175 秒）✅ 合规；`smoke` 的 22 帧 ❌ 不合规。

---

## 15. 图形界面：H3 Studio（h3.c-studio）

### 15.1 选型依据

对比了三个 h3.c 图形界面实现：

| 项目 | 技术栈 | 结论 |
|---|---|---|
| **skaiy/h3.c-studio** | React + FastAPI | ✅ **选用**：五语言界面、Turbo 预设、分镜板、末帧接力、任务持久化 |
| syydaniel/minimax-h3-studio | Python + 原生 JS | ❌ **排除**：作者明确说明"内存小于 64 GB 时 h3.c 有 `--ssd-streaming` 模式…**但本界面目前没有接入**" → 32GB 机器不可用 |
| janishar/h3c-studio | Go | ❌ 依赖 helmstudio 启动器，链路更长 |

### 15.2 关键本地适配：补上 `--ssd-streaming`

原版 Studio 的命令构建里**没有 `--ssd-streaming`**（支持的参数只有 `--layers/--reuse/--steps/--checkpoint/--resume/`…）。在本机这是致命的：DiT 满驻留需 **37–45 GiB**，而 `max Metal buffer` 只有 **18.7 GiB**，不加该参数必然分配失败。

已在 `studio/server/main.py` 的 `job_command()` 中加入约 5 行补丁：

~~~python
# --- local patch (DSH): 32GB 统一内存必须启用 SSD 流式 -------------------
# 本机 max Metal buffer 仅 18.7 GiB，而 DiT 满驻留需 37-45 GiB，
# 不开启 --ssd-streaming 必然分配失败。默认开启，H3_SSD_STREAMING=0 可关闭。
if os.environ.get("H3_SSD_STREAMING", "1") != "0":
    cmd.append("--ssd-streaming")
# --- end local patch --------------------------------------------------
~~~

> 升级 Studio 后此补丁会被覆盖，需重新应用。

### 15.3 安装记录（含两个坑）

~~~bash
cd $H3_ROOT
git clone --depth 1 https://gh-proxy.com/https://github.com/skaiy/h3.c-studio.git h3.c-studio
cd h3.c-studio && make -j8                      # 构建引擎（复用已有权重，不重新下载）

# 软链接到已下载的权重与输出目录，避免重复占盘
ln -s ../models/MiniMax-H3       MiniMax-H3
ln -s ../models/MiniMax-H3-turbo MiniMax-H3-turbo
ln -s ../h3.c/outputs            outputs

# 后端：必须 Python 3.12（3.9 不支持 `float | None` 语法）
brew install python@3.12
cd studio/server && /opt/homebrew/bin/python3.12 -m venv .venv
./.venv/bin/pip install fastapi "uvicorn[standard]" pydantic python-multipart

# 前端
cd .. && npm install
~~~

> **以上步骤现在可以一键完成**：`./deploy.sh --stage studio` 会自动
> clone → `make` → 建模型软链 → 打 `--ssd-streaming` 补丁 → `npm install`
> → 创建后端 venv。手工路径保留在此，供排查问题时逐步对照。

**两个实测坑**：

| 坑 | 现象 | 解决 |
|---|---|---|
| **Python 版本** | 后端启动即崩：`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`（`reference_assets.py:38`） | 系统 Python 3.9 不支持 PEP 604 联合类型；装 `python@3.12` 重建 venv |
| **npm 镜像** | `npm install` 卡死无进展（`node_modules` 0 字节、无 TCP 连接） | **npmmirror 在本网络不可达（HTTP 000），而官方 registry.npmjs.org 反而通（200）**。`npm config set registry https://registry.npmjs.org` |

### 15.4 启动

~~~bash
cd $H3_ROOT
./h3studio          # 前端 http://127.0.0.1:3000  后端 http://127.0.0.1:8765（API 文档 /docs）
~~~

### 15.5 端到端验证（已通过）

通过 API 提交冒烟任务（turbo 6 步 / 512×512 / 22 帧 / seed 42）：

| 检查项 | 结果 |
|---|---|
| 命令行是否含 `--ssd-streaming` | ✅ 确认包含（补丁生效） |
| 任务状态 | `done` |
| 任务耗时 | **133.8 秒** |
| 产物规格 | 512×512 / h264 / 24fps / AAC 立体声 32 kHz ✅ |
| 作品库索引 | ✅ 自动识别到 5 个既有产物（含命令行跑出的基准片） |
| `/api/info` 引擎自检 | ✅ 正确识别 32GB / max Metal buffer 18.7 GiB / 权重清单 |

### 15.6 功能亮点

| 功能 | 说明 |
|---|---|
| **提示词工作室** | 自由文本 / 结构化 Context-IR 双模式；结构化模式提供 Scene / Action / Camera / Look / Audio 五个独立输入框，留空字段自动套用默认值 |
| **条件输入** | 首帧 / 尾帧锚点、多张参考图（Ref2VA）、参考音频（`--ref-audio`），均支持拖拽上传 |
| **实时进度** | 分阶段进度条（文本编码 → 去噪 → VAE 解码）+ 日志流 + 可取消 |
| **Turbo 6 步预设** ⭐ | 一键切换到我们已折叠的 `MiniMax-H3-turbo` 模型目录 |
| **任务持久化** | 状态落盘，重启进程历史不丢，未完成任务标记为"已中断" |
| **分镜板** | 多镜头卡片 + 自动末帧接力链 + 一键无损拼接导出 |
| **末帧接力** | 一键抽取任意视频末帧作为下一条的首帧 |
| **断点续跑** | `--checkpoint-after-step` / `--resume`，长视频中途出草稿 |
| **i18n** | 中文 / English / 日本語 / 한국어 / Deutsch |

### 15.7 已知限制

- **单任务串行**：GPU 队列，一次只跑一条
- **默认无鉴权**：仅限本机使用。如需局域网暴露，设 `H3_STUDIO_TOKEN`（仅保护写操作，读与媒体仍公开）
- **Vite 开发模式**：非生产构建，首次加载稍慢
- 界面**未暴露** `--token-reduction` 之外的进阶参数（如 `--core-reuse`）

---

## 16. ComfyUI 与官方 API 节点接入

### 16.1 定位：ComfyUI 不是本地引擎，而是官方 API 的宿主

本方案中 **h3.c 负责本地生成**，ComfyUI 只承担一件事：**托管两个开源权重里没有的官方 API 节点**（见 4.7）。

| 节点 | 作用 | 费用 |
|---|---|---|
| `MinimaxHailuo03ContextIRNode` | 提示词增强（前置） | **$0.02** 纯文本 / $0.05 带首尾帧 / $0.06–0.11 带参考素材 |
| `MinimaxHailuo03RegenerateNode` | 768P → **2K** 再生成（后置） | 按官方计费 |

### 16.2 安装记录

~~~bash
cd $H3_ROOT
git clone --depth 1 https://gh-proxy.com/https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
/opt/homebrew/bin/python3.12 -m venv .venv
./.venv/bin/pip install torch torchvision torchaudio          # torch 2.14.1
./.venv/bin/pip install -i https://pypi.org/simple -r requirements.txt
./.venv/bin/python -c "import torch; print(torch.backends.mps.is_available())"   # True
~~~

**坑**：`pip install -r requirements.txt` 走阿里云镜像会失败 —— `comfyui-workflow-templates==0.11.76` 镜像未同步（最新只到 0.11.74）。**必须用官方 PyPI**。

### 16.3 API 请求格式（实测确定，非猜测）

DynamicCombo 类型的输入在 API 格式里用**扁平 dot-key**：

~~~json
{
  "1": {"class_type": "MinimaxHailuo03ContextIRNode",
        "inputs": {"model": "MiniMax H3",
                   "model.prompt": "粗略描述",
                   "model.duration": 5,
                   "model.ratio": "16:9"}},
  "2": {"class_type": "SaveText",
        "inputs": {"text": ["1", 0], "filename_prefix": "contextir", "format": "txt"}}
}
~~~

鉴权走 `extra_data.api_key_comfy_org`（key 格式 `comfyui-...`）。

> 实测过程：尝试了 4 种候选格式（扁平 dot-key / 嵌套 dict / 带 key 字段 / 选项名嵌套），只有**扁平 dot-key** 能通过校验并进入执行；无 key 时返回 `Unauthorized: Please login first` —— 这同时证明了格式正确且链路通畅。

### 16.4 两个接入工具

~~~bash
# 提示词增强：粗略想法 → 结构化提示词（stdout 可直接喂给 h3gen）
./comfy-contextir "赛博朋克城市夜景，雨中霓虹" --duration 5 --ratio 16:9

# 2K 再生成：本地 768P 成片 → 2K
./comfy-2k h3.c/outputs/bench-768p-124f.mp4 "原始提示词" [--watermark]
~~~

API Key 配置（**这是 Comfy 账户的 key，不是 MiniMax 官方 key**）：

~~~bash
# 到 https://platform.comfy.org/login 生成（格式 comfyui-xxxx）
echo "comfyui-你的key" > $H3_ROOT/.comfy_api_key
chmod 600 $H3_ROOT/.comfy_api_key
# 或临时用环境变量 COMFY_API_KEY
~~~

### 16.5 完整工作流（把三段串起来）

~~~bash
cd $H3_ROOT

# ① 官方提示词增强（约 $0.02）
./comfy-contextir "一个中文想法" > /tmp/prompt.txt

# ② 本地迭代 —— 零边际成本，随便跑
./h3gen "$(cat /tmp/prompt.txt)" draft        # 480p / 23 分钟

# ③ 本地出片
./h3gen "$(cat /tmp/prompt.txt)" quality      # 768P / 91 分钟

# ④ 官方 2K 再生成（只为成品付费）
./comfy-2k h3.c/outputs/h3-quality-*.mp4 "$(cat /tmp/prompt.txt)"
~~~

### 16.6 官方硬性约束（写错必失败）

| 约束 | 说明 |
|---|---|
| **媒体按位置引用** | Context-IR 的增强提示词用 `<Picture 1>`、`<Video 1>` 指代素材。本地生成时必须挂**同样的图、同样的顺序**，否则引用错位 |
| **2K 帧数网格** | **107–362 帧、步进 17**（即 107, 124, 141, …, 362）。官方 API 实测返回的精确约束，比"4–15 秒"更严格 |
| **2K 最小面积** | **≥ 768×768 = 589824 像素**。官方 API 实测：`base_video area 262144 is below min 589824 (768*768)`。**864×480（414720）也不合规** |
| **2K 输入规格** | 必须**未修改**的原始输出、**24 FPS**、2K 输出不接受 |
| **原始提示词** | 2K 再生成必须提供生成原片时的**完全一致**的提示词 |
| **不可二次再生成** | 2K 成片不能再送入 Regenerate |
| ⚠️ 时长陷阱 | `draft`/`quality` 都是 **124 帧**（5.175s）✅ 双网格都合规；`smoke` 的 22 帧（0.92s）❌ **不合规** |
| 💡 两个网格 | 本地 h3.c = `17k+5`；官方 2K = `107+17k`。**124 是两者唯一在常用区间内的交集** |

### 16.7 端到端实测结果（已全部跑通）

#### ① Context-IR 提示词增强 ✅

**输入**（中文粗略想法）：
> 一只红狐狸在雪地里走过，镜头跟着它，冬天清晨的光线，能听到风声和踩雪的声音

**输出**（1405 字节，标准三段式结构）：

| 字段 | 内容摘要 |
|---|---|
| `integrated_multimodal_description` | `[Shot 1] Cinematic, in a medium tracking shot, the camera steadily follows a wild red fox...` 详细描述毛色（橙红 + 白色尾尖 + 黑色小腿）、行进方向、雪地质感、背景白桦树、低角度晨光与冷蓝阴影、呼吸白雾 |
| `overall_soundscape` | 踩雪的嘎吱声 + 寒风呼啸声 |
| `non_diegetic_music` | `N/A` |

> 官方把声音也一并结构化了 —— 这正是 H3 "音画同生成" 所需要的输入格式。

#### ② 2K 再生成 ✅

| | 源片 | **2K 成片** |
|---|---|---|
| 分辨率 | 1344 × 768（1.03 MP） | **2560 × 1440（3.69 MP）** |
| 帧率 | 24 fps | 24 fps |
| 时长 | 5.175 s | 5.167 s |
| 音频 | AAC 立体声 32 kHz | AAC 立体声 32 kHz |
| 体积 | 4.17 MB | 4.84 MB |

**3.6× 像素量**，画面细节（毛发层次、眼神、胡须）明显提升。产物：`h3.c/outputs/max-2k-fox.mp4`

### 16.8 接入中踩的两个坑

| 坑 | 现象 | 解决 |
|---|---|---|
| **LoadVideo 拒绝软链接** | `custom_validation_failed: file - Invalid video file` | ComfyUI 的 `exists_annotated_filepath()` 会做**真实路径包含检查**，指向 `input/` 之外的符号链接被判定为无效文件。改用**硬链接**（同卷、零额外空间），失败则复制 |
| **DNS 间歇性挂起** | `ClientConnectorError: Cannot connect to host api.comfy.org:443`，单次等 60 秒 | api.comfy.org 的解析偶发超时（curl 也复现过 `Resolving timed out`）。ComfyUI 内置 3 次重试，通常第 3 次成功；代价是单次调用多等约 2 分钟。**无法用 `/etc/hosts` 固定**（需 root 权限） |

### 16.9 完整链路端到端验证（已跑通）

**链路**：中文想法 → Context-IR 增强 → 本地 768P 生成 → 官方 2K 再生成

| 步骤 | 命令 | 耗时 | 成本 |
|---|---|---|---|
| ① 提示词增强 | `./comfy-contextir "中文想法"` | 约 2 分钟 | $0.02 |
| ② 本地生成 768P | `./h3gen "$(cat prompt.txt)" quality` | **92 分 12 秒**（5532 秒） | 免费 |
| ③ 官方 2K | `./comfy-2k 成片.mp4 "$(cat prompt.txt)"` | 约 4 分钟 | 官方计费 |
| **合计** | | **约 98 分钟** | — |

**三个产物规格**：

| | A 原始简短提示词 | B 增强提示词 | C 增强 + 2K |
|---|---|---|---|
| 分辨率 | 1344×768 | 1344×768 | **2560×1440** |
| 时长 | 5.175 s | 5.175 s | 5.167 s |
| 音频 | AAC 立体声 32 kHz | AAC 立体声 32 kHz | AAC 立体声 32 kHz |
| 体积 | 4.17 MB | 3.32 MB | 3.44 MB |

#### 提示词增强的实测效果（同 seed 42 / 同参数）

**这是全链路最有价值的结论** —— 增强前后差异显著且可量化：

| 指标 | A 原始简短提示词 | B 增强提示词 | 变化 |
|---|---|---|---|
| **画面细节量**（拉普拉斯方差，归一化到 256×144） | 201.3 | **410.5** | **2.04×** |
| 2K 再生成后 | — | **440.1** | 再 +7% |
| 时间连贯性（相邻帧差 « 首末帧差） | 8.62 « 35.96 ✅ | 7.17 « 30.70 ✅ | — |

**画面语义层面的差异**（增强提示词逐条被实现）：

| 增强提示词中的要求 | 是否实现 |
|---|---|
| "medium tracking shot"（中景跟拍） | ✅ 全身构图，非特写 |
| "moving horizontally… from the right side toward the left" | ✅ 右→左行进 |
| "pale golden rim light along the fox's back and tail" | ✅ **金色轮廓光清晰可见** |
| "long, cool blue shadows across the snow" | ✅ 冷暖对比明显 |
| "frost-covered lower trunks of dormant birch trees" | ✅ 白桦树干背景 |
| "thick bushy tail with a distinctive white tip" | ✅ 白色尾尖 |
| "dark, almost black fur on its slender lower legs" | ✅ 黑色小腿 |

**结论**：原始简短提示词给的是"一只狐狸在雪地里"的泛化画面；增强提示词给的是**按规格书拍摄的电影感镜头**。细节量翻倍，且构图、光线、背景都按描述落实。

> ⚠️ **一个观察**：增强提示词版本的音频更轻（mean −57.0 dB vs 原始的 −38.6 dB）。原因是增强提示词把声音明确限定为"踩雪声 + 风声"这类环境音，而原始提示词的 "soft footsteps and wind" 更宽泛。**如果你需要更响的音频，可在提示词的 `overall_soundscape` 段加一句"prominent, foreground-level sound"。**

#### 产物归档

| 文件 | 说明 |
|---|---|
| `h3.c/outputs/bench-768p-124f.mp4` | A：原始简短提示词 768P |
| `h3.c/outputs/final-768p-enhanced.mp4` | **B：增强提示词 768P** |
| `h3.c/outputs/final-2k-enhanced.mp4` | **C：增强 + 官方 2K（2560×1440）** |
| `ComfyUI/output/contextir_00001.txt` | Context-IR 增强出的提示词原文 |

### 16.10 GUI 融合：把本地 h3.c 接入 ComfyUI（已完成）

**目标**：把「本地生成」和「官方 API」两套界面融合为单一界面，操作以 GUI 为主。

**方案**：社区节点 `skaiy/wild-h3c-comfyui`（480 行 Python，含测试）。

| 检查项 | 结果 |
|---|---|
| 支持 `--ssd-streaming` | ✅ 是节点输入，但**默认 False** → 已打补丁改为 **True** |
| 着色器 CWD 问题 | ✅ 该节点已自行解决（`h3_runner.py:189` 设 `cwd=dirname(binary)`） |
| ComfyUI V3 schema 兼容 | ✅ |
| 输出接官方节点 | ✅ `io.Video.Output` 与 Regenerate 的 `video` 输入同为 VIDEO |

**三张预置工作流**（自研生成器产出 UI + API 双格式）：

| 工作流 | 节点 | 用途 | 实测 |
|---|---|---|---|
| `h3-local-draft` | Wild H3 → SaveVideo | 864×480 日常迭代 | 23 分钟 |
| `h3-local-quality` | Wild H3 → SaveVideo | 1344×768 成品 | 92 分钟 |
| **`h3-full-chain`** | ContextIR → Wild H3 → Regenerate 2K → SaveVideo | **一句话出 2K** | **100 分 33 秒** |

**全链路单图验证结果**：

| 阶段 | 耗时 |
|---|---|
| ContextIR 提示词增强（中文想法 → 结构化） | 约 3 分钟 |
| 本地生成 1344×768 / 124 帧 / 6 步 Turbo | 约 92 分钟 |
| 官方 2K 再生成 | 约 5 分钟 |
| **总计** | **6033 秒（100 分 33 秒）** |

产物：**2560×1440 / h264 / 24 fps / AAC 立体声 32 kHz** → `h3.c/outputs/final-chain-2k.mp4`

> 详见 [GUI融合方案.md](GUI融合方案.md)

### 16.11 当前状态

| 项 | 状态 |
|---|---|
| ComfyUI 安装与启动 | ✅ http://127.0.0.1:8188（torch 2.14.1 / MPS True） |
| 两个 API 节点注册 | ✅ 已在 970 个节点中确认 |
| API 请求格式 | ✅ 已实测确定（扁平 dot-key） |
| API Key | ✅ 已配置（`.comfy_api_key`，权限 600） |
| **Context-IR** | ✅ **已跑通并产出结构化提示词** |
| **2K 再生成** | ✅ **已跑通，1344×768 → 2560×1440** |
| 本地生成 | 不受影响，仍走 h3.c |

> ComfyUI 与 h3.c-studio 可同时运行（端口 8188 / 3000 / 8765 互不冲突）。

---

## 17. 版本变更记录

| 版本 | 变更 |
|---|---|
| v1.0 | 首版：ComfyUI 双轨方案（原生 MPS + h3.c 桥接） |
| v2.0 | **新增第 4 章「方案对比与选型」**：横向对比 7 条路线，明确 ComfyUI 在 Apple Silicon 上是最慢路线；推荐架构从「ComfyUI 双轨」改为「MLX 4-bit 快通层 + h3.c / h3.c-studio 主力层 + ComfyUI 可选生态层」 |
| v3.0 | **全部结论改为本机实测**。实际部署 h3.c 并跑通 3 个基准：480p/5.17s 从 39:14（20步）优化到 **22:57（Turbo 6步/50层全质量）**，峰值内存仅 11.17 GB、零 swap。**实测否决 T0（MLX）路线**——其文本编码器需 50.3 GB 常驻，而 h3.c 仅需 2.729 GiB。推荐架构修正为「**h3.c 单主力 + ComfyUI 可选生态**」。新增第 13 章完整实测记录与踩坑清单；新增 4.6 节 ComfyUI Context-IR 提示词增强用法 |
| **v3.5** | **完整链路端到端验证通过**（中文想法 → Context-IR → 本地 768P → 官方 2K，全程约 98 分钟）。**提示词增强效果可量化：画面细节量翻倍（201.3 → 410.5）**，且增强提示词中的构图/光线/背景要求逐条被实现。新增 16.9 节完整对比数据与产物归档 |
| **v3.4** | **两个官方 API 节点全部跑通**。Context-IR 把一个中文想法增强为 1405 字节的标准三段式提示词（画面/环境音/配乐）；2K 再生成把 1344×768 提到 **2560×1440**（3.6× 像素）。修复两个真实缺陷：Context-IR 输出解析（SaveText 返回字符串列表而非文件字典）、LoadVideo 拒绝软链接（ComfyUI 做真实路径包含检查 → 改硬链接）。记录 DNS 间歇性挂起问题 |
| **v3.3** | **安装 ComfyUI 并接入两个官方 API 节点**（Context-IR 提示词增强 + 768P→2K 再生成）。实测确定 DynamicCombo 的 API 格式为扁平 dot-key（4 种候选里唯一可行）；封装 `comfy-contextir` / `comfy-2k` 两个 CLI，与 `h3gen` 串成"官方增强 → 本地迭代 → 官方 2K"的完整链路。新增第 16 章。踩坑：`comfyui-workflow-templates` 在阿里云镜像未同步，requirements 必须走官方 PyPI |
| **v3.2** | **安装并跑通图形界面 H3 Studio（h3.c-studio）**。选型排除了不支持 `--ssd-streaming` 的实现；给原版打了 5 行补丁让生成命令默认带 SSD 流式（否则 32GB 必崩）。端到端验证通过：API 提交任务 → 133.8 秒出片 → 作品库自动索引。新增第 15 章安装与适配记录，含两个实测坑（Python 3.9 不支持 `float \| None`；npmmirror 不可达而 npmjs 可达） |
| v3.1 | **补齐 1344×768 成品档实测**：**1 小时 31 分 25 秒/条，峰值内存 12.71 GB，零 swap**。关键发现：**768p 不是内存瓶颈**（只比 480p 高 1.5 GB），代价几乎全在计算（单步 209 s → 863 s）。新增 4.7 节厘清「本地 768P 是不是最终质量」——开源版不含 **H3-Context-IR** 与 **H3-Regenerate-2K**，但官方 2K 再生成的输入规格**恰好就是本地输出规格**，可无缝衔接。新增第 14 章 `h3gen` 日常包装脚本 |

---

*本文档基于 2026 年 8 月的公开资料与本机实测撰写。MiniMax H3 生态迭代很快（ComfyUI 版本、量化档、社区引擎均在变动），执行前请复核 12.1 节的模型仓库版本与各引擎的当前 commit。*
