"""压缩核心测试（不依赖真实 ffmpeg 的部分）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from javvault.core.ffmpeg import build_args, duration_of, probe_ok  # noqa: E402


def test_build_args_h264_defaults():
    a = build_args("in.mp4", "out.mp4", "h264")
    s = " ".join(a)
    assert "-c:v h264_nvenc" in s and "-cq 28" in s and "-b:a 192k" in s
    assert a[-1] == "out.mp4"


def test_build_args_hevc_custom():
    s = " ".join(build_args("i.mp4", "o.mp4", "hevc", cq=28, maxrate_k=8000))
    assert "hevc_nvenc" in s and "-cq 28" in s and "-maxrate 8000k" in s


def test_probe_ok_missing(tmp_path):
    assert not probe_ok(str(tmp_path / "nope.mp4"))
    p = tmp_path / "empty.mp4"
    p.write_bytes(b"")
    assert not probe_ok(str(p))

def test_duration_of_missing_file():
    assert duration_of(str("/nonexist/nope.mp4")) is None
