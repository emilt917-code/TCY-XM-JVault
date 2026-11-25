"""JavVault 番号提取与规范化。"""
from __future__ import annotations

import re

# FC2 特殊格式：FC2-PPV-1234567
_FC2_RE = re.compile(
    r"(?<![A-Za-z0-9])FC2[-_ ]?PPV[-_ ]?(\d{6,10})(?!\d)", re.IGNORECASE)

# 常规番号：字母2-6位 + 可选横杠 + 数字2-5位，前后不能紧贴字母数字
_STD_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{2,6})[-_ ]?(\d{2,5})(?!\d)")

# 文件名里常见的干扰词（避免误提取）
_NOISE = {"mp4", "mkv", "avi", "wmv", "mov", "ts", "iso", "h264", "h265",
          "hevc", "avc", "x264", "x265", "aac", "flac", "vol", "cd", "part"}


def extract_code(filename: str) -> tuple[str, str] | None:
    """从文件名提取番号。

    返回 (显示码, 归一化键)。显示码形如 ADN-476 / FC2-PPV-1234567；
    归一化键去掉前导零并统一大写，用于数据库匹配。
    提取不到返回 None。
    """
    stem = filename
    m = _FC2_RE.search(stem)
    if m:
        num = m.group(1)
        display = f"FC2-PPV-{num}"
        return display, f"FC2-PPV-{int(num)}"
    for m in _STD_RE.finditer(stem):
        prefix, num = m.group(1).upper(), m.group(2)
        if prefix.lower() in _NOISE:
            continue
        display = f"{prefix}-{int(num)}"
        return display, f"{prefix}-{int(num)}"
    return None


def display_from_key(key: str) -> str:
    """归一化键 -> 显示码（键本身即显示格式，此函数保留以备扩展）。"""
    return key
