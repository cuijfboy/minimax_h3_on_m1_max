# GUI 融合方案：把本地 h3.c 接入 ComfyUI

> ✅ **已执行完成**（P1–P5 全部验收）· 执行结果见本节，原评估报告见下方

---

## ✅ 执行结果（2026-10-03 完成）

### 最终验证：单图跑完整链路，一次 Run 出 2K

**在 ComfyUI 里加载一张工作流，Run 一次，100 分 33 秒后得到 2K 成片。**

| 阶段 | 节点 | 耗时 |
|---|---|---|
| ① 官方提示词增强 | MinimaxHailuo03ContextIRNode | 约 3 分钟（$0.02） |
| ② 本地生成 1344×768 | WildH3TextToVideo | 约 92 分钟（免费） |
| ③ 官方 2K 再生成 | MinimaxHailuo03RegenerateNode | 约 5 分钟（官方计费） |
| ④ 保存 | SaveVideo | 秒级 |
| **总计** | | **6033 秒 = 100 分 33 秒** |

**产物规格**：2560×1440 / h264 / 24 fps / 5.167 s / AAC 立体声 32 kHz / 5.48 MB

### 各阶段验收

| # | 阶段 | 结果 |
|---|---|---|
| P1 | 安装与适配 | ✅ 节点注册（972 个）；`ssd_streaming` 默认值已改 True |
| P2 | 冒烟验证 | ✅ 512×512 出片，命令行确认含 `--ssd-streaming` |
| P3 | 三张工作流 | ✅ UI + API 双格式，ComfyUI 已识别，4 条连线槽位正确 |
| P4 | 全链路实测 | ✅ **单图 Run 出 2K，6033 秒** |
| P5 | 手册改版 | ✅ [MiniMax-H3-使用手册.md](MiniMax-H3-使用手册.md) 重写为 GUI 为主（673 行，5 个手把手演练） |

### 过程中发现并修复的问题

| # | 问题 | 根因 | 解法 |
|---|---|---|---|
| 1 | API JSON 报 `missing 1 required positional argument: 'model'` | DynamicCombo 未展开为 `model` + `model.prompt` | 修正生成器 |
| 2 | 报 `required input is missing: watermark` | 误把顶层输入当嵌套，加了 `model.` 前缀 | 增加 `DC_NESTED` 区分嵌套/顶层 |
| 3 | 连线槽位全为 0，多输入节点错位 | 未按实际 `inputs` 数组索引计算 | 按 schema 顺序建槽并回填 |
| 4 | 新 ComfyUI 实例启动失败 | 旧实例仍占用 8188 端口 | `lsof` 找 PID 后强杀 |

### 意外收获：官方 API 返回的两条精确约束

比官方文档更精确，已写入手册与部署文档：

| 约束 | 原文 |
|---|---|
| **2K 帧数** | `length is 107 to 362 frames in steps of 17` |
| **2K 最小面积** | `base_video area 262144 is below min 589824 (768*768)` |

→ **864×480 不能送 2K**，必须 ≥768×768；**124 帧是本地与官方两个网格的唯一常用交集**。

### 交付物

| 项 | 路径 |
|---|---|
| 社区节点 + 5 行补丁 | `ComfyUI/custom_nodes/wild-h3c-comfyui/` |
| 三张预置工作流 | `ComfyUI/user/default/workflows/` |
| 自研工作流生成器 | `scripts/gen_workflows.py`（UI + API 双格式） |
| 最终成片 | `h3.c/outputs/final-chain-2k.mp4` |

---

## 原评估报告（供参考）
> 目标：把「本地生成」和「官方 API」两套 GUI 融合为单一界面，操作以 GUI 为主

---

## 0. 结论

**可行性：高。已有现成方案，且本机所有前置条件均已满足。**

| 问题 | 答案 |
|---|---|
| 能不能把 h3.c 做成 ComfyUI 节点？ | ✅ 能，社区已有实现 |
| 现成方案靠谱吗？ | ⚠️ 年轻但质量不错（★5，2026-09-24 更新，480 行代码，含测试） |
| 本机兼容吗？ | ✅ 逐项检查全部通过（见第 2 章） |
| 融合后能做什么？ | ⭐ **三个环节连成一张图，一次 Run 跑完全链路** |
| 代价是什么？ | 会失去 H3 Studio 的分镜板 / Take 管理（见第 4 章） |

