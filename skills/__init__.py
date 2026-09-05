"""Carpeta de Skills de Atlas.

Una Skill es un modulo .py suelto dentro de esta carpeta que expone:
  - SKILL: dict con "name" y "description" (para mostrarla en la UI).
  - register(): funcion que registra sus propias herramientas via
    core.tools.register(...), sin que core/tools.py tenga que conocerla
    de antemano.

core/skills.py es quien descubre y carga estos modulos - agregar una
Skill nueva es agregar un archivo aca, no tocar el nucleo.
"""
