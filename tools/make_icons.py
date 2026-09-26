"""
Genera los iconos PNG de la PWA sin dependencias externas.

Uso:
    python tools/make_icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

BG = (11, 15, 23)        # fondo oscuro
BODY = (79, 140, 255)    # cuerpo del touchpad (azul)
ACCENT = (34, 211, 166)  # linea del dedo (verde azulado)


def make_icon(size: int) -> bytes:
    """Dibuja un rectangulo redondeado tipo touchpad con una linea vertical."""
    pixels = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]

    margin = size * 0.12
    radius = size * 0.22
    left, top = margin, margin
    right, bottom = size - margin, size - margin
    stroke = max(2.0, size * 0.028)   # grosor del anillo

    def inside_rounded(x: float, y: float) -> bool:
        if not (left <= x <= right and top <= y <= bottom):
            return False
        cx = min(max(x, left + radius), right - radius)
        cy = min(max(y, top + radius), bottom - radius)
        return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2

    # 1) Disco redondeado exterior con el color del cuerpo
    for y in range(size):
        for x in range(size):
            if inside_rounded(x + 0.5, y + 0.5):
                pixels[y][x] = (*BODY, 255)

    # 2) Hueco interior: convierte el disco en un anillo
    inner_margin = margin + stroke
    inner_radius = max(0.0, radius - stroke)
    il, it = inner_margin, inner_margin
    ir, ib = size - inner_margin, size - inner_margin

    def inside_inner(x: float, y: float) -> bool:
        if not (il <= x <= ir and it <= y <= ib):
            return False
        cx = min(max(x, il + inner_radius), ir - inner_radius)
        cy = min(max(y, it + inner_radius), ib - inner_radius)
        return (x - cx) ** 2 + (y - cy) ** 2 <= inner_radius ** 2

    for y in range(size):
        for x in range(size):
            if inside_inner(x + 0.5, y + 0.5):
                pixels[y][x] = (*BG, 255)

    # Linea vertical (el "dedo")
    cx = size / 2
    line_w = max(1.5, size * 0.022)
    y0, y1 = size * 0.30, size * 0.52
    for y in range(int(y0), int(y1)):
        for x in range(size):
            if abs(x + 0.5 - cx) <= line_w:
                pixels[y][x] = (*ACCENT, 255)

    # Linea horizontal (la "zona de botones")
    x0, x1 = size * 0.32, size * 0.68
    for x in range(int(x0), int(x1)):
        for y in range(size):
            if abs(y + 0.5 - size * 0.62) <= line_w:
                pixels[y][x] = (*ACCENT, 255)

    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for pixel in row:
            raw.extend(pixel)
    return png_chunk(size, size, bytes(raw))


def png_chunk(width: int, height: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    WEB.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        target = WEB / f"icon-{size}.png"
        target.write_bytes(make_icon(size))
        print(f"Generado: {target}")


if __name__ == "__main__":
    main()
