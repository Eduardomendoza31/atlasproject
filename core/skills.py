"""Descubrimiento y carga de Skills (ver skills/__init__.py para el
contrato que debe cumplir cada modulo).

No hay nada "magico": recorre los archivos .py sueltos dentro de la
carpeta skills/, importa cada uno, y si expone register() la llama para
que registre sus propias herramientas en core/tools.py. El nucleo nunca
necesita saber los nombres de las Skills instaladas de antemano - agregar
una es agregar un archivo, nunca editar este modulo ni core/tools.py.
"""

import importlib
import pkgutil
from dataclasses import dataclass

import skills as skills_package


@dataclass
class SkillInfo:
    name: str
    description: str
    module: str


_installed: list[SkillInfo] = []


def load_all() -> list[SkillInfo]:
    """Se llama una vez al arrancar el servidor. Si una skill falla al
    cargar, se salta esa sola (con un aviso en consola) en vez de tumbar
    el arranque de todo Atlas por un error en una skill opcional."""
    _installed.clear()
    for _finder, module_name, _is_pkg in pkgutil.iter_modules(skills_package.__path__):
        try:
            module = importlib.import_module(f"skills.{module_name}")
            register_fn = getattr(module, "register", None)
            manifest = getattr(module, "SKILL", None)
            if register_fn is not None:
                register_fn()
            if manifest is not None:
                _installed.append(SkillInfo(
                    name=manifest["name"],
                    description=manifest["description"],
                    module=module_name,
                ))
        except Exception as exc:
            print(f"[Skills] No se pudo cargar '{module_name}': {exc}", flush=True)
    return list(_installed)


def installed_skills() -> list[SkillInfo]:
    return list(_installed)
