"""
Extraccion fiable de la matriz de un QR generado por zxing.

Se pide la imagen a escala 1 (un pixel por modulo) con zona de silencio, que
es la unica forma de no inventarse modulos interpolando. Antes se extraia de
una imagen interpolada y las matrices salian mal, lo que invalidaba las
comparaciones: lo demuestra que zxing no podia leer ni su propio QR despues
de pasar por ese camino.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import zxingcpp

import qr


def zxing_matrix(text: str, version: int, ecl: str, quiet: int = 4) -> list[list[bool]]:
    """
    Matriz de modulos exacta del QR que genera zxing.

    Se usa to_image(scale=1), donde cada modulo ocupa exactamente un pixel.
    """
    barcode = zxingcpp.create_barcode(
        text, zxingcpp.BarcodeFormat.QRCode,
        ec_level={"L": 0, "M": 1, "Q": 2, "H": 3}[ecl], version=version,
    )
    image = np.array(barcode.to_image(scale=1, add_quiet_zones=True))
    pixels = image if image.ndim == 2 else image[:, :, 0]
    size = 17 + 4 * version

    if pixels.shape[0] < size + 2 * quiet:
        raise ValueError(f"imagen demasiado pequena: {pixels.shape}")

    matrix = []
    for row in range(size):
        line = []
        for column in range(size):
            line.append(bool(pixels[row + quiet][column + quiet] < 128))
        matrix.append(line)
    return matrix


def render(matrix, scale: int = 6, quiet: int = 4):
    size = len(matrix)
    span = (size + quiet * 2) * scale
    image = np.full((span, span), 255, dtype=np.uint8)
    for row in range(size):
        for column in range(size):
            if matrix[row][column]:
                image[(row + quiet) * scale:(row + quiet + 1) * scale,
                      (column + quiet) * scale:(column + quiet + 1) * scale] = 0
    return image


def main() -> int:
    text = "http://192.168.1.9:8765/?k=AbCdEf123456"
    failures = 0

    print("== 0) El canal de prueba funciona? ==")
    theirs = zxing_matrix(text, 3, "M")
    got = zxingcpp.read_barcodes(render(theirs))
    ok = bool(got) and got[0].text == text
    print(f"  [{'OK   ' if ok else 'FALLO'}] zxing lee su matriz extraida y "
          f"renderizada por nosotros: {got[0].text if got else None!r}")
    if not ok:
        failures += 1

    print("\n== 1) Nuestro descodificador vs. QR de zxing ==")
    from test_qr import _read_format_first_copy, build_reserved
    size = 29
    version = 3
    declared = _read_format_first_copy(theirs, size) ^ qr.FORMAT_MASK
    mask = (declared >> 10) & 7
    level = {1: "L", 0: "M", 3: "Q", 2: "H"}[declared >> 13]
    print(f"  mascara declarada {mask}, nivel declarado {level} (pedido M/mascara libre)")
    _, reserved = build_reserved(version, "M", mask)
    plain = qr._apply_mask(theirs, reserved, mask)
    bits: list[int] = []
    upward = True
    column = size - 1
    while column > 0:
        if column == 6:
            column -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for offset in range(2):
                x = column - offset
                if reserved[row][x] == qr.RESERVED:
                    continue
                bits.append(1 if plain[row][x] else 0)
        upward = not upward
        column -= 2
    length = 0
    for bit in bits[4:12]:
        length = (length << 1) | bit
    payload = bytearray()
    for index in range(12, 12 + length * 8, 8):
        value = 0
        for bit in bits[index:index + 8]:
            value = (value << 1) | bit
        payload.append(value)
    ok = bytes(payload) == text.encode()
    print(f"  [{'OK   ' if ok else 'FALLO'}] texto recuperado: {bytes(payload)!r}")
    if not ok:
        failures += 1

    print("\n== 2) zxing lee nuestros QR (textos y niveles varios) ==")
    for ecl in ("L", "M", "Q", "H"):
        for sample in ("x", "hola", text, "otro texto de prueba distinto"):
            mine = qr.encode(sample, ecl)
            results = zxingcpp.read_barcodes(render(mine))
            read = results[0].text if results else None
            ok = read == sample
            if not ok:
                failures += 1
            print(f"  [{'OK   ' if ok else 'FALLO'}] {ecl} v{(len(mine) - 17) // 4}: "
                  f"{sample[:28]!r} -> {read!r}")

    print("\n" + "=" * 70)
    print("  Los QR son validos" if not failures else f"  {failures} fallos")
    print("=" * 70)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