**推荐方案：C —— ComfyUI 作为主界面，H3 Studio 保留为多镜头分镜工作台。**

---

## 1. 候选方案：skaiy/wild-h3c-comfyui

| 项 | 值 |
|---|---|
| 仓库 | `skaiy/wild-h3c-comfyui` |
| 描述 | MiniMax H3 video generation on Apple Silicon, powered by the h3.c Metal engine |
| 规模 | `nodes.py` 212 行 + `h3_runner.py` 268 行（含 `tests/`） |
| 活跃度 | 创建 2026-09-23，最后推送 2026-09-24，★5，0 未决 issue |
| 安装 | `git clone` 到 `ComfyUI/custom_nodes/`（或 Manager 搜 "Wild H3C"） |
| 配置 | `config.json`：`{"h3_binary": "...", "model_dir": "..."}` |

**提供的节点**：

| 节点 | node_id | 作用 |
|---|---|---|
| Wild H3 Text to Video | `WildH3TextToVideo` | 文生视频 / 首尾帧（FL2VA） |
| Wild H3 Reference to Video | `WildH3RefToVideo` | 参考生视频（Ref2VA） |

---

## 2. 可行性逐项检查（全部通过）

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | **是否支持 `--ssd-streaming`** | ✅ 是 | `h3_runner.py:160`、`nodes.py:127`（节点输入） |
| 2 | 该参数默认值 | ⚠️ **默认 `False`** | 本机 32GB 必须为 True，否则必然分配失败 → **需打补丁** |
| 3 | **着色器 CWD 问题** | ✅ **已自行解决** | `h3_runner.py:189` 设 `cwd=dirname(binary)`（比我们的 h3gen 还完善） |
| 4 | ComfyUI V3 schema 兼容 | ✅ | 本机 `comfy_api.latest.io` 有 `ComfyNode` / `Video` / `Video.Output` |
| 5 | 本机 ComfyUI 版本 | ✅ | commit `4266410`（2026-10-03），README 称验证于 0.37.0 |
| 6 | 输出类型能否接官方节点 | ✅ **可以** | 节点输出 `io.Video.Output`，与 Regenerate-2K 的 `video` 输入同为 VIDEO |
| 7 | 进度上报 | ✅ | `comfy.utils.ProgressBar`（按帧/步数） |
| 8 | 模型目录可配置 | ✅ | `model_dir` 可指向我们已折叠的 `MiniMax-H3-turbo` |
| 9 | 二进制路径可配置 | ✅ | `binary_path` / `config.json` |

### 节点完整输入

| 输入 | 类型 | 默认 | 本机取值 |
|---|---|---|---|
| `prompt` | STRING（多行） | — | — |
| `width` / `height` | INT（32 倍数） | 864 / 480 | 1344 / 768（成品） |
| `seconds` | FLOAT（0.25–15） | 2.0 | **5.17**（对应 124 帧） |
| `steps` | INT | 20 | **6**（Turbo 折叠后） |
| `preset` | COMBO | `balanced` | **`precise`**（=50 层 / reuse 1，Turbo 必须 reuse=1） |
| `seed` | INT | 42 | — |
| `token_reduction` | BOOL（高级） | False | 可选 |
| **`ssd_streaming`** | BOOL（高级） | **False** | **必须 True** ⚠️ |
| `binary_path` | STRING（高级） | 空 | `$H3_ROOT/h3.c/h3` |
| `model_dir` | STRING（高级） | 空 | `.../models/MiniMax-H3-turbo` |

> **注意 `seconds` 的坑**：节点用 `floor(seconds × 24 + 0.5)` 算帧数。填 `5.0` → 120 帧，不在 `17k+5` 网格上，h3 会向上吸附到 124。**建议直接填 `5.17`** 得到精确的 124 帧。

---

## 3. 融合后的效果（核心价值）

可以把三个环节连成**一张图**，点一次 Run 跑完整链路：

~~~
[中文粗略提示词]
      ↓
