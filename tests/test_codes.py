"""番号提取测试。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from javvault.core.codes import extract_code  # noqa: E402


def c(name):
    r = extract_code(name)
    return r[0] if r else None


def test_standard():
    assert c("ADN-476 お父さん、ごめんね。.mp4") == "ADN-476"
    assert c("adn476 title.mp4") == "ADN-476"
    assert c("[XX组] SSIS-118 彼女の妹 (1080p).mp4") == "SSIS-118"
    assert c("MIDV_832 アイドル.mp4") == "MIDV-832"


def test_leading_zeros_normalized():
    display, key = extract_code("id-001 特典.mp4")
    assert display == "ID-1" and key == "ID-1"


def test_fc2():
    assert c("FC2-PPV-1234567 タイトル.mp4") == "FC2-PPV-1234567"
    assert c("fc2ppv_1234567.mp4") == "FC2-PPV-1234567"


def test_noise_not_matched():
    assert c("readme.txt") is None
    assert c("vacation 2023 photos.mp4") is None  # 纯数字年份不匹配
    assert c("my h264 encode.mp4") is None


def test_no_false_positive_from_extension():
    # 文件名主部无番号时不应把扩展名等技术词当番号
    assert c("赤い雨.mp4") is None
