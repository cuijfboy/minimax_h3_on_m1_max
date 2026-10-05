# MiniMax H3 on M1 Max

在 Apple Silicon Mac 上本地跑 **MiniMax H3**（33.1B 视频+音频生成模型）的完整方案 ——
从模型下载、本地推理、官方 API 增强，到多镜头分镜的全流程落地。

> 在一台 **M1 Max 32GB** 上从零搭起并实测完成。所有性能数字都是真机跑出来的，
> 原始日志在 [`benchmarks/`](benchmarks/)。

---

## 这个仓库给你什么

| | 内容 |
|---|---|
| **一键部署** | `./deploy.sh` —— 从空目录到能出片 |
| **10 张预置工作流** | 视频生成 / 文生图 / 图生视频 / 多镜头分镜 / 2K 放大 |
| **2 个自研 ComfyUI 节点** | 结构化提示词、视频取末帧（89 行） |
| **5 份中文文档** | 部署方案 1427 行 + 使用手册 1205 行 + 三份专题 |
| **实测数据** | 各分辨率/步数的真实耗时、内存占用、画质对比 |
| **模型解耦** | 模型独立存放，可与多个部署共享，不必重复下载 177 GB |

---

## 快速开始

~~~bash
git clone git@github.com:cuijfboy/minimax_h3_on_m1_max.git
cd minimax_h3_on_m1_max

# 全部部署（会下载约 177 GB 模型）
./deploy.sh

# 已经有模型？指给它，就不用重下
cp h3.conf.example h3.conf
# 编辑 h3.conf，填上 H3_MODEL_DIR / H3_TURBO_DIR / COMFY_MODELS_DIR
./deploy.sh --skip-models
~~~

部署完成后：

~~~bash
./cli/start-comfyui     # 主界面 → http://127.0.0.1:8188
./cli/h3studio          # 分镜板 → http://127.0.0.1:3000
./h3-models status      # 看模型状态
~~~

---

## 硬件要求

| | |
|---|---|
| **最低** | Apple Silicon Mac，**32 GB 统一内存**，250 GB 可用磁盘 |
| **本方案验证机** | M1 Max 32GB / macOS 26 |
| **为什么必须 32GB** | DiT 全驻留需 37–45 GiB，超过 Metal 单缓冲上限 18.7 GiB<br>→ 必须开 `--ssd-streaming`（本仓库的节点已默认开启） |

---

## 架构

~~~
┌──────────────────────────────────────────────────────────────┐
│                      ComfyUI  ← 主界面                        │
│                      http://127.0.0.1:8188                    │
│                                                              │
│   ┌─ 视频 ────────────────────────────────────────────┐       │
│   │ h3-local-draft      864×480   23 分钟  免费        │       │
│   │ h3-local-quality    1344×768  92 分钟  免费        │       │
│   │ h3-full-chain       一句话 → 2K   100 分钟  $0.02   │       │
│   │ h3-storyboard-3shot 三镜接力 + 拼接  91 分钟 免费    │       │
│   └──────────────────────────────────────────────────┘       │
│   ┌─ 图片 ────────────────────────────────────────────┐       │
│   │ image-t2i-turbo     1024² × 4   7 分钟   免费      │       │
│   │ image-keyframe-…    1344×768 × 4  7 分钟  免费      │       │
│   │ image-upscale-2k    1024² → 2048²  2 秒   免费      │       │
│   │ image-to-video      图 → 视频 → 2K  95 分钟         │       │
│   └──────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │  H3 Studio（:3000）        │
              │  多镜头分镜板 / 断点续跑     │
              └───────────────────────────┘
~~~

### 模型与代码分离

~~~
H3_MODELS_HOME  (~/minimax-h3-models)     ← 177 GB 权重，可放外置盘
├── MiniMax-H3/          原始权重
├── MiniMax-H3-turbo/    折叠权重（提速 1.71×）
├── loras/
└── comfy/               Z-Image 文生图相关

H3_ROOT  (~/minimax-h3)                   ← 纯代码，删了也不丢模型
├── ComfyUI/  h3.c/  h3.c-studio/
└── models/                              ← 符号链接指向模型仓库
~~~

两者通过**配置文件**或**符号链接**绑定，互为备份。详见
[`docs/06-model-layout.md`](docs/06-model-layout.md)。

---

## 实测数据

### 视频生成（864×480，6 步 Turbo）

| 帧数 | 时长 | 耗时 |
|---|---|---|
| 124 | 5.17 s | 约 23 分钟 |
| 192 | 8.00 s | 约 41 分钟 |
| **440（三镜）** | 18.33 s | **91 分钟** |

**约 12 秒/帧。**

### 分辨率对比（124 帧 / 6 步）

| 分辨率 | 耗时 | 峰值内存 | Swap |
|---|---|---|---|
| 864×480 | 23 分钟 | — | 0 |
| 1344×768 | **92 分钟** | 12.71 GB | **0** |

