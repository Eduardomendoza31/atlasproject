"""Skill: enviar un archivo por WhatsApp Desktop.

Investigado antes de escribir una linea de codigo (Eduardo lo pidio
explicitamente): WhatsApp en Windows dejo de ser una app Electron en
2023 y hoy es una app UWP nativa (paquete "WhatsAppDesktop") - eso saca
de la mesa la opcion de automatizar WhatsApp Web con Selenium (riesgo
real de que Meta banee la cuenta por automatizacion detectada) y deja
como unica opcion razonable controlar la app de escritorio real via UI
Automation, que es lo que hace este archivo con pywinauto (backend
"uia"). Eduardo eligio esta opcion explicitamente sobre Selenium, y
pidio que el envio sea automatico pero con su confirmacion antes de
cada uno - por eso el tier de la herramienta es "critical" (la misma
confirmacion Permitir/Denegar de siempre, no hace falta nada especial
aca para eso).

Nota real encontrada durante la investigacion: aunque la ventana ya no
es Electron, el contenido de los chats sigue siendo una pagina web
(WebView2/Chromium) adentro del marco nativo - la mayoria de sus
elementos internos se exponen como controles genericos sin
automation_id util, asi que esta automatizacion depende de textos
visibles ("Adjuntar", "Documento") en vez de ids estables. Si WhatsApp
cambia esos textos o el idioma de la cuenta no es español, esto se
rompe y hay que volver a mirar la estructura real (ver el metodo usado
en esta sesion: click + captura de pantalla acotada al menu, no
recorrer el arbol entero a ciegas, que es lento en un WebView2 grande).
"""

import asyncio
import subprocess
import time

from core.tools import Tool, register as register_tool, resolve_path

SKILL = {
    "name": "WhatsApp",
    "description": "Envía un archivo por WhatsApp Desktop a un contacto o chat, con tu confirmación antes de cada envío.",
}

WINDOW_TITLE_RE = ".*WhatsApp.*"
SEARCH_BOX_TITLE_RE = "Buscar.*chat.*"
ATTACH_BUTTON_TITLE = "Adjuntar"
DOCUMENT_MENU_ITEM_TITLE = "Documento"

STEP_PAUSE = 1.0
FILE_DIALOG_PAUSE = 1.5
ATTACH_LOAD_PAUSE = 1.5


def _escape_for_send_keys(text: str) -> str:
    # pywinauto.keyboard.send_keys usa {}, (), +, ^, %, ~ como sintaxis
    # especial (modificadores, teclas especiales) - hay que escaparlos
    # para que un nombre de contacto o un mensaje con esos caracteres se
    # escriba tal cual, en vez de interpretarse como una combinacion de
    # teclas.
    especiales = "{}()+^%~"
    out = []
    for ch in text:
        if ch in especiales:
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)


def _find_whatsapp_pid() -> int | None:
    import psutil

    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if "whatsapp" in name:
            return proc.pid
    return None


def _launch_whatsapp() -> None:
    result = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "(Get-AppxPackage | Where-Object { $_.Name -like '*WhatsApp*' } | "
            "Select-Object -First 1).PackageFamilyName",
        ],
        capture_output=True, text=True, timeout=15,
    )
    package_family_name = result.stdout.strip()
    if not package_family_name:
        raise RuntimeError("No encontré WhatsApp Desktop instalado en esta computadora.")
    subprocess.Popen(
        ["explorer.exe", f"shell:AppsFolder\\{package_family_name}!App"]
    )


def _ensure_whatsapp_running_and_focused():
    from pywinauto import Application

    pid = _find_whatsapp_pid()
    if pid is None:
        _launch_whatsapp()
        for _ in range(20):
            time.sleep(0.5)
            pid = _find_whatsapp_pid()
            if pid:
                break
        if pid is None:
            raise RuntimeError("WhatsApp Desktop no terminó de abrirse a tiempo.")
        time.sleep(2)  # que la ventana termine de cargar su contenido

    app = Application(backend="uia").connect(process=pid)
    win = app.top_window()
    win.set_focus()
    time.sleep(0.3)
    return win