┌─────────────────────────┐
│ Context IR（官方 API）   │  $0.02
│ → 结构化专业提示词        │
└───────────┬─────────────┘
            ↓ STRING
┌─────────────────────────┐
│ Wild H3 Text to Video   │  本地 h3.c，免费
│ 1344×768 / 124帧 / 6步   │  ~91 分钟
└───────────┬─────────────┘
            ↓ VIDEO
┌─────────────────────────┐
│ Regenerate to 2K（官方） │  按官方计费
│ 2560×1440               │
└───────────┬─────────────┘
            ↓ VIDEO
       Save Video
~~~

**这是 CLI 做不到的** —— CLI 需要三步手动衔接、手工复制提示词和文件路径。

### 其他收益

- 单一界面，不必在 :3000 和 :8188 之间切换
- 工作流可**保存为 JSON**、复用、分享
- ComfyUI 的队列 / 历史 / 批量运行
- 未来可插入其他节点（超分、插帧、音频处理等）

---

## 4. 代价：会失去什么

| H3 Studio 独有功能 | 并入 ComfyUI 后 | 影响 |
|---|---|---|
| **分镜板**（多镜头卡片 + 自动末帧接力 + 一键拼接导出） | ❌ 无对应，需手工搭多个节点 | 🔴 大 |
| **版本历史 / Take 采用** | ❌ 无 per-shot take 管理 | 🟠 中 |
| **结构化提示词五字段**（场景/动作/镜头/风格/音效） | ❌ 无（但可用官方 Context-IR 代替，质量更好） | 🟢 小 |
| **参考集管理**（角色/场景/风格分类） | ❌ 无（退化为 LoadImage） | 🟠 中 |
| **分阶段进度**（文本编码→去噪→VAE） | ⚠️ 只有按帧的进度条 | 🟡 小 |
| **断点续跑**（`--checkpoint`/`--resume`） | ❌ 节点未暴露 | 🟠 中 |
| **任务持久化**（重启不丢） | ⚠️ ComfyUI 有队列历史，但不能续跑 | 🟡 小 |

**最大损失是分镜板** —— 如果你要做多镜头连贯叙事（角色一致性、镜头接力），H3 Studio 目前没有替代品。

---

## 5. 方案对比

| 方案 | 说明 | 优点 | 缺点 |
|---|---|---|---|
| **A. 全并入 ComfyUI** | 只用 ComfyUI，卸载/停用 H3 Studio | 真正单界面；全链路自动化 | 失去分镜板与 Take 管理 |
| **B. 保持双 GUI** | 维持现状 | 各取所长 | 两个界面（用户想避免的） |
| **C. ComfyUI 为主 + H3 Studio 保留** ⭐ | 日常全在 ComfyUI；需要多镜头分镜时才开 H3 Studio | 单界面为主；不丢能力 | 仍存在第二个界面（低频使用） |
| **D. 自研节点包装 h3gen** | 自己写节点，复用已验证的档位逻辑 | 完全可控；档位/进度贴合本机 | 约 250 行代码需自己维护，重复造轮子 |

**推荐 C**。理由：
- 满足"以 GUI 为主 + 单界面"的核心诉求（95% 的操作都在 ComfyUI）
- 不丢失分镜板这个独特能力（低频但不可替代）
- 实施成本最低（现成方案 + 小补丁）

---

## 6. 执行计划（待批准）

### Phase 1 — 安装与适配（约 30 分钟）

1. 克隆节点到 `ComfyUI/custom_nodes/wild-h3c-comfyui`
2. 写 `config.json`：`h3_binary` → `h3.c/h3`；`model_dir` → `models/MiniMax-H3-turbo`
3. **打补丁**：把 `ssd_streaming` 默认值改为 `True`（本机硬需求）
4. 重启 ComfyUI，确认两个节点注册成功

**✅ 验证点**：节点出现在 ComfyUI 节点列表中；`/object_info` 能查到 `WildH3TextToVideo`

### Phase 2 — 本地生成冒烟验证（约 10 分钟）

用 API 提交一张最小图：`WildH3TextToVideo` → `Save Video`，参数 512×512 / 22 帧 / 6 步 / preset=precise / ssd_streaming=true

