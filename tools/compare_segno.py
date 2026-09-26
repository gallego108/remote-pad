"""
Compara nuestra matriz de QR con la de segno (generador de referencia)
modulo a modulo, forzando la misma version, nivel y mascara.

Es la verificacion definitiva: si ambas matrices coinciden celda a celda, el
generador es correcto. Y donde difieran, se ve exactamente que zona falla.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import qr

try:
    import segno
except ImportError:
    print("Falta segno:  python -m pip install --user segno")
    raise SystemExit(2)

TEXT = "http://192.168.1.9:8765/?k=AbCdEf123456"


def segno_matrix(text: str, version: int, ecl: str, mask: int) -> list[list[bool]]:
    code = segno.make_qr(text, version=version, error=ecl.lower(), mask=mask,
                         boost_error=False)
    return [[bool(module) for module in row] for row in code.matrix]


def our_matrix(text: str, version: int, ecl: str, mask: int) -> list[list[bool]]:
    """Nuestra matriz forzando version y mascara."""
    payload = text.encode("utf-8")
    size = 17 + 4 * version
    matrix, reserved = qr._make_matrix(size)
    qr._place_finder(matrix, reserved, 0, 0)
    qr._place_finder(matrix, reserved, 0, size - 7)
    qr._place_finder(matrix, reserved, size - 7, 0)
    qr._place_alignment(matrix, reserved, version)
    qr._place_timing(matrix, reserved)
    qr._place_dark_module(matrix, reserved)
    qr._place_version(matrix, reserved, version)
    qr._place_format(matrix, reserved, ecl, mask)
    qr._place_data(matrix, reserved,
                   qr._interleave(qr._encode_data(payload, version, ecl), version, ecl))
    return qr._apply_mask(matrix, reserved, mask)


def describe(cell: tuple[int, int], size: int, version: int) -> str:
    row, column = cell
    if row <= 7 and column <= 7:
        return "patron de posicion superior izquierdo"
    if row <= 7 and column >= size - 8:
        return "patron de posicion superior derecho"
    if row >= size - 8 and column <= 7:
        return "patron de posicion inferior izquierdo"
    if row == 6 or column == 6:
        return "temporizacion"
    if row == 8 or column == 8:
        return "zona de informacion de formato"
    positions = qr.ALIGNMENT_POSITIONS.get(version, [])
    for y in positions:
        for x in positions:
            if abs(row - y) <= 2 and abs(column - x) <= 2:
                return f"patron de alineacion ({y},{x})"
    return "zona de datos"


def main() -> int:
    print("Comparando con segno (generador de referencia)")
    print("=" * 72)
    total_failures = 0

    for version, ecl, mask, text in [
        (1, "M", 0, "hola"),
        (1, "M", 3, "http://x"),
        (1, "L", 7, "a"),
        (2, "M", 1, "http://192.168.1.9:8"),
        (3, "M", 1, TEXT),
        (3, "L", 5, TEXT),
        (3, "Q", 2, TEXT),
        (4, "M", 6, "un texto de prueba mas largo para la version cuatro"),
    ]:
        try:
            reference = segno_matrix(text, version, ecl, mask)
        except Exception as exc:
            print(f"\nv{version} {ecl} mascara {mask}: segno no puede ({exc})")
            continue

        mine = our_matrix(text, version, ecl, mask)
        size = len(reference)
        if len(mine) != size:
            print(f"\nv{version} {ecl} mascara {mask}: tamanos distintos "
                  f"({len(mine)} vs {size})")
            total_failures += 1
            continue

        differences = [(r, c) for r in range(size) for c in range(size)
                       if mine[r][c] != reference[r][c]]
        state = "IDENTICAS" if not differences else f"{len(differences)} diferencias"
        print(f"\nv{version} {ecl} mascara {mask} ({size}x{size}): {state}")
        if differences:
            total_failures += 1
            by_zone: dict[str, int] = {}
            for cell in differences:
                zone = describe(cell, size, version)
                by_zone[zone] = by_zone.get(zone, 0) + 1
            for zone, count in sorted(by_zone.items(), key=lambda item: -item[1]):
                print(f"    {count:>4} en {zone}")
            print("    primeras celdas distintas:")
            for cell in differences[:10]:
                print(f"      {cell}: nuestro={mine[cell[0]][cell[1]]} "
                      f"segno={reference[cell[0]][cell[1]]} ({describe(cell, size, version)})")

    print("\n" + "=" * 72)
    print("  El generador coincide con la referencia" if not total_failures
          else f"  {total_failures} combinaciones con diferencias")
    print("=" * 72)
    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
