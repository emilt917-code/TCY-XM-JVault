"""数据文件位置：打包后统一放 exe 同目录（轻装便携），开发态放用户目录。"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """便携模式：PyInstaller 打包后 = exe 所在目录；开发态 = 用户目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.join(os.path.expanduser("~"), ".javvault")


def data_file(name: str) -> str:
    d = app_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)
