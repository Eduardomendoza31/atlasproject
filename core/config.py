import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

load_dotenv(CONFIG_DIR / ".env")

# Carpeta real del usuario (no de la instalacion de Atlas) donde caen las
# imagenes generadas (skills/image_generation.py) - se guarda ahi y no en
# una carpeta interna del proyecto para que el usuario la encuentre en su
# explorador de archivos como cualquier otra foto suya. Vive aca (no en la
# skill) porque core/app.py tambien la necesita, para servirla por HTTP y
# que la UI pueda mostrar la imagen (ver GENERATED_IMAGES_URL_PREFIX ahi).
GENERATED_IMAGES_DIR = Path.home() / "Pictures" / "Atlas"


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.json", "r", encoding="utf-8") as f:
        return json.load(f)


def model_for_role(role: str) -> str:
    settings = load_settings()
    role_cfg = settings["roles"].get(role)
    if role_cfg is None:
        raise ValueError(f"No hay modelo configurado para el rol '{role}'")
    return role_cfg["model"]


USER_NAME = os.getenv("USER_NAME", "").strip() or "amigo"
