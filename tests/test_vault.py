"""出库/复原/状态机测试。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from javvault.core.store import VaultStore  # noqa: E402
from javvault.core.vault import checkout, restore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = VaultStore(str(tmp_path / "vault.db"))
    yield s
    s.close()


def _mk(tmp_path, name, content=b"video-bytes"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_checkout_renames_and_records(tmp_path, store):
    src = _mk(tmp_path, "ADN-476 お父さん、ごめんね。.mp4")
    rep = checkout([src], store)
    assert rep.results[0].ok
    assert os.path.basename(rep.results[0].path) == "ADN-476.mp4"
    recs = store.list_out()
    assert len(recs) == 1
    assert recs[0].original_name == "ADN-476 お父さん、ごめんね。.mp4"
    assert recs[0].code == "ADN-476" and recs[0].md5


def test_checkout_no_code_skipped(tmp_path, store):
    src = _mk(tmp_path, "无番号文件.mp4")
    rep = checkout([src], store)
    assert not rep.results[0].ok and rep.results[0].action == "skipped"
    assert os.path.exists(src)


def test_restore_via_md5_after_rename(tmp_path, store):
    src = _mk(tmp_path, "ADN-476 お父さん、ごめんね。.mp4")
    rep = checkout([src], store)
    coded = rep.results[0].path
    # 模拟处理后被改得面目全非：只保留番号名
    rep2 = restore([coded], store)
    assert rep2.results[0].ok and rep2.results[0].action == "restored"
    assert os.path.basename(rep2.results[0].path) == "ADN-476 お父さん、ごめんね。.mp4"
    assert store.stats()["IN"] == 1


def test_restore_code_fallback(tmp_path, store):
    """MD5 变了（重新编码）但番号还在：按番号复原。"""
    src = _mk(tmp_path, "SSIS-118 彼女の妹.mp4", b"original")
    rep = checkout([src], store)
    coded = rep.results[0].path
    # 模拟重编码：内容变化、大小变化
    with open(coded, "wb") as f:
        f.write(b"re-encoded-much-larger-content" * 10)
    rep2 = restore([coded], store)
    assert rep2.results[0].ok
    assert os.path.basename(rep2.results[0].path) == "SSIS-118 彼女の妹.mp4"


def test_restore_ambiguous_requires_size_match(tmp_path, store):
    """同番号两条在库记录：按文件大小消歧。"""
    a = _mk(tmp_path, "MIDV-832 verA.mp4", b"A" * 100)
    rep = checkout([a], store)
    coded_a = rep.results[0].path
    # 第二条：另一个文件同名番号（目录里自动 _2 命名）
    b = _mk(tmp_path, "MIDV-832 verB.mp4", b"B" * 200)
    rep_b = checkout([b], store)
    assert os.path.basename(rep_b.results[0].path).startswith("MIDV-832_")
    # 复原 A（大小 100 匹配记录 a）
    rep2 = restore([coded_a], store)
    assert rep2.results[0].ok
    assert os.path.basename(rep2.results[0].path) == "MIDV-832 verA.mp4"


def test_restore_unknown_skipped(tmp_path, store):
    p = _mk(tmp_path, "XXX-999 未知.mp4")
    rep = restore([p], store)
    assert not rep.results[0].ok and rep.results[0].action == "skipped"


def test_duplicate_code_gets_suffix(tmp_path, store):
    a = _mk(tmp_path, "ABP-984 a.mp4", b"1")
    rep1 = checkout([a], store)
    coded1 = rep1.results[0].path
    os.rename(coded1, str(tmp_path / "ABP-984.mp4"))
    b = _mk(tmp_path, "ABP-984 b.mp4", b"2")
    rep2 = checkout([b], store)
    assert os.path.basename(rep2.results[0].path) == "ABP-984_2.mp4"
