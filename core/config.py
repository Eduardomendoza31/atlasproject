import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

load_dotenv(CONFIG_DIR / ".env")


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
