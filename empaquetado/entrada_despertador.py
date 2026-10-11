"""Punto de entrada del despertador empaquetado (RemotePadDespertador.exe)."""

import sys

import rutas_instalado  # noqa: F401  (debe ir antes que nada: fija las rutas de datos)
import despertador

sys.exit(despertador.main())
