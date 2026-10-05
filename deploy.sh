#!/usr/bin/env bash
# deploy.sh — 一键部署 MiniMax H3 到 Apple Silicon Mac
#
# 用法：
#   ./deploy.sh                      全部阶段
#   ./deploy.sh --skip-models        跳过模型下载（用已有模型）
#   ./deploy.sh --stage check,deps   只跑指定阶段
#   ./deploy.sh --config my.conf     指定配置文件
#   ./deploy.sh --list               列出所有阶段
#
# 配置见 h3.conf.example。核心思路：模型放在独立的 H3_MODELS_HOME，
# 部署目录只有代码；两者通过配置文件或符号链接接起来。

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ──────────────────────────────── 日志

if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_DIM=$'\033[2m'; C_OK=$'\033[32m'
  C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_HDR=$'\033[1;36m'
else
  C_RESET=; C_DIM=; C_OK=; C_WARN=; C_ERR=; C_HDR=
fi

say()   { printf '%s\n' "$*"; }
info()  { printf '%s→%s %s\n' "$C_DIM" "$C_RESET" "$*"; }
ok()    { printf '%s✓%s %s\n' "$C_OK" "$C_RESET" "$*"; }
warn()  { printf '%s!%s %s\n' "$C_WARN" "$C_RESET" "$*" >&2; }
die()   { printf '%s✗%s %s\n' "$C_ERR" "$C_RESET" "$*" >&2; exit 1; }
hdr()   { printf '\n%s══ %s ══%s\n' "$C_HDR" "$*" "$C_RESET"; }

# ──────────────────────────────── 参数

STAGES="check,deps,comfyui,engine,studio,models,fold,nodes,workflows"
SKIP_MODELS=0
LIST=0
CONF_ARG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --stage)       STAGES="$2"; shift 2 ;;
    --skip-models) SKIP_MODELS=1; shift ;;
    --config)      CONF_ARG="$2"; shift 2 ;;
    --list)        LIST=1; shift ;;
    -h|--help)     sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)             die "未知参数: $1（用 --help 看用法）" ;;
  esac
done

if [ "$LIST" = 1 ]; then
  say "可用阶段："
  echo "$STAGES" | tr ',' '\n' | sed 's/^/    /'
  exit 0
fi

# ──────────────────────────────── 配置

CONF="${CONF_ARG:-${H3_CONF:-$REPO/h3.conf}}"
if [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF"
  info "已加载配置 $CONF"
fi

H3_ROOT="${H3_ROOT:-$HOME/minimax-h3}"
H3_MODELS_HOME="${H3_MODELS_HOME:-$HOME/minimax-h3-models}"
MODEL_BINDING="${MODEL_BINDING:-auto}"
AUTO_DOWNLOAD_MODELS="${AUTO_DOWNLOAD_MODELS:-1}"
VERIFY_MODELS="${VERIFY_MODELS:-1}"
TURBO_DIR="${H3_TURBO_DIR:-}"

export H3_ROOT H3_MODELS_HOME MODEL_BINDING AUTO_DOWNLOAD_MODELS VERIFY_MODELS
export H3_MODEL_DIR="${H3_MODEL_DIR:-}"
export H3_TURBO_DIR="$TURBO_DIR"
export COMFY_MODELS_DIR="${COMFY_MODELS_DIR:-}"
export MODEL_SEARCH_PATHS="${MODEL_SEARCH_PATHS:-}"
# pip 源。国内镜像对 torch 这类大包的覆盖不一（USTC/清华实测 403），默认用官方源
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple/}"
export PIP_INDEX_URL
# GitHub 代理（国内直连 github 往往很慢或不通）。留空则直连。
# 例：GH_PROXY=https://gh-proxy.com/ ./deploy.sh
GH_PROXY="${GH_PROXY:-}"
export GH_PROXY
gh_url() { printf '%shttps://github.com/%s' "$GH_PROXY" "$1"; }

MODELS_PY="$REPO/scripts/h3_models.py"
COMFY="$H3_ROOT/ComfyUI"
PY312="$(brew --prefix python@3.12 2>/dev/null || echo /opt/homebrew/opt/python@3.12)/bin/python3.12"

