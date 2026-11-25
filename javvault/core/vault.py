"""JavVault 出库/复原业务逻辑。"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

from .codes import extract_code
from .store import Record, VaultStore


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class OpResult:
    path: str
    ok: bool
    action: str          # renamed / skipped / restored / error
    detail: str = ""
    record_id: int | None = None
    code: str | None = None


@dataclass
class BatchReport:
    results: list[OpResult] = field(default_factory=list)

    def summary(self) -> str:
        ok = sum(1 for r in self.results if r.ok)
        return f"{ok}/{len(self.results)} 成功"


def _unique_target(directory: str, name: str) -> str:
    """目标名存在时追加序号：ADN-476.mp4 -> ADN-476_2.mp4"""
    stem, ext = (name.rsplit(".", 1) if "." in name else (name, ""))
    cand = os.path.join(directory, name)
    n = 2
    while os.path.exists(cand):
        suffix = f"_{n}" + (f".{ext}" if ext else "")
        cand = os.path.join(directory, stem + suffix)
        n += 1
    return cand


def checkout(paths: list[str], store: VaultStore) -> BatchReport:
    """出库：提取番号 → 改名为番号.ext → 记录原始信息 + MD5。"""
    report = BatchReport()
    for p in paths:
        name = os.path.basename(p)
        ext = name.rsplit(".", 1)[1] if "." in name else ""
        parsed = extract_code(name)
        if not parsed:
            report.results.append(OpResult(p, False, "skipped", "未识别到番号"))
            continue
        display, key = parsed
        try:
            digest = md5_of(p)
            size = os.path.getsize(p)
        except OSError as e:
            report.results.append(OpResult(p, False, "error", str(e)))
            continue
        directory = os.path.dirname(os.path.abspath(p))
        target = _unique_target(directory, f"{display}.{ext}" if ext else display)
        new_name = os.path.basename(target)
        try:
            os.rename(p, target)
        except OSError as e:
            report.results.append(OpResult(p, False, "error", str(e)))
            continue
        rec_id = store.add_checkout(key, name, new_name, directory, size, digest)
        report.results.append(OpResult(target, True, "renamed",
                                       f"{name} -> {new_name}", rec_id, display))
    return report


def restore(paths: list[str], store: VaultStore) -> BatchReport:
    """复原：MD5 优先匹配，番号+状态匹配兜底，多候选时按大小消歧。"""
    report = BatchReport()
    for p in paths:
        try:
            digest = md5_of(p)
            size = os.path.getsize(p)
        except OSError as e:
            report.results.append(OpResult(p, False, "error", str(e)))
            continue
        rec = None
        hits = store.by_md5_out(digest)
        if len(hits) == 1:
            rec = hits[0]
        elif len(hits) > 1:
            sized = [h for h in hits if h.size == size]
            if len(sized) == 1:
                rec = sized[0]
        if rec is None:
            parsed = extract_code(os.path.basename(p))
            if parsed:
                candidates = store.by_code_out(parsed[1])
                if len(candidates) == 1:
                    rec = candidates[0]
                elif len(candidates) > 1:
                    sized = [c for c in candidates if c.size == size]
                    if len(sized) == 1:
                        rec = sized[0]
                    else:
                        report.results.append(OpResult(
                            p, False, "skipped",
                            f"{parsed[0]} 有 {len(candidates)} 条在库记录，无法消歧"))
                        continue
        if rec is None:
            report.results.append(OpResult(
                p, False, "skipped", "库中无匹配（MD5 与番号均未命中）"))
            continue
        directory = os.path.dirname(os.path.abspath(p))
        target = os.path.join(directory, rec.original_name)
        if os.path.exists(target):
            report.results.append(OpResult(
                p, False, "skipped", f"复原目标已存在：{rec.original_name}"))
            continue
        try:
            os.rename(p, target)
        except OSError as e:
            report.results.append(OpResult(p, False, "error", str(e)))
            continue
        store.mark_in(rec.id)
        report.results.append(OpResult(target, True, "restored",
                                       f"{os.path.basename(p)} -> {rec.original_name}",
                                       rec.id, rec.code))
    return report
