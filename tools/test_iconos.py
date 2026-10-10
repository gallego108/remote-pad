"""
Pruebas de server/iconos.py (iconos de los programas abiertos, en PNG).

  - La transparencia se recupera comparando los dibujos sobre negro y
    sobre blanco: pixel opaco, transparente y semitransparente.
  - El PNG generado es valido (se decodifica de vuelta con zlib).
  - La cache no vuelve a dibujar, recuerda los "sin icono", descarta un
    icono vacio y respeta su limite.

Uso:
    python tools/test_iconos.py
"""

from __future__ import annotations

import base64
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import iconos  # noqa: E402

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def leer_png(datos: bytes) -> tuple[int, int, bytes]:
    """Decodificador minimo (solo RGBA de 8 bits sin filtro), para comprobar."""
    assert datos[:8] == b"\x89PNG\r\n\x1a\n"
    pos, ancho, alto, idat = 8, 0, 0, b""
    while pos < len(datos):
        largo = struct.unpack(">I", datos[pos:pos + 4])[0]
        tipo = datos[pos + 4:pos + 8]
        cuerpo = datos[pos + 8:pos + 8 + largo]
        crc = struct.unpack(">I", datos[pos + 8 + largo:pos + 12 + largo])[0]
        assert crc == zlib.crc32(tipo + cuerpo) & 0xFFFFFFFF, "crc"
        if tipo == b"IHDR":
            ancho, alto = struct.unpack(">II", cuerpo[:8])
            assert cuerpo[8:10] == b"\x08\x06", "RGBA de 8 bits"
        elif tipo == b"IDAT":
            idat += cuerpo
        pos += 12 + largo
    crudo = zlib.decompress(idat)
    fila = ancho * 4 + 1
    return ancho, alto, b"".join(crudo[y * fila + 1:(y + 1) * fila] for y in range(alto))


def main() -> int:
    print("\n== Transparencia (negro frente a blanco) ==")
    # BGRA: un rojo opaco, un hueco transparente y un azul al 50 %.
    negro = bytes([0, 0, 255, 0,   0, 0, 0, 0,     128, 0, 0, 0])
    blanco = bytes([0, 0, 255, 0,  255, 255, 255, 0,  255, 127, 127, 0])
    rgba = iconos.combinar_fondos(negro, blanco)
    check("Pixel opaco: color y alfa 255", rgba[0:4] == bytes([255, 0, 0, 255]), rgba[0:4].hex())
    check("Pixel transparente: alfa 0", rgba[7] == 0, rgba[4:8].hex())
    check("Pixel al 50 %: alfa ~128 y azul puro",
          abs(rgba[11] - 128) <= 1 and rgba[8] == 0 and rgba[10] >= 250, rgba[8:12].hex())
    check("Tamanos distintos se rechazan", _lanza(lambda: iconos.combinar_fondos(b"1234", b"")))
    check("Icono vacio detectado", iconos.es_vacio(bytes(16)) and not iconos.es_vacio(rgba))

    print("\n== PNG ==")
    pixeles = bytes(range(256)) * 4          # 16 x 16 RGBA
    png = iconos.png_rgba(16, 16, pixeles)
    ancho, alto, vuelta = leer_png(png)
    check("Se decodifica de vuelta igual", (ancho, alto, vuelta) == (16, 16, pixeles))
    check("Tamano incorrecto se rechaza", _lanza(lambda: iconos.png_rgba(4, 4, b"x")))

    print("\n== Cache ==")
    llamadas = []

    def dibujo():
        llamadas.append(1)
        return 2, 1, bytes([0, 0, 255, 0] * 2), bytes([0, 0, 255, 0] * 2)

    cache = iconos.CacheIconos(limite=2)
    url = cache.obtener("a.exe", dibujo)
    check("Devuelve un data URL PNG", bool(url) and url.startswith("data:image/png;base64,"))
    check("El PNG del data URL es valido",
          leer_png(base64.b64decode(url.split(",", 1)[1]))[:2] == (2, 1))
    check("La segunda vez no se dibuja", cache.obtener("a.exe", dibujo) == url
          and len(llamadas) == 1)

    sin = []
    check("Sin icono devuelve None",
          cache.obtener("b.exe", lambda: sin.append(1)) is None)
    cache.obtener("b.exe", lambda: sin.append(1))
    check("Y no se reintenta", len(sin) == 1)
    check("Un icono vacio cuenta como sin icono",
          cache.obtener("c.exe", lambda: (1, 1, bytes(4), bytes([255, 255, 255, 0]))) is None)
    check("Un error al dibujar no rompe nada",
          cache.obtener("d.exe", lambda: 1 / 0) is None)
    cache.obtener("a.exe", dibujo)
    check("Respeta el limite (lo mas antiguo se va)", len(llamadas) == 2)

    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


def _lanza(funcion) -> bool:
    try:
        funcion()
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
