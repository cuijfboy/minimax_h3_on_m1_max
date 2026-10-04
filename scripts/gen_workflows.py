#!/usr/bin/env python3
"""从同一份声明式规格生成 ComfyUI 的 UI 格式与 API 格式工作流。

UI 格式的 widget 顺序依据：
  · 参考官方模板 api_minimax_h3_flf2v.json 反向验证过约定
  · DynamicCombo 先输出选项 key，再按嵌套 schema 顺序输出基本类型 widget
  · socket 类型（IMAGE/VIDEO/AUDIO）不进 widgets_values
  · control_after_generate 的 INT 后面追加一个 "randomize"/"fixed"
"""
import json, uuid, copy, os, pathlib, urllib.request

ROOT = pathlib.Path(os.environ.get("H3_ROOT", pathlib.Path.home() / "minimax-h3"))

# 实时拉取节点定义，避免用过期的缓存导致 KeyError
with urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=30) as _r:
    OBJ = json.load(_r)

# ---- 各节点的 widget 顺序（硬编码，已按 object_info 核对）----------------
WIDGETS = {
    "WildH3TextToVideo": ["prompt", "width", "height", "seconds", "steps", "preset",
                          "seed", "@seed_ctrl", "token_reduction", "ssd_streaming",
                          "binary_path", "model_dir"],
    "SaveVideo": ["filename_prefix", "format", "codec"],
    "MinimaxHailuo03ContextIRNode": ["@dc:model", "prompt", "duration", "ratio"],
    "MinimaxHailuo03RegenerateNode": ["@dc:model", "prompt", "resolution"],
    # ---- 文生图（Z-Image）标准节点：顺序已按 object_info 核对 ----
    "UNETLoader": ["unet_name", "weight_dtype"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "VAELoader": ["vae_name"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    # sampling 是后加的 advanced COMBO（官方模板只有 1 个值），这里显式写 2 个
    "ModelSamplingAuraFlow": ["shift", "sampling"],
    "KSampler": ["seed", "@seed_ctrl", "steps", "cfg",
                 "sampler_name", "scheduler", "denoise"],
    "CLIPTextEncode": ["text"],
    "ConditioningZeroOut": [],
    "VAEDecode": [],
    "SaveImage": ["filename_prefix"],
    "PrimitiveStringMultiline": ["value"],
    # ---- 多镜头分镜所需节点 ----
    "GetVideoComponents": [],
    "ImageFromBatch": ["batch_index", "length"],
    "ConcatenateVideo": ["codec"],
    # ---- 自研 h3-toolkit 节点 ----
    "H3StructuredPrompt": ["scene", "action", "camera", "style", "sound", "extra"],
    "H3LastFrame": [],
    # ---- 2K 放大器 ----
    "LoadImage": ["image"],
    "UpscaleModelLoader": ["model_name"],
    "ImageUpscaleWithModel": [],
    "ImageScaleBy": ["upscale_method", "scale_by"],
    "VAEEncode": [],
}
# socket 输入 → 连线类型（这些不进 widgets_values）
SOCKET_INPUTS = {
    "WildH3TextToVideo": {"first_frame": "IMAGE", "last_frame": "IMAGE"},
    "SaveVideo": {"video": "VIDEO"},
    "MinimaxHailuo03ContextIRNode": {"first_frame": "IMAGE", "last_frame": "IMAGE"},
    "MinimaxHailuo03RegenerateNode": {"video": "VIDEO",
                                      "first_frame": "IMAGE", "last_frame": "IMAGE"},
    # ---- 文生图（Z-Image）标准节点 ----
    "UNETLoader": {},
    "CLIPLoader": {},
    "VAELoader": {},
    "EmptySD3LatentImage": {},
    "ModelSamplingAuraFlow": {"model": "MODEL"},
    "KSampler": {"model": "MODEL", "positive": "CONDITIONING",
                 "negative": "CONDITIONING", "latent_image": "LATENT"},
    "CLIPTextEncode": {"clip": "CLIP"},
    "ConditioningZeroOut": {"conditioning": "CONDITIONING"},
    "VAEDecode": {"samples": "LATENT", "vae": "VAE"},
    "SaveImage": {"images": "IMAGE"},
    "PrimitiveStringMultiline": {},
    # ---- 多镜头分镜所需节点 ----
    "GetVideoComponents": {"video": "VIDEO"},
    "ImageFromBatch": {"image": "IMAGE"},
    # ConcatenateVideo 的 videos 是 COMFY_AUTOGROW_V3，实测展开名为 videos.videoN
    "ConcatenateVideo": {"videos.video0": "VIDEO", "videos.video1": "VIDEO",
                         "videos.video2": "VIDEO", "videos.video3": "VIDEO",
                         "videos.video4": "VIDEO", "complete_audio": "AUDIO"},
    # ---- 自研 h3-toolkit 节点 ----
    "H3StructuredPrompt": {},
    "H3LastFrame": {"video": "VIDEO"},
    # ---- 2K 放大器 ----
    "LoadImage": {},
    "UpscaleModelLoader": {},
    "ImageUpscaleWithModel": {"upscale_model": "UPSCALE_MODEL", "image": "IMAGE"},
    "ImageScaleBy": {"image": "IMAGE"},
    "VAEEncode": {"pixels": "IMAGE", "vae": "VAE"},
}
DC_KEY = {"WildH3TextToVideo": None,
          "MinimaxHailuo03ContextIRNode": "MiniMax H3",
          "MinimaxHailuo03RegenerateNode": "MiniMax H3"}
# DynamicCombo 里面**嵌套**的参数（其余是该节点的顶层输入，如 watermark/video）
DC_NESTED = {
    "MinimaxHailuo03ContextIRNode": {"prompt", "duration", "ratio"},
    "MinimaxHailuo03RegenerateNode": {"prompt", "resolution"},
}


def widgets(node):
    vals = []
    for w in WIDGETS[node["type"]]:
        if w == "@dc:model":
            vals.append(DC_KEY[node["type"]])
        elif w == "@seed_ctrl":
            vals.append(node["params"].get("_seed_ctrl", "randomize"))
        elif w in node["params"]:
            vals.append(node["params"][w])
        else:
            vals.append(None)
    return vals


def input_slots(ct):
    """按 schema 顺序给出「可作为连线目标」的输入名列表。

    规则：
      · socket 类型（IMAGE/VIDEO/AUDIO/…）总是占一个槽
      · DynamicCombo 的嵌套输入里，socket 类型占槽，其余是 widget
      · 非 socket 的 top-level 输入（widget）默认不占槽，被转换时才追加到末尾

    返回 (固定槽列表, 可转换 widget 列表)
    """
    known = SOCKET_INPUTS.get(ct, {})
    info = OBJ[ct]["input"]
    allin = {**info.get("required", {}), **info.get("optional", {})}
    sockets, widgets_ = [], []
    for name, spec in allin.items():
        t = spec[0] if isinstance(spec, list) else spec
        extra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        if isinstance(t, str) and t.startswith("COMFY_DYNAMIC"):
            opts = extra.get("options", [])
            nested = list(opts[0]["inputs"]["required"].items()) if opts else []
            for nk, nspec in nested:
                nt = nspec[0]
                if isinstance(nt, str) and nt in SOCKET_TYPES:
                    sockets.append((f"model.{nk}", nt))
                else:
                    widgets_.append(f"model.{nk}")
        elif isinstance(t, str) and t.startswith("COMFY_AUTOGROW"):
            pass                                 # autogrow 容器；展开名由 SOCKET_INPUTS 显式给出
        elif isinstance(t, str) and t in SOCKET_TYPES:
            sockets.append((name, t))
        elif name in known:                      # 显式声明的 socket
            sockets.append((name, known[name]))
        elif not (t == "STRING" and extra.get("forceInput")):
            widgets_.append(name)
    # 追加「显式声明但 schema 里没有」的槽（如 autogrow 展开后的 videos.videoN）
    have = {n for n, _ in sockets}
    for k, t in known.items():
        if k not in have:
            sockets.append((k, t))
    return sockets, widgets_


SOCKET_TYPES = {"IMAGE", "VIDEO", "AUDIO", "LATENT", "MASK", "CLIP", "MODEL", "VAE",
                "CONDITIONING", "SAMPLER", "SIGMAS", "GUIDER", "NOISE", "CONTROL_NET",
                "STYLE_MODEL", "GLIGEN", "UPSCALE_MODEL", "CLIP_VISION"}


def ui_node(node, nid, pos, order, links_out, links_in):
    """生成 UI 格式节点，并返回 (节点, {输入名: 槽序号})"""
    ct = node["type"]
    otypes = OBJ[ct].get("output") or []
    onames = OBJ[ct].get("output_name") or []
    outlist = []
    for i, t in enumerate(otypes):
        nm = onames[i] if i < len(onames) else t
        outlist.append({"name": nm, "type": t, "links": links_out.get(i) or None})

    fixed, convertible = input_slots(ct)
    inlist, slot_of = [], {}
    for name, typ in fixed:
        base = name.split(".")[-1]
        entry = {"name": name, "type": typ, "link": links_in.get(name)}
        if base in ("first_frame", "last_frame"):
            entry["shape"] = 7
        slot_of[name] = len(inlist)
        inlist.append(entry)
    # 被转换的 widget 追加在末尾
    # 注意：DynamicCombo 嵌套项的全名是 "model.prompt"，而边规格里写的是 "prompt"，
    #       两种写法都要能对上，否则连线会找不到目标槽。
    for name in convertible:
        short = name.split(".")[-1]
        key = name if name in links_in else (short if short in links_in else None)
        if key is None:
            continue
        entry = {"name": name, "type": "STRING",
                 "widget": {"name": name}, "link": links_in[key]}
        slot_of[key] = len(inlist)
        slot_of[name] = len(inlist)
        inlist.append(entry)
    return {
        "id": nid, "type": ct, "pos": pos, "size": node.get("size", [380, 420]),
        "flags": {}, "order": order, "mode": 0,
        "inputs": inlist, "outputs": outlist,
        "properties": {"Node name for S&R": ct},
        "widgets_values": widgets(node),
    }, slot_of


def build(spec, name):
    """spec: {"nodes":[{id,type,pos,params,size?}], "edges":[(from_id, from_slot, to_node, to_input)]}"""
    nodes = {n["id"]: n for n in spec["nodes"]}
    links_out, links_in = {}, {}
    for i, (src, slot, dst, inp) in enumerate(spec["edges"], start=1):
        links_out.setdefault(src, {})[slot] = [i]
        links_in.setdefault(dst, {})[inp] = i
    # 先建节点拿到真实槽序号，再回填 links
    built, slot_maps, by_id = [], {}, {}
    for order, n in enumerate(spec["nodes"]):
        node_json, slot_of = ui_node(n, n["id"], n["pos"], order,
                                     links_out.get(n["id"], {}), links_in.get(n["id"], {}))
        built.append(node_json)
        slot_maps[n["id"]] = slot_of
        by_id[n["id"]] = node_json
    links = []
    for i, (src, slot, dst, inp) in enumerate(spec["edges"], start=1):
        tslot = slot_maps[dst].get(inp)
        if tslot is None:
            raise SystemExit(f"❌ 边 {src}->{dst}.{inp} 找不到目标槽（{list(slot_maps[dst])}）")
        # 连线类型直接取目标输入槽声明的类型（MODEL/CLIP/CONDITIONING/LATENT/IMAGE/VIDEO…）
        typ = by_id[dst]["inputs"][tslot]["type"]
        links.append([i, src, slot, dst, tslot, typ])
    ui_nodes = built
    maxid = max(nodes) if nodes else 0
    wf = {"id": str(uuid.uuid4()), "revision": 0,
          "last_node_id": maxid, "last_link_id": len(links),
          "nodes": ui_nodes, "links": links, "groups": [], "config": {},
          "extra": {"ds": {"scale": 0.85, "offset": [0, 0]}, "frontendVersion": "1.53.10"},
          "version": 0.4}
    # API 格式（同一份规格）
    # 注意：DynamicCombo 节点在 API 格式里必须展开为
    #   "model": "<选项 key>"  +  "model.<嵌套输入>": <值>
    # 这是实测确认的（写错会报 missing 1 required positional argument: 'model'）
    api = {}
    for n in spec["nodes"]:
        ct = n["type"]
        raw = {k: v for k, v in n["params"].items() if k != "_seed_ctrl"}
        if DC_KEY.get(ct):
            nested = DC_NESTED.get(ct, set())
            inp = {"model": DC_KEY[ct]}
            for k, v in raw.items():
                inp[f"model.{k}" if k in nested else k] = v
        else:
            inp = dict(raw)
        for (src, slot, dst, name) in spec["edges"]:
            if dst == n["id"]:
                key = f"model.{name}" if name in DC_NESTED.get(ct, set()) else name
                inp[key] = [str(src), slot]
        api[str(n["id"])] = {"class_type": ct, "inputs": inp}
    return wf, api, name


H3_COMMON = {"token_reduction": False, "ssd_streaming": True,
             "binary_path": "", "model_dir": ""}
PROMPT = ("A red fox walks through fresh snow in a pine forest. Medium tracking shot, "
          "natural winter light, realistic fur, soft footsteps and wind.")

SPECS = [
    ("h3-local-draft", {
        "nodes": [
            {"id": 1, "type": "WildH3TextToVideo", "pos": [80, 120], "size": [440, 460],
             "params": {"prompt": PROMPT, "width": 864, "height": 480, "seconds": 5.17,
                        "steps": 6, "preset": "precise", "seed": 42, **H3_COMMON}},
            {"id": 2, "type": "SaveVideo", "pos": [600, 200], "size": [400, 300],
             "params": {"filename_prefix": "h3-local-draft", "format": "auto", "codec": "auto"}},
        ],
        "edges": [(1, 0, 2, "video")],
    }),
    ("h3-local-quality", {
        "nodes": [
            {"id": 1, "type": "WildH3TextToVideo", "pos": [80, 120], "size": [440, 460],
             "params": {"prompt": PROMPT, "width": 1344, "height": 768, "seconds": 5.17,
                        "steps": 6, "preset": "precise", "seed": 42, **H3_COMMON}},
            {"id": 2, "type": "SaveVideo", "pos": [600, 200], "size": [400, 300],
             "params": {"filename_prefix": "h3-local-quality", "format": "auto", "codec": "auto"}},
        ],
        "edges": [(1, 0, 2, "video")],
    }),
    ("h3-full-chain", {
        "nodes": [
            {"id": 1, "type": "MinimaxHailuo03ContextIRNode", "pos": [60, 100], "size": [460, 380],
             "params": {"prompt": "一只红狐狸在雪地里走过，镜头跟着它，冬天清晨的光线，能听到风声和踩雪的声音",
                        "duration": 5, "ratio": "16:9"}},
            {"id": 2, "type": "WildH3TextToVideo", "pos": [600, 100], "size": [440, 460],
             "params": {"prompt": "(由 Context-IR 自动填入)", "width": 1344, "height": 768,
                        "seconds": 5.17, "steps": 6, "preset": "precise", "seed": 42, **H3_COMMON}},
            {"id": 3, "type": "MinimaxHailuo03RegenerateNode", "pos": [1120, 100], "size": [440, 340],
             "params": {"prompt": "(由 Context-IR 自动填入)", "resolution": "2K", "watermark": False}},
            {"id": 4, "type": "SaveVideo", "pos": [1640, 150], "size": [400, 300],
             "params": {"filename_prefix": "h3-2k-final", "format": "auto", "codec": "auto"}},
        ],
        # 关键：增强提示词同时喂给「本地生成」和「2K 再生成」
        # （官方要求 2K 的 prompt 必须与生成原片时完全一致）
        "edges": [(1, 0, 2, "prompt"), (1, 0, 3, "prompt"),
                  (2, 0, 3, "video"), (3, 0, 4, "video")],
    }),
]

# ==========================================================================
#                        文生图（Z-Image）
# ==========================================================================
IMG_PROMPT = ("A red fox walking through fresh snow in a larch forest, "
              "golden winter morning light, shallow depth of field, "
              "photorealistic wildlife photography")
VID_PROMPT = ("Medium tracking shot follows the red fox as it walks through "
              "fresh snow, camera moving with it. Soft crunch of paws on snow, "
              "gentle wind, distant birds. Natural winter morning light.")
TURBO_DIT = "z_image_turbo_bf16.safetensors"
BASE_DIT = "z_image_bf16.safetensors"


def z_loaders(unet):
    """Z-Image 的三个加载器节点（所有文生图工作流共用）。"""
    return [
        {"id": 1, "type": "UNETLoader", "pos": [40, 60], "size": [420, 90],
         "params": {"unet_name": unet, "weight_dtype": "default"}},
        {"id": 2, "type": "CLIPLoader", "pos": [40, 200], "size": [420, 130],
         "params": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2",
                    "device": "default"}},
        {"id": 3, "type": "VAELoader", "pos": [40, 380], "size": [420, 80],
         "params": {"vae_name": "ae.safetensors"}},
    ]


def z_sampler_chain(steps, cfg, width, height, batch, prefix, x0=520):
    """CLIPTextEncode → ZeroOut → Latent → AuraFlow → KSampler → VAEDecode → SaveImage"""
    return [
        {"id": 4, "type": "CLIPTextEncode", "pos": [x0, 60], "size": [400, 180],
         "params": {"text": IMG_PROMPT}},
        {"id": 5, "type": "ConditioningZeroOut", "pos": [x0, 280], "size": [400, 60],
         "params": {}},
        {"id": 6, "type": "EmptySD3LatentImage", "pos": [x0, 380], "size": [400, 110],
         "params": {"width": width, "height": height, "batch_size": batch}},
        {"id": 7, "type": "ModelSamplingAuraFlow", "pos": [x0, 530], "size": [400, 100],
         "params": {"shift": 3.0, "sampling": "flow"}},
        {"id": 8, "type": "KSampler", "pos": [x0 + 480, 60], "size": [400, 320],
         "params": {"seed": 42, "steps": steps, "cfg": cfg,
                    "sampler_name": "res_multistep", "scheduler": "simple",
                    "denoise": 1.0}},
        {"id": 9, "type": "VAEDecode", "pos": [x0 + 480, 420], "size": [400, 60],
         "params": {}},
        {"id": 10, "type": "SaveImage", "pos": [x0 + 480, 520], "size": [400, 480],
         "params": {"filename_prefix": prefix}},
    ]


Z_BASE_EDGES = [(2, 0, 4, "clip"), (4, 0, 5, "conditioning"), (1, 0, 7, "model"),
                (7, 0, 8, "model"), (4, 0, 8, "positive"), (5, 0, 8, "negative"),
                (6, 0, 8, "latent_image"), (8, 0, 9, "samples"), (3, 0, 9, "vae"),
                (9, 0, 10, "images")]

SPECS += [
    # ---- #1 Turbo 概念图：8 步 / 1024² / batch 4 ----
    ("image-t2i-turbo", {
        "nodes": z_loaders(TURBO_DIT) + z_sampler_chain(8, 1.0, 1024, 1024, 4,
                                                        "z-image-turbo"),
        "edges": Z_BASE_EDGES,
    }),
    # ---- #2 base 实验档：25 步 / CFG 2 / 1024² / batch 1 ----
    # ⚠️ 实测结论：
    #    · 官方模板给的 CFG=4 **过高** → 背景糊成一片、毛发简化
    #    · 改用 CFG=2 后背景结构恢复（能看到树干），画质明显改善
    #    · 但即便 CFG=2，锐度仍不如 Turbo，且慢 6.6 倍 → 定位为实验档
    #    · CFG≠1 时每步要跑两次前向，所以 CFG2 与 CFG4 耗时相同（约 26s/步）
    ("image-t2i-base", {
        "nodes": z_loaders(BASE_DIT) + z_sampler_chain(25, 2.0, 1024, 1024, 1,
                                                       "z-image-base"),
        "edges": Z_BASE_EDGES,
    }),
    # ---- #3 视频首帧：8 步 / 1344×768（与视频画布一致）/ batch 4 ----
    ("image-keyframe-for-video", {
        "nodes": z_loaders(TURBO_DIT) + z_sampler_chain(8, 1.0, 1344, 768, 4,
                                                        "z-image-keyframe"),
        "edges": Z_BASE_EDGES,
    }),
    # ---- #4 图 → 视频：出图 → Wild H3 首帧 → 官方 2K → 保存 ----
    # 关键：用 PrimitiveStringMultiline 把「视频提示词」同时喂给
    #       Wild H3 和 Regenerate，保证官方要求的「提示词完全一致」
    ("image-to-video", {
        "nodes": z_loaders(TURBO_DIT)
        + z_sampler_chain(8, 1.0, 1344, 768, 1, "z-image-keyframe")
        + [
            {"id": 11, "type": "PrimitiveStringMultiline", "pos": [x, 1080],
             "size": [420, 160], "params": {"value": VID_PROMPT}}
            for x in [40]
        ] + [
            {"id": 12, "type": "WildH3TextToVideo", "pos": [1480, 60], "size": [440, 460],
             "params": {"prompt": VID_PROMPT, "width": 1344, "height": 768,
                        "seconds": 5.17, "steps": 6, "preset": "precise", "seed": 42,
                        **H3_COMMON}},
            {"id": 13, "type": "MinimaxHailuo03RegenerateNode", "pos": [2000, 60],
             "size": [440, 260],
             "params": {"prompt": VID_PROMPT, "resolution": "2K", "watermark": False}},
            {"id": 14, "type": "SaveVideo", "pos": [2500, 120], "size": [400, 300],
             "params": {"filename_prefix": "image-to-video-2k",
                        "format": "auto", "codec": "auto"}},
        ],
        "edges": Z_BASE_EDGES + [
            (9, 0, 12, "first_frame"),   # 生成的图 → 视频首帧
            (11, 0, 12, "prompt"),       # 提示词 → 本地生成
            (11, 0, 13, "prompt"),       # 同一提示词 → 2K 节点（保证一致）
            (12, 0, 13, "video"),
            (13, 0, 14, "video"),
        ],
    }),
]

# ==========================================================================
#         多镜头分镜（可配镜头数 + 末帧接力 + 一键拼接）
# ==========================================================================

# 增删这里的条目就能改变镜头数。每个字段对应 H3StructuredPrompt 的一个输入框。
# seconds 必须落在 h3.c 的帧网格上（17k+5 帧，即 k/24 + 5/24 秒）：
#   5.17 → 124 帧   8.00 → 192 帧   4.46 → 107 帧
# 这三个值同时满足官方 2K 的 107+17k 网格，将来要送 2K 也不用改。
STORYBOARD = [
    {
        "scene": "a red fox stepping out of a snowy larch forest into an open snowfield",
        "action": "the fox walks forward slowly, leaving a trail of prints",
        "camera": "wide establishing shot, static then a slow pan to the right",
        "style": "photorealistic wildlife cinematography, golden winter morning light",
        "sound": "gentle wind, distant birds, soft snow crunch",
        "extra": "",
        "seconds": 8.00,   # 建立镜头铺陈久一点：192 帧
        "seed": 42,
    },
    {
        "scene": "the same snowfield, seen closer, the fox now mid-distance",
        "action": "the fox keeps walking, ears swivelling, breath visible in the cold air",
        "camera": "medium tracking shot, camera moves alongside the fox",
        "style": "photorealistic wildlife cinematography, low golden sun behind the trees",
        "sound": "soft crunch of paws on snow, light breeze",
        "extra": "",
        "seconds": 5.17,
        "seed": 43,
    },
    {
        "scene": "close on the red fox, snow particles drifting past its face",
        "action": "the fox stops and lifts its head, sniffing the air",
        "camera": "slow push-in to a close-up",
        "style": "photorealistic wildlife cinematography, warm rim light on the fur",
        "sound": "quiet, still winter atmosphere",
        "extra": "",
        "seconds": 5.17,
        "seed": 44,
    },
]

SHOT_W, SHOT_H = 864, 480


def _storyboard_spec():
    """按 STORYBOARD 的长度生成：N 个结构化提示词 + N 个镜头 + (N-1) 次接力 + 1 次拼接。"""
    nodes, edges = [], []
    nid = 0
    prompts, shots = [], []

    for i, s in enumerate(STORYBOARD):
        nid += 1
        nodes.append({"id": nid, "type": "H3StructuredPrompt",
                      "pos": [40, 60 + i * 300], "size": [400, 300],
                      "params": {k: s[k] for k in
                                 ("scene", "action", "camera", "style", "sound", "extra")}})
        prompts.append(nid)

    for i, s in enumerate(STORYBOARD):
        nid += 1
        nodes.append({"id": nid, "type": "WildH3TextToVideo",
                      "pos": [520 + i * 560, 40], "size": [440, 460],
                      "params": {"prompt": "", "width": SHOT_W, "height": SHOT_H,
                                 "seconds": s["seconds"], "steps": 6, "preset": "precise",
                                 "seed": s["seed"], **H3_COMMON}})
        shots.append(nid)

    # 末帧接力：shot[i] → 末帧 → shot[i+1] 的首帧
    for i in range(len(shots) - 1):
        nid += 1
        lf = nid
        nodes.append({"id": lf, "type": "H3LastFrame",
                      "pos": [520 + i * 560, 560], "size": [400, 100], "params": {}})
        edges.append((shots[i], 0, lf, "video"))
        edges.append((lf, 0, shots[i + 1], "first_frame"))

    # 拼接
    nid += 1
    concat = nid
    nodes.append({"id": concat, "type": "ConcatenateVideo",
                  "pos": [520 + len(shots) * 560, 40], "size": [400, 200],
                  "params": {"codec": "auto"}})
    for i, sid in enumerate(shots):
        edges.append((sid, 0, concat, f"videos.video{i}"))

    # 每镜单独存一份，方便逐镜检查
    for i, sid in enumerate(shots):
        nid += 1
        nodes.append({"id": nid, "type": "SaveVideo",
                      "pos": [520 + len(shots) * 560, 300 + i * 250], "size": [400, 220],
                      "params": {"filename_prefix": f"shot-{i + 1}",
                                 "format": "auto", "codec": "auto"}})
        edges.append((sid, 0, nid, "video"))

    # 拼接成片
    nid += 1
    nodes.append({"id": nid, "type": "SaveVideo",
                  "pos": [520 + (len(shots) + 1) * 560, 40], "size": [400, 280],
                  "params": {"filename_prefix": f"storyboard-{len(shots)}shot",
                             "format": "auto", "codec": "auto"}})
    edges.append((concat, 0, nid, "video"))

    for pid, sid in zip(prompts, shots):
        edges.append((pid, 0, sid, "prompt"))

    return {"nodes": nodes, "edges": edges}


# ConcatenateVideo 的 autogrow 槽数要跟镜头数一致，否则界面上会多出空槽
SOCKET_INPUTS["ConcatenateVideo"] = {
    **{f"videos.video{i}": "VIDEO" for i in range(len(STORYBOARD))},
    "complete_audio": "AUDIO",
}

SPECS += [
    (f"h3-storyboard-{len(STORYBOARD)}shot", _storyboard_spec()),
]

# ==========================================================================
#                        2K 放大器
# ==========================================================================
# 实测对比（1024² → 2048²，拉普拉斯方差，越高越锐；原图 131.9）：
#   纯 RealESRGAN        298.0  (2.26x)  ← 最佳
#   RealESRGAN + VAE往返  273.2  (2.07x)
#   含 Z-Image 精修       122.7  (0.93x)  ← 精修把放大成果抹掉了
# 所以默认工作流走「纯放大」；精修版单独一张，只在需要重绘细节时用。
UPSCALE_MODEL = "RealESRGAN_x4plus.pth"
UPSCALE_PROMPT = ("masterpiece, 8k, sharp focus, rich detail, "
                  "photorealistic wildlife photography")

SPECS += [
    # ---- #1 纯放大（推荐）：1024² → 2048²，约 10 秒 ----
    ("image-upscale-2k", {
        "nodes": [
            {"id": 4, "type": "UpscaleModelLoader", "pos": [40, 60], "size": [400, 80],
             "params": {"model_name": UPSCALE_MODEL}},
            {"id": 5, "type": "LoadImage", "pos": [40, 200], "size": [400, 420],
             "params": {"image": "example.png"}},
            {"id": 9, "type": "ImageUpscaleWithModel", "pos": [520, 60], "size": [400, 60],
             "params": {}},
            {"id": 10, "type": "ImageScaleBy", "pos": [520, 160], "size": [400, 110],
             "params": {"upscale_method": "lanczos", "scale_by": 0.5}},
            {"id": 14, "type": "SaveImage", "pos": [520, 320], "size": [400, 480],
             "params": {"filename_prefix": "z-image-2k"}},
        ],
        "edges": [
            (4, 0, 9, "upscale_model"), (5, 0, 9, "image"),
            (9, 0, 10, "image"),
            (10, 0, 14, "images"),
        ],
    }),
    # ---- #2 放大 + Z-Image 精修：会重绘细节，但会变软（约 8 分钟）----
    ("image-upscale-2k-refine", {
        "nodes": [
            {"id": 1, "type": "UNETLoader", "pos": [40, 60], "size": [400, 90],
             "params": {"unet_name": TURBO_DIT, "weight_dtype": "default"}},
            {"id": 2, "type": "CLIPLoader", "pos": [40, 190], "size": [400, 130],
             "params": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2",
                        "device": "default"}},
            {"id": 3, "type": "VAELoader", "pos": [40, 360], "size": [400, 80],
             "params": {"vae_name": "ae.safetensors"}},
            {"id": 4, "type": "UpscaleModelLoader", "pos": [40, 480], "size": [400, 80],
             "params": {"model_name": UPSCALE_MODEL}},
            {"id": 5, "type": "LoadImage", "pos": [40, 600], "size": [400, 420],
             "params": {"image": "example.png"}},
            {"id": 6, "type": "CLIPTextEncode", "pos": [520, 60], "size": [400, 160],
             "params": {"text": UPSCALE_PROMPT}},
            {"id": 7, "type": "CLIPTextEncode", "pos": [520, 260], "size": [400, 160],
             "params": {"text": ""}},
            {"id": 8, "type": "ModelSamplingAuraFlow", "pos": [520, 460], "size": [400, 100],
             "params": {"shift": 3.0, "sampling": "flow"}},
            {"id": 9, "type": "ImageUpscaleWithModel", "pos": [1000, 60], "size": [400, 60],
             "params": {}},
            {"id": 10, "type": "ImageScaleBy", "pos": [1000, 160], "size": [400, 110],
             "params": {"upscale_method": "lanczos", "scale_by": 0.5}},
            {"id": 11, "type": "VAEEncode", "pos": [1000, 310], "size": [400, 60],
             "params": {}},
            {"id": 12, "type": "KSampler", "pos": [1000, 410], "size": [400, 320],
             "params": {"seed": 42, "steps": 5, "cfg": 1.0,
                        "sampler_name": "dpmpp_2m_sde", "scheduler": "beta",
                        "denoise": 0.33}},
            {"id": 13, "type": "VAEDecode", "pos": [1480, 60], "size": [400, 60],
             "params": {}},
            {"id": 14, "type": "SaveImage", "pos": [1480, 160], "size": [400, 480],
             "params": {"filename_prefix": "z-image-2k"}},
        ],
        "edges": [
            (2, 0, 6, "clip"), (2, 0, 7, "clip"),
            (1, 0, 8, "model"),
            (4, 0, 9, "upscale_model"), (5, 0, 9, "image"),
            (9, 0, 10, "image"),
            (10, 0, 11, "pixels"), (3, 0, 11, "vae"),
            (8, 0, 12, "model"), (6, 0, 12, "positive"), (7, 0, 12, "negative"),
            (11, 0, 12, "latent_image"),
            (12, 0, 13, "samples"), (3, 0, 13, "vae"),
            (13, 0, 14, "images"),
        ],
    }),
]

out_ui = ROOT / "workflows"
out_api = ROOT / "workflows" / "api"
out_ui.mkdir(parents=True, exist_ok=True)
out_api.mkdir(parents=True, exist_ok=True)
for name, spec in SPECS:
    wf, api, _ = build(spec, name)
    (out_ui / f"{name}.json").write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_api / f"{name}.api.json").write_text(json.dumps(api, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ✅ {name}: UI {len(wf['nodes'])} 节点 / {len(wf['links'])} 连线 | API {len(api)} 节点")
