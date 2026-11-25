"""JavVault 主窗口：库管理 + 压缩队列。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QStatusBar, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from javvault.core import (
    CompressionJob, VaultStore, checkout, find_binary, restore,
)

STATUS_TEXT = {"OUT": "在外(OUT)", "IN": "已归还(IN)", "ARCHIVED": "已归档"}
STATUS_COLOR = {"OUT": QColor("#e65100"), "IN": QColor("#2e7d32"),
                "ARCHIVED": QColor("#616161")}


class CompressWorker(QThread):
    """后台压缩线程：逐个任务执行，发进度信号。"""
    progress = Signal(int, int, str)      # 任务序号, 百分比, 消息
    item_done = Signal(int, bool, str)    # 任务序号, 成功, 消息
    all_done = Signal()

    def __init__(self, jobs: list[CompressionJob], ffmpeg: str, ffprobe: str):
        super().__init__()
        self.jobs = jobs
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def run(self):
        for i, job in enumerate(self.jobs):
            self.progress.emit(i, 0, "压缩中…")
            ok, msg = job.run(self.ffmpeg, self.ffprobe,
                              lambda pct, i=i: self.progress.emit(i, pct, ""))
            self.item_done.emit(i, ok, msg)
        self.all_done.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JavVault — 番号出库/复原 + 压缩队列")
        self.resize(1180, 760)
        self.store = VaultStore()
        self.ffmpeg = find_binary("ffmpeg")
        self.ffprobe = find_binary("ffprobe")
        self.jobs: list[CompressionJob] = []
        self.worker: CompressWorker | None = None
        self._build_ui()
        self.refresh_library()

    # ================================================== UI
    def _build_ui(self):
        tabs = QTabWidget()
        tabs.addTab(self._build_library_tab(), "📚 库管理")
        tabs.addTab(self._build_compress_tab(), "🎬 压缩队列")
        self.setCentralWidget(tabs)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        ff_state = "ffmpeg ✅ " + (self.ffmpeg or "") if self.ffmpeg \
            else "ffmpeg ❌ 未在 PATH 找到（压缩功能不可用，番号功能不受影响）"
        self.status.showMessage(ff_state)

    def _build_library_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        btn_out = QPushButton("⬆ 出库（改名=番号）")
        btn_out.clicked.connect(self._do_checkout)
        btn_in = QPushButton("⬇ 复原（找回原名）")
        btn_in.clicked.connect(self._do_restore)
        btn_arch = QPushButton("🗄 标记已归档")
        btn_arch.clicked.connect(self._do_archive)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh_library)
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(lambda: self.lib_table.selectAll())
        for b in (btn_out, btn_in, btn_arch, btn_all, btn_refresh):
            bar.addWidget(b)
        bar.addStretch(1)
        self.lbl_stats = QLabel("")
        bar.addWidget(self.lbl_stats)
        v.addLayout(bar)

        self.lib_table = QTableWidget()
        self.lib_table.setColumnCount(6)
        self.lib_table.setHorizontalHeaderLabels(["番号", "原始文件名", "当前名",
                                        "状态", "大小", "出库时间"])
        self.lib_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.lib_table.setSelectionBehavior(self.lib_table.SelectionBehavior.SelectRows)
        self.lib_table.setSelectionMode(self.lib_table.SelectionMode.ExtendedSelection)
        v.addWidget(self.lib_table, 1)
        tip = QLabel("出库：选中文件提取番号改名并记录；处理完后把文件丢回原目录，选中点「复原」找回原名（MD5 优先，番号兜底）。")
        tip.setWordWrap(True)
        v.addWidget(tip)
        return w

    def _build_compress_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        grp_src = QGroupBox("1. 任务来源")
        sv = QHBoxLayout(grp_src)
        btn_add = QPushButton("添加文件…")
        btn_add.clicked.connect(self._add_files)
        btn_dir = QPushButton("添加目录…")
        btn_dir.clicked.connect(self._add_dir)
        btn_clear = QPushButton("清空队列")
        btn_clear.clicked.connect(self._clear_queue)
        self.chk_pipeline = QCheckBox("全自动流水线（出库改名→压缩→复原原名→标记归档）")
        self.chk_pipeline.setChecked(True)
        for c in (btn_add, btn_dir, btn_clear):
            sv.addWidget(c)
        sv.addWidget(self.chk_pipeline, 1)
        v.addWidget(grp_src)

        grp_cfg = QGroupBox("2. 编码参数")
        cv = QHBoxLayout(grp_cfg)
        cv.addWidget(QLabel("编码:"))
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItems(["h264（兼容优先）", "hevc（体积优先）"])
        cv.addWidget(self.cmb_profile)
        cv.addWidget(QLabel("CQ 质量:"))
        self.spn_cq = QSpinBox()
        self.spn_cq.setRange(0, 51)
        self.spn_cq.setValue(23)
        cv.addWidget(self.spn_cq)
        cv.addWidget(QLabel("码率上限(kbps):"))
        self.spn_maxrate = QSpinBox()
        self.spn_maxrate.setRange(0, 200000)
        self.spn_maxrate.setValue(20000)
        cv.addWidget(self.spn_maxrate)
        cv.addWidget(QLabel("音频(kbps):"))
        self.spn_audio = QSpinBox()
        self.spn_audio.setRange(64, 512)
        self.spn_audio.setValue(192)
        cv.addWidget(self.spn_audio)
        self.chk_del_src = QCheckBox("完成后删除源文件")
        self.chk_del_src.setToolTip("仅在产物 ffprobe 校验通过后删除；不勾选则保留源文件")
        cv.addWidget(self.chk_del_src)
        cv.addStretch(1)
        v.addWidget(grp_cfg)

        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(5)
        self.queue_table.setHorizontalHeaderLabels(["源文件", "输出文件", "状态", "进度", "消息"])
        self.queue_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        v.addWidget(self.queue_table, 1)

        btn_run = QPushButton("▶ 开始压缩队列")
        btn_run.clicked.connect(self._start_queue)
        v.addWidget(btn_run)
        return w

    # ================================================== 库管理
    def _selected_paths(self) -> list[str]:
        out = []
        for item in self.lib_table.selectedItems():
            if item.column() == 0:
                rid = self.lib_table.item(item.row(), 5).data(Qt.UserRole)
                rec = self.store.by_id(rid)
                if rec:
                    d = rec.dir_path or ""
                    cur = rec.current_name or ""
                    out.append(os.path.join(d, cur) if cur else "")
        return [p for p in out if p and os.path.exists(p)]

    def _do_checkout(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要出库的文件")
        if not paths:
            return
        rep = checkout(paths, self.store)
        self._show_report(rep)
        self.refresh_library()

    def _do_restore(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要复原的文件")
        if not paths:
            return
        rep = restore(paths, self.store)
        self._show_report(rep)
        self.refresh_library()

    def _do_archive(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择已处理完的文件")
        if not paths:
            return
        from javvault.core import md5_of
        n = 0
        for p in paths:
            try:
                digest = md5_of(p)
            except OSError:
                continue
            for rec in self.store.by_md5_out(digest):
                self.store.mark_archived(rec.id, "手动归档")
                n += 1
        self.status.showMessage(f"已标记 {n} 条为归档")
        self.refresh_library()

    def _show_report(self, rep):
        lines = [f"{r.action}: {r.detail or r.path}" for r in rep.results]
        QMessageBox.information(self, "操作结果",
                                rep.summary() + "\n\n" + "\n".join(lines[:20]))

    def refresh_library(self):
        recs = self.store.list_all()
        self.lib_table.setRowCount(0)
        for rec in recs:
            row = self.lib_table.rowCount()
            self.lib_table.insertRow(row)
            import time as _t
            vals = [rec.code, rec.original_name, rec.current_name or "",
                    STATUS_TEXT.get(rec.status, rec.status),
                    f"{(rec.size or 0)/1e9:.2f} GB",
                    _t.strftime("%m-%d %H:%M", _t.localtime(rec.ts_out or 0))]
            for col, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                if col == 3:
                    it.setForeground(STATUS_COLOR.get(rec.status, QColor("#000")))
                if col == 0:
                    it.setData(Qt.UserRole, rec.id)
                self.lib_table.setItem(row, col, it)
        st = self.store.stats()
        self.lbl_stats.setText(
            f"在外 {st['OUT']} | 已归还 {st['IN']} | 已归档 {st['ARCHIVED']}")

    # ================================================== 压缩队列
    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", "", "视频 (*.mp4 *.mkv *.avi *.wmv *.mov *.ts)")
        self._enqueue(paths)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择目录")
        if not d:
            return
        exts = {".mp4", ".mkv", ".avi", ".wmv", ".mov", ".ts"}
        self._enqueue([os.path.join(d, f) for f in sorted(os.listdir(d))
                       if os.path.splitext(f)[1].lower() in exts])

    def _enqueue(self, paths):
        for p in paths:
            if not p or not os.path.isfile(p):
                continue
            dst = os.path.splitext(p)[0] + "_cmp.mp4"
            self.jobs.append(CompressionJob(
                p, dst, self._profile(), self.spn_cq.value(),
                self.spn_maxrate.value(), self.spn_audio.value()))
        self._refresh_queue()

    def _profile(self) -> str:
        return "hevc" if self.cmb_profile.currentIndex() == 1 else "h264"

    def _clear_queue(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "队列运行中", "先等队列结束或取消")
            return
        self.jobs.clear()
        self._refresh_queue()

    def _refresh_queue(self, statuses=None):
        self.queue_table.setRowCount(0)
        for i, j in enumerate(self.jobs):
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            self.queue_table.setItem(row, 0, QTableWidgetItem(j.src))
            self.queue_table.setItem(row, 1, QTableWidgetItem(j.dst))
            st, prog, msg = (statuses or {}).get(i, ("待处理", 0, ""))
            self.queue_table.setItem(row, 2, QTableWidgetItem(st))
            bar = QProgressBar()
            bar.setValue(prog)
            self.queue_table.setCellWidget(row, 3, bar)
            self.queue_table.setItem(row, 4, QTableWidgetItem(msg))

    def _start_queue(self):
        if not self.ffmpeg:
            QMessageBox.warning(self, "缺 ffmpeg",
                                "PATH 中找不到 ffmpeg。\n把 ffmpeg.exe 所在目录加入 PATH，"
                                "或把 ffmpeg.exe/ffprobe.exe 放到本程序同目录。")
            return
        if not self.jobs:
            return
        self.worker = CompressWorker(self.jobs, self.ffmpeg, self.ffprobe)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.all_done.connect(self._on_all_done)
        self._refresh_queue({(i,): ("排队", 0, "") for i in range(len(self.jobs))} and
                            {i: ("压缩中", 0, "") for i in range(len(self.jobs))})
        self.worker.start()

    def _on_progress(self, idx, pct, msg):
        self._set_row(idx, "压缩中", pct, msg)

    def _set_row(self, idx, st, pct, msg):
        if idx >= self.queue_table.rowCount():
            return
        self.queue_table.item(idx, 2).setText(st)
        bar = self.queue_table.cellWidget(idx, 3)
        if isinstance(bar, QProgressBar):
            bar.setValue(pct)
        if msg:
            self.queue_table.item(idx, 4).setText(msg)

    def _on_item_done(self, idx, ok, msg):
        job = self.jobs[idx]
        if not ok:
            self._set_row(idx, "❌ 失败", 0, msg)
            return
        self._set_row(idx, "校验通过", 100, "")
        if self.chk_pipeline.isChecked():
            self._pipeline_after_compress(job)
        if self.chk_del_src.isChecked() and os.path.exists(job.src):
            os.remove(job.src)
            self._set_row(idx, "✅ 完成(源已删)", 100, "已删除源文件")
        else:
            self._set_row(idx, "✅ 完成", 100, msg)

    def _pipeline_after_compress(self, job):
        """全自动：出库记录 → 复原原名 → 标记归档。"""
        from javvault.core import md5_of
        src = job.src
        name = os.path.basename(src)
        parsed = None
        from javvault.core.codes import extract_code
        parsed = extract_code(name)
        directory = os.path.dirname(os.path.abspath(src))
        if not parsed:
            return
        display, key = parsed
        try:
            digest = md5_of(src)
            size = os.path.getsize(src)
        except OSError:
            return
        # 找到已有 OUT 记录（压缩的是已出库文件）或新建记录
        recs = self.store.by_md5_out(digest)
        rec_id = recs[0].id if len(recs) == 1 else None
        if rec_id is None:
            rec_id = self.store.add_checkout(
                key, name, name, directory, size, digest)
        # 复原：把压缩产物改名回原名（_cmp 后缀去掉）
        restored_name = recs[0].original_name if rec_id and recs else name
        if recs:
            self.store.mark_in(recs[0].id)
            rec_id = recs[0].id
        # 压缩产物接替原文件身份
        new_src = os.path.join(directory, restored_name)
        if os.path.exists(new_src):
            stem, ext = os.path.splitext(new_src)
            new_src = f"{stem}_cmp{ext}"
        try:
            os.rename(job.dst, new_src)
        except OSError:
            return
        # 旧源文件让位删除或改名 .bak
        if os.path.exists(src) and src != new_src:
            os.rename(src, src + ".bak")
            self.status.showMessage(f"原文件已改名 {src}.bak，确认没问题后手动删")
        self.store.mark_archived(rec_id, f"压缩产物: {os.path.basename(new_src)}")
        self.refresh_library()

    def _on_all_done(self):
        self.status.showMessage("队列全部完成")
        self.refresh_library()


def main():
    app = QApplication([])
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
