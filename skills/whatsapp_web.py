"""Skill: enviar un archivo por WhatsApp Web (alternativa a
skills/whatsapp.py, que controla la app de escritorio).

Eduardo pidio explicitamente tener las dos opciones disponibles y que
Atlas le pregunte cual prefiere usar cada vez, en vez de que Atlas elija
sola - ver el system prompt (core/app.py), que le indica al modelo
preguntar el metodo antes de llamar a cualquiera de las dos.

Riesgo real de esta opcion (a diferencia de la app de escritorio):
WhatsApp/Meta detecta activamente automatizacion de navegador en
WhatsApp Web, y en teoria podria restringir la cuenta si la detecta -
por eso Eduardo eligio la app de escritorio como opcion principal, pero
quiso esta tambien disponible para cuando la prefiera.

Selectores verificados EN VIVO contra una sesion real ya logueada de
WhatsApp Web (no adivinados de memoria - la pagina cambia seguido):
- Buscador: input[data-tab="3"] (ya NO es un div contenteditable como
  en versiones viejas documentadas por otras herramientas - WhatsApp Web
  lo cambio a un <input> normal en algun momento).
- Input de archivo para documentos: el <input type="file"> cuyo accept
  es "*" (a diferencia del de fotos/videos, que acepta solo imagenes y
  videos) - se le puede mandar la ruta directo con send_keys, sin tener
  que clickear el menu "Adjuntar" > "Documento" en absoluto. Es mas
  robusto que simular esos clicks.
El boton de enviar (span[data-icon="send"]) y el cuadro de texto para el
mensaje que acompaña al archivo NO se pudieron verificar en vivo (harian
falta enviar de verdad a un chat real para verlos, y Eduardo pidio
probar el envio real el mismo) - son el patron mas usado y documentado
en herramientas de automatizacion de WhatsApp Web, pero si WhatsApp
cambio tambien esa parte, es lo primero a revisar si esto falla despues
de adjuntar el archivo.
"""

import asyncio
import time
from pathlib import Path

from core.tools import Tool, register as register_tool, resolve_path

SKILL = {
    "name": "WhatsApp Web",
    "description": "Envía un archivo por WhatsApp Web a un contacto o chat, con tu confirmación antes de cada envío.",
}

PROFILE_DIR = Path.home() / ".atlas" / "whatsapp_web_profile"
LOGIN_TIMEOUT_SECONDS = 90
SEARCH_RESULTS_PAUSE = 1.5
ATTACH_LOAD_PAUSE = 2.0

_driver = None  # se reusa entre llamadas para no perder la sesion iniciada


def _get_driver():
    global _driver
    if _driver is not None:
        try:
            _driver.current_url  # probar que el navegador sigue vivo
            return _driver
        except Exception:
            _driver = None

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    # Sin --headless a proposito: si hace falta escanear el codigo QR
    # (primera vez, o la sesion vencio), el usuario necesita ver la
    # ventana real para escanearlo con el telefono.
    _driver = webdriver.Chrome(options=options)
    return _driver


def _wait_for_login(driver) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver.get("https://web.whatsapp.com")
    try:
        WebDriverWait(driver, LOGIN_TIMEOUT_SECONDS).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-tab="3"]'))
        )
        return True
    except Exception:
        return False


def _open_chat(driver, contact: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    search_box = driver.find_element(By.CSS_SELECTOR, 'input[data-tab="3"]')
    search_box.click()
    search_box.send_keys(contact)
    time.sleep(SEARCH_RESULTS_PAUSE)
    search_box.send_keys(Keys.DOWN)
    search_box.send_keys(Keys.ENTER)
    time.sleep(1.0)

    # Verificacion minima: si de verdad se abrio un chat, tiene que
    # existir el input de archivo para documentos en el compositor.
    file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"][accept="*"]')
    if not file_inputs:
        raise RuntimeError(
            f"No pude abrir un chat para '{contact}' - revisá que el nombre "
            "sea exactamente como aparece en tus contactos de WhatsApp."
        )


def _attach_and_send_file(driver, file_path: str, message: str) -> None:
    from selenium.webdriver.common.by import By

    file_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"][accept="*"]')
    file_input.send_keys(file_path)
    time.sleep(ATTACH_LOAD_PAUSE)

    if message:
        caption_boxes = driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="10"]')
        if caption_boxes:
            caption_boxes[0].send_keys(message)

    send_buttons = driver.find_elements(By.CSS_SELECTOR, 'span[data-icon="send"]')
    if not send_buttons:
        raise RuntimeError(
            "El archivo se adjuntó pero no encontré el botón de enviar - "
            "puede que WhatsApp Web haya cambiado ese ícono."
        )
    send_buttons[0].click()


async def _exec_send_whatsapp_file_web(arguments: dict) -> str:
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

    def run() -> str:
        driver = _get_driver()
        if not _wait_for_login(driver):
            return (
                "Abrí WhatsApp Web y no detecté que hayas iniciado sesión a "
                "tiempo - fijate en la ventana del navegador que se abrió, "
                "escaneá el código QR con tu teléfono, y pedime que lo "
                "intente de nuevo."
            )
        _open_chat(driver, contact)
        _attach_and_send_file(driver, str(path), message)
        return f"Archivo '{path.name}' enviado por WhatsApp Web a '{contact}'."

    try:
        return await asyncio.to_thread(run)
    except Exception as exc:
        return f"Error: no pude enviar el archivo por WhatsApp Web: {exc}"


def register() -> None:
    register_tool(Tool(
        name="send_whatsapp_file_web",
        description=(
            "Envía un archivo real por WhatsApp WEB (a través de un "
            "navegador Chrome controlado, no la app de escritorio) a un "
            "contacto o chat. Alternativa a send_whatsapp_file - usa esta "
            "solo si el usuario específicamente pidió WhatsApp Web en vez "
            "de la app de escritorio. La primera vez puede pedir escanear "
            "un código QR con el teléfono."
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
        executor=_exec_send_whatsapp_file_web,
        confirm_text=lambda a: (
            f"Enviar el archivo \"{a.get('file_path', '')}\" por WhatsApp Web a "
            f"\"{a.get('contact', '')}\""
            + (f", con el mensaje: \"{a.get('message')}\"" if a.get("message") else "")
        ),
    ))
