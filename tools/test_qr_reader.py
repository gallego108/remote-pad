"""
Prueba definitiva: genera codigos QR con nuestro generador y los descodifica
con un lector profesional independiente (zxing-cpp, el motor que usan muchos
lectores y telefonos).

Si el lector recupera exactamente el texto, el codigo es valido de verdad:
no depende de mi criterio ni de mi propio descodificador.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import qr  # noqa: E402

try:
    import numpy as np
    import zxingcpp
except ImportError as exc:
    print("Faltan dependencias para la prueba real:", exc)
    print("  python -m pip install --user zxing-cpp numpy")
    raise SystemExit(2)


def render(matrix, quiet: int = 4, scale: int = 6):
    """Convierte la matriz en una imagen (modulos oscuros sobre fondo claro)."""
    size = len(matrix)
    span = (size + quiet * 2) * scale
    image = np.full((span, span), 255, dtype=np.uint8)
    for row in range(size):
        for column in range(size):
            if matrix[row][column]:
                top = (row + quiet) * scale
                left = (column + quiet) * scale
                image[top:top + scale, left:left + scale] = 0
    return image


TESTS = [
    "http://192.168.1.9:8765/?k=AbCdEf123456",
    "http://127.0.0.1:8765/?k=x",
    "http://192.168.1.100:8765/?k=" + "Z" * 12,
    "a",
    "un texto bastante mas largo para forzar otra version del codigo QR, con mas contenido todavia",
]


def main() -> int:
    total = 0
    failures = 0
    print("Descodificando con zxing-cpp (lector independiente)")
    print("=" * 66)

    for ecl in ("L", "M", "Q", "H"):
        for text in TESTS:
            matrix = qr.encode(text, ecl)
            size = len(matrix)
            version = (size - 17) // 4
            image = render(matrix)

            results = zxingcpp.read_barcodes(image)
            got = results[0].text if results else None
            total += 1
            ok = got == text
            if not ok:
                failures += 1
            detail = f"v{version} {size}x{size}"
            if ok:
                print(f"  [OK   ] {ecl} {detail}: {text[:44]!r}")
            else:
                print(f"  [FALLO] {ecl} {detail}: esperado {text[:34]!r}")
                print(f"          leido: {got!r}")

    # Tambien con la imagen invertida (modulos claros sobre fondo oscuro),
    # por si la consola del usuario tuviera el tema cambiado.
    print("\n== Variante con colores invertidos ==")
    inverted_ok = 0
    for ecl in ("L", "M", "Q", "H"):
        text = "http://192.168.1.9:8765/?k=AbCdEf123456"
        matrix = qr.encode(text, ecl)
        image = 255 - render(matrix)
        results = zxingcpp.read_barcodes(image)
        got = results[0].text if results else None
        total += 1
        if got == text:
            inverted_ok += 1
        else:
            failures += 1
            print(f"  [FALLO] {ecl} invertido: leido {got!r}")
    print(f"  {inverted_ok}/4 codigos invertidos tambien se leen")

    # Y con la imagen reducida y con ruido, para acercarse a una foto real
    # hecha con la camara del telefono.
    print("\n== Variante reducida y con ruido (simula la camara) ==")
    rng = np.random.default_rng(20260926)
    robust_ok = 0
    robust_total = 0
    for ecl in ("L", "M", "Q", "H"):
        for text in TESTS[:3]:
            matrix = qr.encode(text, ecl)
            image = render(matrix, quiet=4, scale=3).astype(np.int16)
            noise = rng.integers(-40, 41, image.shape)
            noisy = np.clip(image + noise, 0, 255).astype(np.uint8)
            results = zxingcpp.read_barcodes(noisy)
            got = results[0].text if results else None
            robust_total += 1
            total += 1
            if got == text:
                robust_ok += 1
            else:
                print(f"  [FALLO] {ecl} con ruido: esperado {text[:30]!r}, leido {got!r}")
    print(f"  {robust_ok}/{robust_total} leidos con ruido y a menor escala")

    print("\n" + "=" * 66)
    print(f"  {total - failures} de {total} lecturas correctas")
    print("=" * 66)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
