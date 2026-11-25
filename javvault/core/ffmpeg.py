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
             "-movflags", "+faststart", "-stats_period", "0.2", dst]
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
            progress=None, on_log=None) -> tuple[bool, str]:
        total = duration_of(self.src, ffprobe)
        args = build_args(self.src, self.dst, self.profile, self.cq,
                          self.maxrate_k, self.audio_kbps, ffmpeg)
        if on_log:
            on_log(f"$ {' '.join(args)}")
            if total:
                on_log(f"[i] 源时长 {total/3600:.2f}h")
        try:
            self.process = subprocess.Popen(
                args, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE)
        except OSError as e:
            return False, f"启动 ffmpeg 失败: {e}"
        except OSError as e:
            return False, f"启动 ffmpeg 失败: {e}"
        code = None
        time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        speed_re = re.compile(r"speed=\s*([\d.]+)x")
        frame_re = re.compile(r"frame=\s*(\d+)")
        assert self.process.stderr is not None
        fd = self.process.stderr.fileno()
        pending = b""
        while not self.cancelled:
            # ffmpeg 进度用 \r 分隔而非 \n，必须按块读再手动切分
            try:
                chunk = os.read(fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            pending += chunk
            parts = re.split(b"[\r\n]", pending)
            pending = parts[-1]
            for raw_line in parts[:-1]:
                text = raw_line.decode("utf-8", "ignore")
                stripped = text.strip()
                if stripped and on_log and not stripped.startswith("frame="):
                    on_log(stripped)
                m = time_re.search(text)
                if not (m and progress):
                    continue
                sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + \
                    float(m.group(3))
                sm = speed_re.search(text)
                fm = frame_re.search(text)
                if total:
                    pct = min(99, int(sec / total * 100))
                    info = f"{sec/3600:.2f}/{total/3600:.2f}h"
                else:
                    pct = 0
                    info = f"已编码 {sec/60:.1f} 分钟（时长未知）"
                if sm:
                    info += f" | {sm.group(1)}x"
                    if float(sm.group(1)) > 0:
                        remain = (total - sec) / float(sm.group(1)) if total else None
                        if remain and remain > 0:
                            info += f" | 剩余~{int(remain//60)}m{int(remain%60):02d}s"
                if fm:
                    info += f" | 帧{fm.group(1)}"
                progress(pct, info)
        code = self.process.wait()
        if self.cancelled:
            return False, "已取消"
        if code != 0:
            return False, f"ffmpeg 退出码 {code}"
        if not probe_ok(self.dst, ffprobe):
            return False, "产物校验失败（ffprobe 无法解码）"
        if progress:
            progress(100, "")
        return True, "ok"