### 文生图（Z-Image）

| 配置 | 耗时 | 单张 |
|---|---|---|
| Turbo 1024² / 8 步 / batch 1 | **104.5 s** | 1.7 分钟 |
| Turbo 1024² / 8 步 / batch 4 | **426.6 s** | 1.8 分钟 |
| base 1024² / 25 步 / CFG4 | 696.1 s | 11.6 分钟 |

> **批量不省时间** —— batch 4 就是 batch 1 的 4 倍。批量的价值是"一次拿 4 个候选"。

### 2K 放大（1024² → 2048²）

| 方案 | 耗时 | 拉普拉斯方差 |
|---|---|---|
| 原图 | — | 131.9 |
| **纯 RealESRGAN** | **2.0 s** | **298.0（2.26×）** |
| 官方模板（含 Z-Image 精修） | 477 s | 122.7（0.93×） |

> 官方模板的精修步会把放大器的成果磨平。本仓库默认走纯放大。

---

## 实测中发现的问题（都已修掉）

| 问题 | 现象 | 根因 |
|---|---|---|
| 32GB 必 OOM | 不加 `--ssd-streaming` 直接失败 | DiT 需 37–45 GiB > Metal 上限 18.7 GiB |
| 着色器找不到 | `cannot compile h3_shaders.metal` | h3.c 用 CWD 相对路径找 `.metal` |
| ComfyUI 拒绝符号链接 | `Invalid video file` | `exists_annotated_filepath()` 的 realpath 包含检查 |
| DynamicCombo 参数报错 | `missing 1 required argument: 'model'` | API 格式需展开成 `model` + `model.prompt` |
| 混元节点缺参 | `required input is missing: watermark` | `watermark` 是顶层输入，不该加 `model.` 前缀 |
| 连线槽位错位 | 多输入节点连错 | 未按实际 `inputs` 数组索引计算 |
| 2K 拒绝小视频 | `area 262144 is below min 589824` | 官方要求 ≥768×768 |
| 2K 拒绝短帧 | `length is 107 to 362 frames in steps of 17` | 官方帧数网格与本地不同 |
| Z-Image base 背景糊 | 官方模板 CFG=4 过高 | 改成 CFG 2 后恢复 |

---

## 目录

~~~
├── deploy.sh              一键部署
├── h3-models              模型管理（status / verify / bind / paths）
├── h3.conf.example        配置模板
├── config/
│   └── models.manifest.json   模型校验基线
├── docs/
│   ├── 01-deployment.md        部署方案（1427 行，含全部实测与原理）
│   ├── 02-usage-manual.md      使用手册（1205 行，GUI 手把手）
│   ├── 03-text-to-image.md     文生图方案
│   ├── 04-gui-fusion.md        GUI 融合方案
│   ├── 05-gui-fusion-phase2.md GUI 融合二期评估
│   ├── 06-model-layout.md      模型解耦与共享
│   └── 07-videoGen-工具链.md   清空重建部署记录（容器布局 / 补丁清单 / 验证实测）
├── workflows/             10 张工作流（UI 格式）+ api/（API 格式）
├── scripts/               工作流生成器、模型下载、校验
├── cli/                   h3gen / comfy-contextir / comfy-2k / start-comfyui / h3studio
├── custom_nodes/h3-toolkit/   自研节点
├── patches/               第三方节点补丁说明
└── benchmarks/            实测原始日志
~~~

---

## 命令行

~~~bash
# 本地生成（免费）
./cli/h3gen "一只红狐狸走过雪地" draft      # 864×480, 23 分钟
./cli/h3gen "..." quality                   # 1344×768, 92 分钟

# 官方 API（收费）
./cli/comfy-contextir "中文想法" > prompt.txt   # 提示词增强，$0.02
./cli/comfy-2k 视频.mp4 "$(cat prompt.txt)"    # 2K 再生成

# 模型管理
./h3-models status
./h3-models verify
./h3-models bind
~~~

---

## 已知限制

- **只在 M1 Max 32GB 上验证过**。其它 Apple Silicon 应该也能跑，但参数可能需要调。
- **官方节点需要 API 密钥**（提示词增强 / 2K 再生成）。本地生成不需要。
  `deploy.sh` 不会自动写入密钥，只给提示。
- **ComfyUI 的图是原子执行的** —— 中途无法暂停续跑。需要断点续跑请用 H3 Studio。
- **三镜串联要 91 分钟**，失败代价高。建议先用 draft 参数验证分镜，再跑成品。

---

## 许可

自研部分 [MIT](LICENSE)。第三方组件（MiniMax H3 / ComfyUI / h3.c / Z-Image 等）
**不含在本仓库内**，各自遵循其原始许可，详见 [LICENSE](LICENSE#L25)。
