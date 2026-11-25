"""ffmpeg/ffprobe 封装：探测、参数构建、带进度的压缩执行。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

PROFILES = {
    # 兼容优先：H.264 NVENC + AAC
    "h264": {"vcodec": "h264_nvenc", "cq": 23, "preset": "p5",
             "maxrate_k": 20000},
    # 体积优先：HEVC NVENC + AAC
    "hevc": {"vcodec": "hevc_nvenc", "cq": 26, "preset": "p5",
             "maxrate_k": 12000},
}


def find_binary(name: str) -> str | None:
    """依次查找 PATH、程序所在目录、当前目录（Windows 下支持 ffmpeg.exe 放旁边）。"""
    found = shutil.which(name)
    if found:
        return found
    import sys
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.dirname(sys.executable))
    candidates.append(os.getcwd())
    suffix = ".exe" if os.name == "nt" else ""
    for d in candidates:
        c = os.path.join(d, name + suffix)
        if os.path.isfile(c):
            return c
    return None


def duration_of(path: str, ffprobe: str = "ffprobe") -> float | None:
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
        d = data.get("format", {}).get("duration")
        return float(d) if d else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def probe_ok(path: str, ffprobe: str = "ffprobe") -> bool:
    """压缩产物可解码性校验。"""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60)
        return bool(r.stdout.strip())
    except OSError:
        return False


def build_args(src: str, dst: str, profile: str = "h264", cq: int | None = None,
               maxrate_k: int | None = None, audio_kbps: int = 192,
               ffmpeg: str = "ffmpeg") -> list[str]:
    p = PROFILES.get(profile, PROFILES["h264"])
    cq = p["cq"] if cq is None else cq
    maxrate_k = p["maxrate_k"] if maxrate_k is None else maxrate_k
    args = [ffmpeg, "-y", "-i", src, "-c:v", p["vcodec"],
            "-preset", p["preset"]]
    if "nvenc" in p["vcodec"]:
        # NVENC 专用：VBR + CQ 质量模式
        args += ["-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
    else:
        # CPU 编码器（备用/测试）：CRF 质量模式
        args += ["-crf", str(cq)]
    args += ["-maxrate", f"{maxrate_k}k", "-bufsize", "40M",
             "-c:a", "aac", "-b:a", f"{audio_kbps}k",
             "-movflags", "+faststart", dst]
    return args


class CompressionJob:
    """单文件压缩任务（阻塞执行，progress 回调 0-100）。"""

    def __init__(self, src: str, dst: str, profile: str = "h264",
                 cq: int | None = None, maxrate_k: int | None = None,
                 audio_kbps: int = 192):
        self.src = src
        self.dst = dst
        self.profile = profile
        self.cq = cq
        self.maxrate_k = maxrate_k
        self.audio_kbps = audio_kbps
        self.process: subprocess.Popen | None = None
        self.cancelled = False

    def run(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
            progress=None) -> tuple[bool, str]:
        total = duration_of(self.src, ffprobe)
        args = build_args(self.src, self.dst, self.profile, self.cq,
                          self.maxrate_k, self.audio_kbps, ffmpeg)
        try:
            self.process = subprocess.Popen(
                args, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace")
        except OSError as e:
            return False, f"启动 ffmpeg 失败: {e}"
        time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        assert self.process.stderr is not None
        for line in self.process.stderr:
            if self.cancelled:
                self.process.kill()
                return False, "已取消"
            m = time_re.search(line)
            if m and total and progress:
                sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + \
                    float(m.group(3))
                progress(min(99, int(sec / total * 100)))
        code = self.process.wait()
        if code != 0:
            return False, f"ffmpeg 退出码 {code}"
        if not probe_ok(self.dst, ffprobe):
            return False, "产物校验失败（ffprobe 无法解码）"
        if progress:
            progress(100)
        return True, "ok"
