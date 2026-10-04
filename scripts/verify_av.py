#!/usr/bin/env python3
"""Verify temporal coherence and stereo correlation of h3.c output."""
import subprocess, numpy as np, sys, os

FFMPEG = os.environ.get("FFMPEG", os.path.join(os.environ.get("H3_ROOT", os.path.expanduser("~/minimax-h3")), "bin", "ffmpeg"))
VID = os.environ.get("VID", os.path.join(os.environ.get("H3_ROOT", os.path.expanduser("~/minimax-h3")), "h3.c", "outputs", "bench-480p.mp4"))

def probe(cmd):
    return subprocess.run(cmd, capture_output=True)

# --- 视频：抽原始灰度帧，算相邻帧差 vs 远端帧差 ---
raw = subprocess.run([FFMPEG, "-v", "error", "-i", VID, "-f", "rawvideo",
                      "-pix_fmt", "gray", "-vf", "scale=96:54", "-"],
                     capture_output=True).stdout
fsz = 96 * 54
n = len(raw) // fsz
frames = np.frombuffer(raw[:n*fsz], dtype=np.uint8).reshape(n, fsz).astype(np.float32)
adj = np.abs(np.diff(frames, axis=0)).mean()
far = np.abs(frames[-1] - frames[0]).mean()
print(f"视频帧数: {n}")
print(f"相邻帧平均差异: {adj:.2f}")
print(f"首末帧平均差异: {far:.2f}")
print(f"时间连贯性: {'✅ 合格' if adj < far else '❌ 异常'}  (相邻 {adj:.2f} < 远端 {far:.2f})")

# --- 音频：解码双声道，算左右相关 ---
raw_a = subprocess.run([FFMPEG, "-v", "error", "-i", VID, "-f", "s16le",
                        "-acodec", "pcm_s16le", "-ac", "2", "-ar", "32000", "-"],
                       capture_output=True).stdout
a = np.frombuffer(raw_a, dtype=np.int16).astype(np.float32).reshape(-1, 2)
if len(a) > 0:
    L, R = a[:, 0], a[:, 1]
    corr = np.corrcoef(L, R)[0, 1]
    rms = np.sqrt((a ** 2).mean())
    print(f"\n音频采样: {len(a)}  ({len(a)/32000:.2f} 秒)")
    print(f"左右声道相关: {corr:+.3f}")
    print(f"RMS: {rms:.1f}")
    print(f"立体声判定: {'✅ 真立体声（非单声道复制）' if 0.2 < corr < 0.99 else '⚠️ 检查'}")
