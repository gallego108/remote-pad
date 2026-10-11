"""
Rutas de datos cuando RemotePad va instalado (empaquetado con PyInstaller).

El programa vive en Archivos de programa, donde el usuario no puede escribir.
Los datos (accesos, ajustes, historial, registro) van a la carpeta RemotePad
dentro de APPDATA.
Este modulo se importa el primero en los dos ejecutables; en desarrollo no hace nada.
"""

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    _datos = Path(os.environ["APPDATA"]) / "RemotePad"
    _datos.mkdir(parents=True, exist_ok=True)
    _archivos = {
        "REMOTEPAD_TOKENS": "tokens.json",
        "REMOTEPAD_PROFILES": "profiles.json",
        "REMOTEPAD_LEARNING": "learning.json",
        "REMOTEPAD_HISTORY": "history.json",
        "REMOTEPAD_CONFIG": "config.json",
        "REMOTEPAD_HTTPS_DIR": "https",
        "REMOTEPAD_LOG": "servidor.log",
        "REMOTEPAD_CONSOLA": "consola.log",
        "REMOTEPAD_ESCRITORIO": "escritorio.json",
        "REMOTEPAD_DESPERTADOR_LOG": "despertador.log",
    }
    for _variable, _nombre in _archivos.items():
        os.environ.setdefault(_variable, str(_datos / _nombre))
