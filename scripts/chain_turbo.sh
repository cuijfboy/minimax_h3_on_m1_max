#!/bin/bash
set -x
export PATH="${H3_ROOT:-$HOME/minimax-h3}/bin:$PATH"
ROOT="${H3_ROOT:-$HOME/minimax-h3}"
cd "$ROOT/h3.c"

echo "=== [1/4] 等待当前基准测试结束 ==="
while pgrep -x h3 > /dev/null; do sleep 20; done
echo "  当前基准已结束: $(date '+%H:%M:%S')"
grep -a "h3 profile:" "$ROOT/logs/bench-480p-124f.log" | sed 's/  */ /g' > "$ROOT/logs/bench-480p-profile.txt"
tail -25 "$ROOT/logs/bench-480p-124f.log" | tr '\r' '\n' | grep -a . | tail -20 >> "$ROOT/logs/bench-480p-profile.txt"

echo "=== [2/4] APFS 克隆建立 Turbo 模型目录 ==="
if [ ! -d "$ROOT/models/MiniMax-H3-turbo" ]; then
  cp -cR "$ROOT/models/MiniMax-H3" "$ROOT/models/MiniMax-H3-turbo" && echo "  克隆完成"
else
  echo "  已存在，跳过"
fi
df -h /System/Volumes/Data | tail -1

echo "=== [3/4] 折叠 Turbo LoRA 到 FL2VA/transformer ==="
"$ROOT/.venv/bin/python" "$ROOT/h3.c/tools/fold_turbo_lora.py" \
  --checkpoint "$ROOT/models/MiniMax-H3/FL2VA/transformer" \
  --lora "$ROOT/models/loras/minimax_h3_turbo_v4_step600_ema.safetensors" \
  --out "$ROOT/models/MiniMax-H3-turbo/FL2VA/transformer" > "$ROOT/logs/fold-turbo.log" 2>&1
echo "  折叠退出码=$?"
tail -15 "$ROOT/logs/fold-turbo.log"
df -h /System/Volumes/Data | tail -1

echo "=== [3.5/4] 校验折叠后的模型目录 ==="
./h3 --info -d "$ROOT/models/MiniMax-H3-turbo" 2>&1 | head -14

echo "=== [4/4] Turbo 对比基准: 864x480 / 124帧 / 6步 / reuse1 ==="
date '+开始: %H:%M:%S'
/usr/bin/time -l ./h3 --profile \
  -d "$ROOT/models/MiniMax-H3-turbo" \
  -p "A red fox walks through fresh snow in a pine forest. Medium tracking shot, natural winter light, realistic fur, soft footsteps and wind." \
  --width 864 --height 480 --frames 124 --steps 6 \
  --layers 50 --reuse 1 --ssd-streaming \
  -o outputs/bench-480p-turbo.mp4 > "$ROOT/logs/bench-480p-turbo.log" 2>&1
echo "  退出码=$?"
date '+结束: %H:%M:%S'
grep -a "h3 profile:" "$ROOT/logs/bench-480p-turbo.log" | sed 's/  */ /g'
echo "=== 链路完成 ==="
