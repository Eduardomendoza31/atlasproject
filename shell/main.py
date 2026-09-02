import sys
import threading
from pathlib import Path

import uvicorn
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication


class DebugPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"[JS console] {source}:{line} — {message}", flush=True)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.app import app as fastapi_app  # noqa: E402

HOST = "127.0.0.1"
PORT = 8731


def run_server():
    uvicorn.run(fastapi_app, host=HOST, port=PORT, log_level="warning")


def main():
    threading.Thread(target=run_server, daemon=True).start()

    app = QApplication(sys.argv)
    window = QWebEngineView()
    window.setPage(DebugPage(window))
    window.setWindowTitle("Atlas")
    window.resize(900, 700)
    window.load(QUrl.fromLocalFile(str(ROOT / "ui" / "index.html")))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