**✅ 验证点**：产出可播放的 mp4（带立体声）；命令行确认含 `--ssd-streaming`；无 OOM

> ⚠️ 这一步是**关键风险点** —— 若失败，回退到方案 D（自研节点）

### Phase 3 — 搭三张工作流（约 40 分钟）

| 工作流 | 内容 | 用途 |
|---|---|---|
| `h3-local-draft.json` | Wild H3 → SaveVideo（864×480 / 124帧 / 6步） | 日常迭代，23 分钟 |
| `h3-local-quality.json` | Wild H3 → SaveVideo（1344×768 / 124帧 / 6步） | 成品，91 分钟 |
| **`h3-full-chain.json`** ⭐ | **Context-IR → Wild H3 → Regenerate-2K → SaveVideo** | 一键全链路 |

**✅ 验证点**：三张图都能加载、连线正确、参数已填好

### Phase 4 — 全链路实测（约 2 小时，含生成时间）

跑 `h3-full-chain.json`：中文想法 → 增强 → 本地 768P → 官方 2K

**✅ 验证点**：一次 Run 产出 2560×1440 成片，中途无需人工干预

### Phase 5 — 使用手册改版（约 1 小时）

按"**GUI 为主**"重写 [MiniMax-H3-使用手册.md](MiniMax-H3-使用手册.md)：

| 现在 | 改版后 |
|---|---|
| 第 3 章「命令行用法详解」在前 | 把 GUI 章节提到前面 |
| H3 Studio 与 ComfyUI 分成两章 | ComfyUI 作为主界面详述（含三张工作流的操作步骤） |
| — | H3 Studio 降为"进阶：多镜头分镜"一节 |
| CLI 内容 | 保留但移到附录，标注"适合批量/自动化" |

**✅ 验证点**：新用户按手册能纯 GUI 完成"想法 → 2K 成片"

### 总工作量

| 阶段 | 人工时间 | 机器时间 |
|---|---|---|
| Phase 1 安装适配 | 30 分钟 | — |
| Phase 2 冒烟验证 | 10 分钟 | 2 分钟 |
| Phase 3 工作流搭建 | 40 分钟 | — |
| Phase 4 全链路实测 | 20 分钟 | ~2 小时 |
| Phase 5 手册改版 | 1 小时 | — |
| **合计** | **约 2.5 小时** | **约 2 小时**（可并行） |

---

## 7. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 节点在本机跑不通（32GB / Turbo 模型兼容性） | 🟠 中 | Phase 2 冒烟验证先行；失败则回退方案 D（自研节点包装已验证的 `h3gen`） |
| `ssd_streaming` 默认 False 被遗忘 | 🔴 高 | 直接改源码默认值 + 在工作流里显式勾选（双保险） |
| Turbo 模型要求 `reuse=1`，preset 可能覆盖 | 🟠 中 | 固定用 `preset=precise`（50 层 / reuse 1），与 Turbo 要求一致 |
| 91 分钟的单节点阻塞 ComfyUI 队列 | 🟡 低 | 单用户场景可接受；生成期间不排队其他任务 |
| 节点项目年轻（★5，创建仅 1 天） | 🟠 中 | 代码仅 480 行，可自行维护；已读源码确认无隐患 |
| 融合后失去分镜板能力 | 🟠 中 | 方案 C：保留 H3 Studio 作为低频工具 |
| `seconds` 与帧数网格不一致 | 🟡 低 | 统一填 `5.17`（→124 帧） |

---

## 8. 附：为什么不选「把 ComfyUI 接进 H3 Studio」

反向融合（改造 H3 Studio 去调 ComfyUI 的 API 节点）需要：
- Fork 并修改 H3 Studio 的 React 前端 + FastAPI 后端
- 自己实现 API 节点的鉴权、轮询、文件上传下载
- 跟随上游更新维护（H3 Studio 迭代快）

**工作量远大于正向融合，且要动第三方仓库源码。不推荐。**

而正向融合只需：克隆一个 480 行的现成节点 + 改 1 行默认值。

---

*本方案基于 2026-10-03 的源码调研撰写。所有结论均附代码行号出处，未执行任何修改。*
