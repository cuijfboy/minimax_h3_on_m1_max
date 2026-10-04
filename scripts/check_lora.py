import os
import json, struct
from pathlib import Path
H3_MODELS_HOME = Path(os.environ.get("H3_MODELS_HOME", Path.home() / "minimax-h3-models"))
CKPT = H3_MODELS_HOME / "MiniMax-H3" / "FL2VA" / "transformer"
LORA = str(H3_MODELS_HOME / "loras" / "minimax_h3_turbo_v4_step600_ema.safetensors")
def header(p):
    with open(p,"rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n))
ck = set()
for s in sorted(CKPT.glob("*.safetensors")):
    ck |= {k for k in header(s) if k != "__metadata__"}
lh = header(LORA)
targets = {k[:-len(".lora_A.weight")] for k in lh if k.endswith(".lora_A.weight")}
ok = [t for t in targets if t + ".weight" in ck]
bad = sorted(t for t in targets if t + ".weight" not in ck)
print(f"LoRA 目标模块: {len(targets)}")
print(f"在 checkpoint 中找到 .weight: {len(ok)}")
print(f"缺失: {len(bad)}")
for b in bad[:8]: print("   MISSING:", b)
import collections
c = collections.Counter(t.split(".")[-1] for t in ok)
print("按类型统计:", dict(c))