def _open_chat(win, contact: str) -> None:
    from pywinauto.keyboard import send_keys

    search_boxes = win.descendants(control_type="Edit", title_re=SEARCH_BOX_TITLE_RE)
    if not search_boxes:
        raise RuntimeError("No encontré el buscador de chats de WhatsApp.")
    search_box = search_boxes[0]
    search_box.click_input()
    time.sleep(0.3)
    send_keys(_escape_for_send_keys(contact), pause=0.02)
    time.sleep(1.2)
    send_keys("{DOWN}{ENTER}")
    time.sleep(1.0)

    # Verificacion minima: si de verdad se abrio un chat, el boton
    # "Adjuntar" del compositor deberia existir ahora. Si no aparece,
    # lo mas probable es que la busqueda no haya encontrado nada.
    attach_buttons = win.descendants(control_type="Button", title=ATTACH_BUTTON_TITLE)
    if not attach_buttons:
        raise RuntimeError(
            f"No pude abrir un chat para '{contact}' - revisá que el nombre "
            "sea exactamente como aparece en tus contactos de WhatsApp."
        )


def _attach_and_send_file(win, file_path: str, message: str) -> None:
    from pywinauto.keyboard import send_keys

    attach_buttons = win.descendants(control_type="Button", title=ATTACH_BUTTON_TITLE)
    if not attach_buttons:
        raise RuntimeError("No encontré el botón de adjuntar en el chat abierto.")
    attach_buttons[0].click_input()
    time.sleep(STEP_PAUSE)

    doc_items = win.descendants(control_type="Button", title=DOCUMENT_MENU_ITEM_TITLE)
    if not doc_items:
        send_keys("{ESC}")
        raise RuntimeError("No encontré la opción 'Documento' en el menú de adjuntar.")
    doc_items[0].click_input()
    time.sleep(FILE_DIALOG_PAUSE)

    # El cuadro de dialogo nativo de Windows para elegir archivo ya
    # tiene el foco puesto en su campo de nombre de archivo apenas se
    # abre - escribir la ruta completa ahi y confirmar con Enter es mas
    # confiable que buscar la ventana del dialogo por titulo (varia
    # segun el idioma de Windows).
    send_keys(_escape_for_send_keys(file_path))
    send_keys("{ENTER}")
    time.sleep(ATTACH_LOAD_PAUSE)

    if message:
        send_keys(_escape_for_send_keys(message))

    send_keys("{ENTER}")


async def _exec_send_whatsapp_file(arguments: dict) -> str:
    contact = arguments.get("contact", "")
    raw_path = arguments.get("file_path", "")
    message = arguments.get("message", "")

    if not contact:
        return "Error: falta indicar a quién enviarle el archivo."
    if not raw_path:
        return "Error: falta indicar qué archivo enviar."

    path = resolve_path(raw_path)
    if not path.is_file():
        return f"Error: no encontré el archivo '{path}'."

    def run() -> None:
        win = _ensure_whatsapp_running_and_focused()
        _open_chat(win, contact)
        _attach_and_send_file(win, str(path), message)

    try:
        await asyncio.to_thread(run)
    except Exception as exc:
        return f"Error: no pude enviar el archivo por WhatsApp: {exc}"

    return f"Archivo '{path.name}' enviado por WhatsApp a '{contact}'."


def register() -> None:
    register_tool(Tool(
        name="send_whatsapp_file",
        description=(
            "Envía un archivo real por WhatsApp Desktop a un contacto o chat. "
            "Controla la aplicación de WhatsApp instalada en esta computadora "
            "(no WhatsApp Web) - abre el chat indicado, adjunta el archivo y "
            "lo envía. Usala solo cuando el usuario pida explícitamente "
            "enviar o mandar un archivo por WhatsApp a alguien."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Nombre del contacto o chat de WhatsApp tal como aparece en la lista de chats.",
                },
                "file_path": {
                    "type": "string",
                    "description": "Ruta completa del archivo a enviar.",
                },
                "message": {
                    "type": "string",
                    "description": "Mensaje opcional para acompañar el archivo.",
                },
            },
            "required": ["contact", "file_path"],
        },
        tier="critical",
        executor=_exec_send_whatsapp_file,
        confirm_text=lambda a: (
            f"Enviar el archivo \"{a.get('file_path', '')}\" por WhatsApp a "
            f"\"{a.get('contact', '')}\""
            + (f", con el mensaje: \"{a.get('message')}\"" if a.get("message") else "")
        ),
    ))