want() { case ",$STAGES," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
have() { command -v "$1" >/dev/null 2>&1; }

# ──────────────────────────────── 阶段 0：环境预检

stage_check() {
  hdr "环境预检"
  [ "$(uname -s)" = "Darwin" ] || die "本方案面向 macOS，当前是 $(uname -s)"
  [ "$(uname -m)" = "arm64" ]  || die "需要 Apple Silicon（M 系列），当前是 $(uname -m)"

  local mem_gb disk_gb
  mem_gb=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  ok "macOS $(sw_vers -productVersion) / $(uname -m) / ${mem_gb} GB 内存"
  [ "$mem_gb" -ge 32 ] || warn "少于 32 GB 内存，可能跑不动（本项目在 M1 Max 32GB 上验证）"

  mkdir -p "$H3_ROOT"
  disk_gb=$(df -g "$H3_ROOT" | awk 'NR==2 {print $4}')
  ok "部署目录 ${H3_ROOT}（可用 ${disk_gb} GB）"

  if [ "$SKIP_MODELS" = 0 ] && [ "$AUTO_DOWNLOAD_MODELS" = 1 ]; then
    if [ "$disk_gb" -lt 250 ]; then
      die "磁盘不足：下载模型需要 ≥250 GB，当前 ${disk_gb} GB
   可以：① 设 H3_MODELS_HOME 指向有空间的卷
         ② 用 --skip-models 复用已有模型"
    fi
    ok "磁盘空间满足模型需求（≥250 GB）"
  fi
}

# ──────────────────────────────── 阶段 1：依赖

stage_deps() {
  hdr "系统依赖"
  have brew || die "未找到 Homebrew，请先安装：https://brew.sh"
  ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"

  # python 必须是 3.12（ComfyUI 依赖需要 PEP 604 语法）
  if [ -x "$PY312" ]; then
    ok "python3.12 已可用"
  else
    info "安装 python@3.12 …"
    brew install python@3.12 || die "安装 python@3.12 失败"
  fi
  [ -x "$PY312" ] || die "找不到 python3.12：$PY312"

  # 其余工具只要在 PATH 上就行，不强制用 brew 装的
  local tool
  for tool in cmake node ffmpeg; do
    if have "$tool"; then
      ok "$tool 已在 PATH（$(command -v "$tool")）"
    else
      info "安装 $tool …"
      brew install "$tool" || die "安装 $tool 失败"
    fi
  done

  # cli/* 与 Studio 会把 $H3_ROOT/bin 前置到 PATH，这里把 ffmpeg/ffprobe 放进去
  mkdir -p "$H3_ROOT/bin"
  local b
  for b in ffmpeg ffprobe; do
    if [ -e "$H3_ROOT/bin/$b" ]; then
      ok "bin/$b 已就绪"
    elif have "$b"; then
      ln -s "$(command -v "$b")" "$H3_ROOT/bin/$b"
      ok "bin/$b → $(command -v "$b")"
    else
      warn "PATH 上没有 $b，bin/$b 未创建"
    fi
  done
}

# ──────────────────────────────── 阶段 2：ComfyUI

stage_comfyui() {
  hdr "ComfyUI"
  if [ -d "$COMFY/.git" ]; then
    ok "已存在 $COMFY"
  else
    info "clone ComfyUI …"
    git clone --depth 1 "$(gh_url comfyanonymous/ComfyUI.git)" "$COMFY" \
      || die "clone 失败（网络？）"
    ok "已 clone"
  fi

  if [ ! -x "$COMFY/.venv/bin/python" ]; then
    info "创建虚拟环境并安装依赖（几分钟）…"
    "$PY312" -m venv "$COMFY/.venv"
    "$COMFY/.venv/bin/pip" install -q --upgrade pip
    info "pip 源：${PIP_INDEX_URL}（torch 等大包约 2.5 GB，看网速可能要十几分钟）"
    "$COMFY/.venv/bin/pip" install -q -i "$PIP_INDEX_URL" -r "$COMFY/requirements.txt" \
      || die "pip 安装失败。可换源重试，例如：
       PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ ./deploy.sh --stage comfyui"
  fi
  ok "Python 依赖就绪"
}

# ──────────────────────────────── 阶段 3：h3.c 引擎

stage_engine() {
  hdr "h3.c 引擎（C + Metal）"
  if [ -x "$H3_ROOT/h3.c/h3" ]; then
    ok "已编译：$H3_ROOT/h3.c/h3"
    return
  fi
  if [ ! -d "$H3_ROOT/h3.c" ]; then
    info "clone h3.c …"
    git clone --depth 1 "$(gh_url antirez/h3.c.git)" "$H3_ROOT/h3.c" \
      || die "clone 失败（网络？）"
  fi
  info "编译 …"
  ( cd "$H3_ROOT/h3.c" && make ) || die "编译失败。若缺编译工具：xcode-select --install"
  ok "编译完成"
}

# ──────────────────────────────── 阶段 4：H3 Studio

stage_studio() {
  hdr "H3 Studio（多镜头分镜板）"
  local STUDIO="$H3_ROOT/h3.c-studio"

  if [ ! -d "$STUDIO" ]; then
    info "clone h3.c-studio …"
    git clone --depth 1 "$(gh_url skaiy/h3.c-studio.git)" "$STUDIO" \
      || die "clone 失败（网络？）"
  fi

  # 1) 引擎：上游仓库不含 h3 二进制，必须自己编译
  if [ -x "$STUDIO/h3" ]; then
    ok "Studio 引擎已编译"
  else
    info "编译 Studio 引擎（make）…"
    ( cd "$STUDIO" && make ) || die "编译失败。若缺编译工具：xcode-select --install"
  fi

  # 2) 32GB 机器必需：强制 --ssd-streaming（详见 patches/h3-c-studio.md）
  python3 "$REPO/scripts/patch_studio_ssd.py" "$STUDIO/studio/server/main.py" \
    || warn "Studio 补丁未打上 —— 分镜板生成时可能 OOM，见 patches/h3-c-studio.md"

  # 3) 前端依赖
  if [ -d "$STUDIO/studio/node_modules" ]; then
    ok "前端依赖已安装"
  else
    info "npm install …"
    ( cd "$STUDIO/studio" && npm install ) || die "npm install 失败"
  fi

  # 4) 后端依赖：早期 deploy.sh 遗漏，缺了 ./cli/h3studio 会直接报环境缺失
  if [ -x "$STUDIO/studio/server/.venv/bin/python" ]; then
    ok "后端依赖已安装"
  else
    info "创建后端 venv 并安装 fastapi / uvicorn …"
    "$PY312" -m venv "$STUDIO/studio/server/.venv" || die "创建后端 venv 失败"
    "$STUDIO/studio/server/.venv/bin/pip" install -q --upgrade pip
    "$STUDIO/studio/server/.venv/bin/pip" install -q -i "$PIP_INDEX_URL" \
      fastapi 'uvicorn[standard]' pydantic python-multipart \
      || die "后端依赖安装失败。可换源重试：
       PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ ./deploy.sh --stage studio"
  fi
  ok "H3 Studio 就绪"
}

# ──────────────────────────────── 阶段 5：模型

stage_models() {
  hdr "模型解析与校验"
  local paths
  if ! paths="$(python3 "$MODELS_PY" paths 2>/dev/null)"; then
    warn "有模型没找到。"
    if [ "$SKIP_MODELS" = 1 ] || [ "$AUTO_DOWNLOAD_MODELS" != 1 ]; then
      python3 "$MODELS_PY" status || true
      die "模型不齐，且已禁用自动下载。
   请在 h3.conf 里指定 H3_MODEL_DIR / H3_TURBO_DIR / COMFY_MODELS_DIR，
   或设 MODEL_SEARCH_PATHS 让脚本自己找。"
    fi
    info "开始下载 H3 权重到 ${H3_MODELS_HOME}（约 144 GB）…"
    H3_MODEL_DIR="$H3_MODELS_HOME/MiniMax-H3" \
      python3 "$REPO/scripts/h3_download.py" || die "H3 权重下载失败"
    paths="$(python3 "$MODELS_PY" paths)" || die "下载后仍解析不到模型"
  fi
  eval "$paths"
  ok "MiniMax-H3       → $H3_MODEL_DIR"
  ok "MiniMax-H3-turbo → $H3_TURBO_DIR"
  ok "ComfyUI 模型     → $COMFY_MODELS_DIR"

  if [ "$VERIFY_MODELS" = 1 ]; then
    python3 "$MODELS_PY" verify || warn "校验有问题（见上）。大小不符建议重新下载。"
  fi
}

# ──────────────────────────────── 阶段 6：Turbo 折叠

stage_fold() {
  hdr "Turbo LoRA 折叠（提速 1.71×）"
  if [ -n "$TURBO_DIR" ] && [ -d "$TURBO_DIR/FL2VA" ]; then
    ok "已折叠：$TURBO_DIR"
    return
  fi
  local lora="$H3_MODELS_HOME/loras/minimax_h3_turbo_v4_step600_ema.safetensors"
  if [ ! -f "$lora" ]; then
    warn "未找到 LoRA：$lora"
    warn "跳过折叠。部署仍可用，只是慢 1.71×（用 h3-local-draft / quality 工作流）。"
    return
  fi
  info "开始折叠（约 10 分钟，磁盘 +58 GB）…"
  H3_ROOT="$H3_ROOT" H3_MODELS_HOME="$H3_MODELS_HOME" bash "$REPO/scripts/chain_turbo.sh" \
    || warn "折叠失败，跳过（不影响基本使用）"
}

# ──────────────────────────────── 阶段 7：自定义节点

stage_nodes() {
  hdr "自定义节点"
  local cn="$COMFY/custom_nodes"
  mkdir -p "$cn"

  rm -rf "$cn/h3-toolkit"
  cp -R "$REPO/custom_nodes/h3-toolkit" "$cn/"
  ok "h3-toolkit（结构化提示词 + 取末帧）"

  if [ ! -d "$cn/wild-h3c-comfyui" ]; then
    info "clone wild-h3c-comfyui …"
    git clone --depth 1 "$(gh_url skaiy/wild-h3c-comfyui.git)" "$cn/wild-h3c-comfyui" \
      || die "clone 失败（网络？）"
  fi

  local nf="$cn/wild-h3c-comfyui/nodes.py"
  if [ -f "$nf" ]; then
    if grep -q 'ssd_streaming", default=False' "$nf"; then
      sed -i '' 's/ssd_streaming", default=False/ssd_streaming", default=True/' "$nf"
      ok "已打补丁：ssd_streaming 默认 True"
    else
      ok "补丁已生效（或上游已改默认值）"
    fi
  fi
}

# ──────────────────────────────── 阶段 8：绑定与工作流

stage_workflows() {
  hdr "模型绑定与工作流"
  python3 "$MODELS_PY" bind || warn "绑定有告警（见上）"

  mkdir -p "$COMFY/user/default/workflows"
  cp "$REPO"/workflows/*.json "$COMFY/user/default/workflows/"
  ok "已部署 $(ls "$REPO"/workflows/*.json | wc -l | tr -d ' ') 张工作流"

  if [ ! -f "$COMFY_MODELS_DIR/diffusion_models/z_image_turbo_bf16.safetensors" ]; then
    if [ "$SKIP_MODELS" = 1 ] || [ "$AUTO_DOWNLOAD_MODELS" != 1 ]; then
      warn "Z-Image 模型缺失 —— 文生图工作流不可用（视频工作流不受影响）"
    else
      info "下载 Z-Image 模型（约 33 GB）…"
      COMFY_MODELS_DIR="$COMFY_MODELS_DIR" python3 "$REPO/scripts/zimage_download.py" \
        || warn "Z-Image 下载失败，文生图不可用"
    fi
  else
    ok "Z-Image 模型已在位"
  fi

  if [ ! -f "$H3_ROOT/.comfy_api_key" ]; then
    warn "未配置 ComfyUI API 密钥 —— 官方节点（提示词增强 / 2K 再生成）不可用。"
    warn "  1. 到 https://platform.comfy.org/login 申请"
    warn "  2. 写入 $H3_ROOT/.comfy_api_key 并 chmod 600"
    warn "  本地生成工作流不需要密钥。"
  else
    ok "API 密钥已配置"
  fi
}

# ──────────────────────────────── 主流程

say ""
say "${C_HDR}MiniMax H3 部署${C_RESET}"
say "  部署目录  $H3_ROOT"
say "  模型仓库  $H3_MODELS_HOME"
say "  阶段      $STAGES"

want check     && stage_check
want deps      && stage_deps
want comfyui   && stage_comfyui
want engine    && stage_engine
want studio    && stage_studio
want models    && stage_models
want fold      && stage_fold
want nodes     && stage_nodes
want workflows && stage_workflows

hdr "完成"
say ""
say "  启动 ComfyUI    $REPO/cli/start-comfyui"
say "  启动 H3 Studio  $REPO/cli/h3studio"
say "  生成视频        $REPO/cli/h3gen \"一只红狐狸走过雪地\" draft"
say "  模型状态        $REPO/h3-models status"
say ""
say "  界面：ComfyUI http://127.0.0.1:8188   H3 Studio http://127.0.0.1:3000"
say "  文档：docs/02-usage-manual.md"
say ""
