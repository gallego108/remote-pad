"""Punto de entrada del panel empaquetado (RemotePad.exe)."""

import sys

import rutas_instalado  # noqa: F401  (debe ir antes que nada: fija las rutas de datos)
import remotepad_escritorio

sys.exit(remotepad_escritorio.main())
