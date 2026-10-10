"""
Iconos de los programas abiertos, como PNG para el celular.

native_input dibuja cada icono dos veces, sobre fondo negro y sobre fondo
blanco (BGRA de 32 bits). Comparando las dos imagenes se recupera la
transparencia sea cual sea el tipo de icono (con canal alfa o con mascara
antigua): donde el icono es opaco las dos coinciden y donde es transparente
se ve el fondo.

Este modulo es puro (sin Win32): se prueba con pixeles inventados.
"""

from __future__ import annotations

import base64
import struct
import zlib
from collections import OrderedDict
from typing import Callable, Optional

MAX_CACHE = 64


def combinar_fondos(negro: bytes, blanco: bytes) -> bytes:
    """De dos dibujos BGRA (fondo negro y fondo blanco) saca un RGBA."""
    if len(negro) != len(blanco) or len(negro) % 4:
        raise ValueError("tamanos distintos")
    salida = bytearray(len(negro))
    for i in range(0, len(negro), 4):
        bn, gn, rn = negro[i], negro[i + 1], negro[i + 2]
        bb, gb, rb = blanco[i], blanco[i + 1], blanco[i + 2]
        # Sobre negro: c * a. Sobre blanco: c * a + 255 * (1 - a).
        diferencia = ((bb - bn) + (gb - gn) + (rb - rn)) / 3
        alfa = max(0, min(255, round(255 - diferencia)))
        if alfa:
            salida[i] = min(255, round(rn * 255 / alfa))
            salida[i + 1] = min(255, round(gn * 255 / alfa))
            salida[i + 2] = min(255, round(bn * 255 / alfa))
        salida[i + 3] = alfa
    return bytes(salida)


def _bloque(tipo: bytes, datos: bytes) -> bytes:
    crc = zlib.crc32(tipo + datos) & 0xFFFFFFFF
    return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", crc)


def png_rgba(ancho: int, alto: int, rgba: bytes) -> bytes:
    """Codifica pixeles RGBA (fila a fila, de arriba abajo) como PNG."""
    if len(rgba) != ancho * alto * 4:
        raise ValueError("tamano de pixeles incorrecto")
    fila = ancho * 4
    crudo = b"".join(
        b"\x00" + rgba[y * fila:(y + 1) * fila] for y in range(alto)
    )
    cabecera = struct.pack(">IIBBBBB", ancho, alto, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _bloque(b"IHDR", cabecera)
        + _bloque(b"IDAT", zlib.compress(crudo, 9))
        + _bloque(b"IEND", b"")
    )


def es_vacio(rgba: bytes) -> bool:
    """True si todos los pixeles son transparentes (no habia icono que pintar)."""
    return not any(rgba[3::4])


class CacheIconos:
    """
    Iconos ya convertidos, por ruta del ejecutable: abrir la lista otra vez
    no vuelve a dibujar ni a comprimir nada. Guarda tambien los "sin icono"
    (None) para no reintentarlos en cada refresco.
    """

    def __init__(self, limite: int = MAX_CACHE) -> None:
        self._datos: OrderedDict[str, Optional[str]] = OrderedDict()
        self._limite = limite

    def obtener(
        self, clave: str,
        dibujar: Callable[[], Optional[tuple[int, int, bytes, bytes]]],
    ) -> Optional[str]:
        """Data URL del icono (o None). `dibujar` devuelve (ancho, alto, negro, blanco)."""
        if clave in self._datos:
            self._datos.move_to_end(clave)
            return self._datos[clave]
        url = None
        try:
            dibujo = dibujar()
            if dibujo:
                ancho, alto, negro, blanco = dibujo
                rgba = combinar_fondos(negro, blanco)
                if not es_vacio(rgba):
                    png = png_rgba(ancho, alto, rgba)
                    url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        except Exception:
            url = None
        self._datos[clave] = url
        while len(self._datos) > self._limite:
            self._datos.popitem(last=False)
        return url
