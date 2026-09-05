import multiprocessing
import os
import sys
import threading
from pathlib import Path

# Evita el crash clasico de Windows cuando dos librerias nativas (Qt y
# ctranslate2, en este caso) cargan cada una su propio runtime OpenMP en
# el mismo proceso ("OMP Error #15: duplicate libiomp5md.dll").
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import uvicorn
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEnginePermission
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication


class DebugPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"[JS console] {source}:{line} — {message}", flush=True)

    def renderProcessTerminated(self, status, exit_code):
        print(f"[RENDERER MURIO] status={status} exit_code={exit_code}", flush=True)


def _handle_permission_request(permission: QWebEnginePermission) -> None:
    if permission.permissionType() in (
        QWebEnginePermission.PermissionType.MediaAudioCapture,
        QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
    ):
        permission.grant()
    else:
        permission.deny()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.app import app as fastapi_app  # noqa: E402

HOST = "127.0.0.1"
PORT = 8731


def run_server():
    uvicorn.run(fastapi_app, host=HOST, port=PORT, log_level="warning")


def main():
    if sys.platform == "win32":
        # Sin esto, Windows agrupa la ventana bajo el icono generico de
        # python.exe en la barra de tareas en vez del icono propio de la
        # app, sin importar que la ventana/el QApplication ya tengan su
        # icono seteado - es el identificador que Windows usa para saber
        # que esta app es "distinta" de cualquier otro script de Python.
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("eduardo.atlas.asistente")
        except Exception:
            pass

    threading.Thread(target=run_server, daemon=True).start()

    app = QApplication(sys.argv)
    icon = QIcon(str(ROOT / "img" / "atlas_icon.ico"))
    app.setWindowIcon(icon)  # necesario ademas del de la ventana para que la barra de tareas de Windows lo muestre
    window = QWebEngineView()
    page = DebugPage(window)
    page.permissionRequested.connect(_handle_permission_request)
    window.setPage(page)
    window.setWindowIcon(icon)
    window.setWindowTitle("Atlas")
    window.resize(900, 700)
    window.load(QUrl.fromLocalFile(str(ROOT / "ui" / "index.html")))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
