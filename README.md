# JavVault

番号出库/复原 + NVENC 压缩队列工具。Python + PySide6，跨平台（Windows / macOS）。
配套软件：UltraRename（通用批量重命名）。

## 功能

**📚 库管理**
- 出库：丢入「番号 标题.mp4」类文件 → 提取番号改名（ADN-476.mp4）→ SQLite 记录原始名/路径/大小/MD5
- 复原：处理完的文件丢回来 → MD5 优先匹配（改名后仍能找回）→ 番号兜底（重新编码后 MD5 变了也能靠番号+大小消歧）→ 恢复原始文件名
- 状态机：OUT（在外）/ IN（已归还）/ ARCHIVED（已归档），重复番号自动加 _2 后缀不冲突
- 归档：标记处理完成的记录

**🎬 压缩队列**
- ffmpeg 集成（NVENC 硬编：h264 兼容优先 CQ23 / hevc 体积优先 CQ26，参数可调）
- 逐任务实时进度条，队列挂机批处理
- 产物 ffprobe 校验通过才算成功；「删除源文件」开关默认关闭
- 全自动流水线：出库改名 → 压缩 → 复原原名 → 标记归档；原文件自动改名 .bak 备份
- 没有 ffmpeg 时番号功能完全不受影响

## 运行

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip ...
PYTHONPATH=. .venv/bin/python run.py
```

## 打包

- Windows：双击 `build_win.bat` → `dist/JavVault.exe`
  （需 ffmpeg.exe / ffprobe.exe 与 exe 同目录或在 PATH；本仓库不附带，ffmpeg 官网下载 release essentials 包）
- macOS：`.venv/bin/pyinstaller --onefile --windowed --name JavVault run.py`
  （macOS 无 NVENC，压缩需改用 VideoToolbox，本工具面向 Windows 新机 RTX 5090D）

## 数据位置

- 记录库：`~/.javvault/vault.db`（SQLite，可备份/迁移）

## 测试

```bash
.venv/bin/python -m pytest tests/ -q   # 15 项（番号提取/出库/复原/消歧/ffmpeg参数/产物校验）
```

## 目录结构

- `javvault/core/` codes（番号正则）/ store（SQLite）/ vault（出库复原）/ ffmpeg（压缩）
- `javvault/gui/` 主窗口（库管理 + 压缩队列双标签）
- `tests/` 单元测试
