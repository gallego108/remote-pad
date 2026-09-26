"""
Prueba de capacidad: QR llenos al maximo segun nuestra tabla.

Si la capacidad calculada fuese mayor que la real, el QR tendria datos de mas
y ningun lector podria descodificarlo. Por eso se llena cada version y nivel
hasta el limite exacto que dice nuestro codigo y se comprueba con el lector.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import numpy as np
import zxingcpp

import qr


def render(matrix, scale: int = 5, quiet: int = 4):
    size = len(matrix)
    span = (size + quiet * 2) * scale
    image = np.full((span, span), 255, dtype=np.uint8)
    for row in range(size):
        for column in range(size):
            if matrix[row][column]:
                image[(row + quiet) * scale:(row + quiet + 1) * scale,
                      (column + quiet) * scale:(column + quiet + 1) * scale] = 0
    return image


def capacity_bytes(version: int, ecl: str) -> int:
    """Cuantos bytes de texto caben, descontando cabecera, terminador y relleno."""
    total_bits = qr.DATA_CODEWORDS[ecl][version] * 8
    count_bits = qr._character_count_bits(version)
    return (total_bits - 4 - count_bits) // 8


def main() -> int:
    failures = 0
    total = 0
    print("QR llenos al maximo de su capacidad")
    print("=" * 74)
    for version in (1, 2, 3, 4, 5, 7, 10):
        for ecl in ("L", "M", "Q", "H"):
            size = capacity_bytes(version, ecl)
            text = "".join(chr(ord("a") + (i % 26)) for i in range(size))
            try:
                matrix = qr.encode(text, ecl)
            except Exception as exc:
                print(f"  v{version} {ecl}: nuestro codigo no pudo ({exc})")
                failures += 1
                continue

            got_version = (len(matrix) - 17) // 4
            results = zxingcpp.read_barcodes(render(matrix))
            read = results[0].text if results else None
            ok = read == text and got_version == version
            total += 1
            if not ok:
                failures += 1
            detail = ""
            if not ok:
                if got_version != version:
                    detail = f" (nuestra version elegida: {got_version}, esperada {version})"
                else:
                    detail = f" (leido {len(read) if read else 0} de {len(text)} caracteres)"
            print(f"  [{'OK   ' if ok else 'FALLO'}] v{version} {ecl}: "
                  f"{size} bytes exactos{detail}")

    print("\n" + "=" * 74)
    print("  La capacidad es correcta" if not failures
          else f"  {failures} de {total} fallos: la capacidad no cuadra")
    print("=" * 74)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
