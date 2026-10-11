"""
Punto de entrada del servidor empaquetado (RemotePadServidor.exe).

Sirve dos cosas: el servidor normal y, con --laser, el puntero laser (que el
servidor lanza como proceso aparte; en desarrollo lo lanza con python laser.py).
"""

import sys

import rutas_instalado  # noqa: F401  (debe ir antes que nada: fija las rutas de datos)

if "--laser" in sys.argv[1:]:
    import laser
    sys.exit(laser.main())

import app

sys.exit(app.main())
