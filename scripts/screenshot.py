"""离屏截图验证 JavVault GUI。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from javvault.gui.main_window import MainWindow


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/javvault.png"
    app = QApplication([])
    w = MainWindow()
    w.resize(1180, 900)
    if len(sys.argv) > 3 and sys.argv[3] == "compress":
        w.centralWidget().setCurrentIndex(1)
    w.show()

    def shoot():
        w.grab().save(out)
        app.quit()

    QTimer.singleShot(800, shoot)
    app.exec()
    print("saved:", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
