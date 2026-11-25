"""JavVault SQLite 记录库。"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass

DEFAULT_DB = os.path.expanduser("~/.javvault/vault.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL,          -- 归一化番号键，如 ADN-476
    original_name TEXT NOT NULL,          -- 出库时的完整原始文件名
    current_name  TEXT,                   -- 出库后的文件名（番号.ext）
    dir_path      TEXT,                   -- 出库时所在目录
    size          INTEGER,                -- 字节
    md5           TEXT,                   -- 文件内容指纹
    status        TEXT NOT NULL DEFAULT 'OUT',  -- OUT / IN / ARCHIVED
    ts_out        REAL,
    ts_in         REAL,
    ts_updated    REAL,
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_md5   ON records(md5);
CREATE INDEX IF NOT EXISTS idx_code  ON records(code, status);
"""


@dataclass
class Record:
    id: int
    code: str
    original_name: str
    current_name: str | None
    dir_path: str | None
    size: int | None
    md5: str | None
    status: str
    ts_out: float | None
    ts_in: float | None


class VaultStore:
    def __init__(self, db_path: str = DEFAULT_DB):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # ------------------------------------------------ 写
    def add_checkout(self, code: str, original_name: str, current_name: str,
                     dir_path: str, size: int, md5: str) -> int:
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO records(code, original_name, current_name, dir_path,"
            " size, md5, status, ts_out, ts_updated)"
            " VALUES(?,?,?,?,?,?, 'OUT', ?, ?)",
            (code, original_name, current_name, dir_path, size, md5, now, now))
        self.conn.commit()
        return cur.lastrowid

    def mark_in(self, rec_id: int):
        self.conn.execute(
            "UPDATE records SET status='IN', ts_in=?, ts_updated=? WHERE id=?",
            (time.time(), time.time(), rec_id))
        self.conn.commit()

    def mark_archived(self, rec_id: int, notes: str = ""):
        self.conn.execute(
            "UPDATE records SET status='ARCHIVED', notes=?, ts_updated=? WHERE id=?",
            (notes, time.time(), rec_id))
        self.conn.commit()

    # ------------------------------------------------ 读
    @staticmethod
    def _to_record(row: sqlite3.Row) -> Record:
        return Record(row["id"], row["code"], row["original_name"],
                      row["current_name"], row["dir_path"], row["size"],
                      row["md5"], row["status"], row["ts_out"], row["ts_in"])

    def by_md5_out(self, md5: str) -> list[Record]:
        rows = self.conn.execute(
            "SELECT * FROM records WHERE md5=? AND status='OUT'", (md5,)).fetchall()
        return [self._to_record(r) for r in rows]

    def by_code_out(self, code: str) -> list[Record]:
        rows = self.conn.execute(
            "SELECT * FROM records WHERE code=? AND status='OUT' ORDER BY id",
            (code,)).fetchall()
        return [self._to_record(r) for r in rows]

    def by_id(self, rec_id: int) -> Record | None:
        row = self.conn.execute("SELECT * FROM records WHERE id=?",
                                (rec_id,)).fetchone()
        return self._to_record(row) if row else None

    def list_all(self) -> list[Record]:
        rows = self.conn.execute("SELECT * FROM records ORDER BY id DESC").fetchall()
        return [self._to_record(r) for r in rows]

    def list_out(self) -> list[Record]:
        rows = self.conn.execute(
            "SELECT * FROM records WHERE status='OUT' ORDER BY id DESC").fetchall()
        return [self._to_record(r) for r in rows]

    def stats(self) -> dict:
        row = self.conn.execute(
            "SELECT status, COUNT(*) n FROM records GROUP BY status").fetchall()
        d = {r["status"]: r["n"] for r in row}
        return {"OUT": d.get("OUT", 0), "IN": d.get("IN", 0),
                "ARCHIVED": d.get("ARCHIVED", 0)}
