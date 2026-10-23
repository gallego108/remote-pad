"""
Estado del escritorio remoto de Windows (RDP), para el icono "Escritorio"
del celular o la tableta.

RemotePad no activa RDP ni abre puertos: solo mira si Windows lo tiene
activado (registro, de solo lectura) y si el servicio contesta en el puerto
3389. Activarlo exige permisos de administrador, asi que lo hace el usuario en
Configuracion de Windows > Sistema > Escritorio remoto.

Las funciones de lectura se pasan como parametro, asi que se prueba sin tocar
el registro ni la red (ver tools/test_rdp.py).
"""

from __future__ import annotations

import platform
import socket
from typing import Callable, Optional

PUERTO_RDP = 3389
RUTA_REGISTRO = r"SYSTEM\CurrentControlSet\Control\Terminal Server"


def leer_activado() -> Optional[bool]:
    """True/False segun Windows; None si no se puede saber (p. ej. Windows Home)."""
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RUTA_REGISTRO) as clave:
            valor, _tipo = winreg.QueryValueEx(clave, "fDenyTSConnections")
    except OSError:
        return None
    return int(valor) == 0


def escucha_local(puerto: int = PUERTO_RDP, espera: float = 0.4) -> bool:
    """True si el servicio RDP acepta conexiones en esta PC."""
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=espera):
            return True
    except OSError:
        return False


def estado(
    ip_lan: str,
    nombre_pc: str,
    leer: Callable[[], Optional[bool]] = leer_activado,
    escuchar: Callable[[], bool] = escucha_local,
) -> dict:
    """Datos que muestra la app del celular para conectarse por RDP."""
    activado = leer()
    escucha = escuchar()
    if activado is None:
        mensaje = ("No se puede comprobar en esta PC. Mira en Configuración > "
                   "Sistema > Escritorio remoto (Windows Home no lo incluye).")
    elif not activado:
        mensaje = ("Está desactivado. Actívalo en Configuración > Sistema > "
                   "Escritorio remoto.")
    elif not escucha:
        mensaje = ("Está activado, pero el servicio no responde. Prueba a "
                   "reiniciar la PC.")
    else:
        mensaje = "Listo: abre Microsoft Remote Desktop en el celular y escribe la IP."
    return {
        "activado": activado,
        "escucha": escucha,
        "ip": ip_lan,
        "puerto": PUERTO_RDP,
        "pc": nombre_pc,
        "mensaje": mensaje,
    }
