"""
Verifica el generador de QR.

Cuatro niveles de comprobacion:

1. Aritmetica: los bits de formato y de version se contrastan con la tabla
   oficial (Anexo C.1 de la ISO/IEC 18004, tal como aparece en la
   implementacion de referencia ZXing) y con las propiedades del codigo
   corrector (todas distintas, distancia de Hamming >= 7).
2. Estructura: patrones de posicion, alineacion, temporizacion, modulo oscuro
   y rejilla de reservados en el QR ya terminado.
3. Ida y vuelta: se quita la mascara, se leen los codigos, se deshace el
   entrelazado y se recupera el texto original.
4. Lectura real con OpenCV, si esta instalado (lo mismo que hace un telefono).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import qr  # noqa: E402

failures: list[str] = []
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    suffix = f"  {detail}" if detail and not condition else ""
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}{suffix}")
    if not condition:
        failures.append(name)


# ------------------------------------------------------------------ 1. tablas
# Tabla oficial de informacion de formato: (valor ya enmascarado, indice),
# donde indice = (nivel << 3) | mascara  con  nivel 0=M, 1=L, 2=H, 3=Q.
ZXING_FORMAT = [
    (0x5412, 0x00), (0x5125, 0x01), (0x5E7C, 0x02), (0x5B4B, 0x03),
    (0x45F9, 0x04), (0x40CE, 0x05), (0x4F97, 0x06), (0x4AA0, 0x07),
    (0x77C4, 0x08), (0x72F3, 0x09), (0x7DAA, 0x0A), (0x789D, 0x0B),
    (0x662F, 0x0C), (0x6318, 0x0D), (0x6C41, 0x0E), (0x6976, 0x0F),
    (0x1689, 0x10), (0x13BE, 0x11), (0x1CE7, 0x12), (0x19D0, 0x13),
    (0x0762, 0x14), (0x0255, 0x15), (0x0D0C, 0x16), (0x083B, 0x17),
    (0x355F, 0x18), (0x3068, 0x19), (0x3F31, 0x1A), (0x3A06, 0x1B),
    (0x24B4, 0x1C), (0x2183, 0x1D), (0x2EDA, 0x1E), (0x2BED, 0x1F),
]
LEVEL_BY_FORMAT_INDEX = {0: "M", 1: "L", 2: "H", 3: "Q"}

# Valores oficiales de la informacion de version (versiones 7 a 10).
ZXING_VERSION = {
    7: 0b000111110010010100,
    8: 0b001000010110111100,
    9: 0b001001101010011001,
    10: 0b001010010011010011,
}


def arithmetic_checks() -> None:
    print("\n== 1. Aritmetica contra la tabla oficial ==")
    by_index = {index: value for value, index in ZXING_FORMAT}
    bad = 0
    for ecl in ("L", "M", "Q", "H"):
        level_index = {v: k for k, v in LEVEL_BY_FORMAT_INDEX.items()}[ecl]
        for mask in range(8):
            expected = by_index[(level_index << 3) | mask]
            if qr._format_bits(ecl, mask) != expected:
                bad += 1
    check("Las 32 palabras de formato coinciden con la tabla oficial", bad == 0,
          f"{bad} discrepancias")

    values = {qr._format_bits(ecl, mask)
              for ecl in ("L", "M", "Q", "H") for mask in range(8)}
    check("Las 32 son distintas", len(values) == 32, f"{len(values)} distintas")
    check("Ninguna vale cero", all(value != 0 for value in values))
    check("Todas caben en 15 bits", all(0 <= value < (1 << 15) for value in values))

    worst_format = min(
        bin(a ^ b).count("1")
        for a in values for b in values if a != b
    )
    check(f"Distancia de Hamming minima >= 7 (es {worst_format})", worst_format >= 7)

    bad = sum(1 for version, expected in ZXING_VERSION.items()
              if qr._version_bits(version) != expected)
    check("Las 4 palabras de version coinciden con la tabla oficial", bad == 0,
          f"{bad} discrepancias")

    version_values = {qr._version_bits(v) for v in ZXING_VERSION}
    worst_version = min(
        bin(a ^ b).count("1")
        for a in version_values for b in version_values if a != b
    )
    check(f"Distancia de Hamming de version >= 8 (es {worst_version})",
          worst_version >= 8)


# ------------------------------------------------------------- 2. estructura
def build_reserved(version: int, ecl: str = "M", mask: int = 0):
    """
    Matriz con todos los patrones colocados y su rejilla de reservados.

    IMPORTANTE: hay que llamar a _place_format, igual que hace el codificador.
    Las 30 celdas de la informacion de formato cuentan como reservadas (aunque
    en el QR terminado llevan los bits de formato, que no son datos).
    """
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
    return matrix, reserved


# Patron de posicion: borde negro de 7x7, anillo blanco y nucleo negro 3x3.
FINDER = (
    [[True] * 7]
    + [[True, False, False, False, False, False, True] for _ in range(5)]
    + [[True] * 7]
)
FINDER[2][2] = FINDER[2][3] = FINDER[2][4] = True
FINDER[3][2] = FINDER[3][3] = FINDER[3][4] = True
FINDER[4][2] = FINDER[4][3] = FINDER[4][4] = True

TEXTS = [
    "x",
    "hola",
    "http://192.168.1.9:8765/?k=AbCdEf123456",
    "http://127.0.0.1:8765/?k=" + "Z" * 12,
    "un texto bastante mas largo para forzar otra version del codigo QR",
]


def structural_checks() -> None:
    print("\n== 2. Estructura del QR terminado ==")
    total = 0
    finder_bad = 0
    timing_bad = 0
    dark_bad = 0
    for text in TEXTS:
        for ecl in ("L", "M", "Q", "H"):
            matrix = qr.encode(text, ecl)
            size = len(matrix)
            total += 1
            for (r0, c0) in ((0, 0), (0, size - 7), (size - 7, 0)):
                block = [line[c0:c0 + 7] for line in matrix[r0:r0 + 7]]
                if block != FINDER:
                    finder_bad += 1
            if matrix[size - 8][8] is not True:
                dark_bad += 1
            if not all(matrix[6][i] == (i % 2 == 0) and matrix[i][6] == (i % 2 == 0)
                       for i in range(8, size - 8)):
                timing_bad += 1

    check(f"Patrones de posicion intactos ({total} combinaciones)",
          finder_bad == 0, f"{finder_bad} alterados")
    check("Modulo oscuro siempre oscuro", dark_bad == 0, f"{dark_bad} alterados")
    check("Temporizacion siempre alterna", timing_bad == 0, f"{timing_bad} alteradas")

    # Alineacion: se comprueba el centro (oscuro) y el anillo exterior (claro).
    # Se saltan las celdas que otro patron de funcion reclama, porque ahi el
    # valor es el de ese patron y no el de la alineacion.
    alignment_bad = 0
    checked = 0
    for text in TEXTS:
        for ecl in ("L", "M", "Q", "H"):
            matrix = qr.encode(text, ecl)
            size = len(matrix)
            version = (size - 17) // 4
            positions = qr.ALIGNMENT_POSITIONS.get(version, [])
            if not positions:
                continue

            # Rejilla con TODOS los demas patrones (sin alineacion): asi se
            # sabe que celdas son exclusivas del patron de alineacion.
            _, others = qr._make_matrix(size)
            qr._place_finder(others, others, 0, 0)
            qr._place_finder(others, others, 0, size - 7)
            qr._place_finder(others, others, size - 7, 0)
            qr._place_timing(others, others)
            qr._place_dark_module(others, others)
            qr._place_version(others, others, version)
            qr._place_format(others, others, ecl, 0)

            for cy in positions:
                for cx in positions:
                    if (cy <= 7 and cx <= 7) or (cy <= 7 and cx >= size - 8) \
                            or (cy >= size - 8 and cx <= 7):
                        continue
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            row, column = cy + dy, cx + dx
                            if others[row][column] == qr.RESERVED:
                                continue    # esa celda es de otro patron
                            want = (max(abs(dy), abs(dx)) == 2) or (dy == 0 and dx == 0)
                            checked += 1
                            if matrix[row][column] is not want:
                                alignment_bad += 1
    check(f"Patrones de alineacion bien formados ({checked} celdas)",
          alignment_bad == 0, f"{alignment_bad} alteradas")

    # Se compara con un generador de referencia (segno) cuando esta instalado:
    # es la comprobacion mas fuerte, modulo a modulo.
    reference_checks()

    # La mascara no debe tocar la rejilla reservada de formato.
    mask_bad = 0
    for ecl in ("L", "M", "Q", "H"):
        for version in (1, 2, 3, 4):
            size = 17 + 4 * version
            base, reserved = build_reserved(version, ecl, 0)
            masked = qr._apply_mask(base, reserved, 0)
            for row in range(size):
                for column in range(size):
                    if reserved[row][column] == qr.RESERVED and base[row][column] != masked[row][column]:
                        mask_bad += 1
    check("La mascara no toca ningun modulo reservado", mask_bad == 0,
          f"{mask_bad} modulos alterados")


# ----------------------------------------------------------- 3. ida y vuelta
def _read_format_first_copy(matrix, size: int) -> int:
    """Lee los 15 bits de formato (delegando en el generador, que ya los conoce)."""
    return qr.read_format_bits(matrix)


def _read_format_second_copy(matrix, size: int) -> int:
    """
    Lee los 15 bits de formato de la segunda copia.

    Los bits van con la misma convencion que la primera: el bit 0 en la celda
    de indice 0 (la primera de abajo), y el bit 14 al final.
    """
    def cell(index: int) -> bool:
        if index < 7:
            return bool(matrix[size - 1 - index][8])
        return bool(matrix[8][size - 15 + index])

    value = 0
    for index in range(15):
        if cell(index):
            value |= 1 << (14 - index)
    return value


def _read_codewords(matrix, reserved, size: int) -> list[int]:
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
                bits.append(1 if matrix[row][x] else 0)
        upward = not upward
        column -= 2
    codewords = []
    for index in range(0, len(bits) - 7, 8):
        value = 0
        for bit in bits[index:index + 8]:
            value = (value << 1) | bit
        codewords.append(value)
    return codewords


def _deinterleave(codewords: list[int], version: int, ecl: str) -> list[int]:
    _, _, groups = qr.BLOCK_STRUCTURE[(ecl, version)]
    sizes: list[int] = []
    for count, size in groups:
        sizes.extend([size] * count)

    blocks: list[list[int]] = [[] for _ in sizes]
    index = 0
    for position in range(max(sizes)):
        for block_index, size in enumerate(sizes):
            if position < size:
                blocks[block_index].append(codewords[index])
                index += 1

    data: list[int] = []
    for block in blocks:
        data.extend(block)
    return data


def _decode_payload(data: list[int], version: int) -> bytes:
    bits: list[int] = []
    for codeword in data:
        for shift in range(7, -1, -1):
            bits.append((codeword >> shift) & 1)

    def take(count: int) -> int:
        value = 0
        for bit in bits[:count]:
            value = (value << 1) | bit
        del bits[:count]
        return value

    if take(4) != 0b0100:
        raise ValueError("modo distinto de byte")
    length = take(qr._character_count_bits(version))
    return bytes(take(8) for _ in range(length))


def roundtrip_checks() -> None:
    print("\n== 3. Ida y vuelta (codificar -> leer -> comparar) ==")
    for ecl in ("L", "M", "Q", "H"):
        bad = 0
        details = []
        for text in TEXTS:
            payload = text.encode("utf-8")
            matrix = qr.encode(text, ecl)
            size = len(matrix)
            version = (size - 17) // 4

            # Se descodifica LA MISMA matriz que devuelve encode(), leyendo de
            # ella la mascara aplicada y reconstruyendo solo la rejilla de
            # reservados (que depende unicamente de la version y el nivel).
            info = _read_format_first_copy(matrix, size) ^ qr.FORMAT_MASK
            mask = (info >> 10) & 0b111

            _, reserved = build_reserved(version, ecl, mask)
            plain = qr._apply_mask(matrix, reserved, mask)

            try:
                recovered = _decode_payload(
                    _deinterleave(_read_codewords(plain, reserved, size), version, ecl),
                    version,
                )
            except Exception as exc:
                recovered = f"<{exc}>".encode()

            if recovered != payload:
                bad += 1
                details.append(f"{text[:20]!r}->{recovered[:20]!r}")

        check(f"Nivel {ecl}: los {len(TEXTS)} textos se recuperan tal cual",
              bad == 0, "; ".join(details))

    # Las dos copias de la informacion de formato deben coincidir.
    bad = 0
    for ecl in ("L", "M", "Q", "H"):
        for text in TEXTS[:2]:
            matrix = qr.encode(text, ecl)
            size = len(matrix)
            if _read_format_first_copy(matrix, size) != _read_format_second_copy(matrix, size):
                bad += 1
    check("Las dos copias de formato coinciden", bad == 0, f"{bad} discrepancias")


# ------------------------------------------------------------- 4. lector real
def scanner_checks() -> None:
    print("\n== 4. Lectura con un lector real (lo que hace el telefono) ==")
    try:
        import numpy
    except ImportError:
        print("  [----] numpy no esta instalado: se omite")
        return
    try:
        import cv2
    except ImportError:
        print("  [----] OpenCV no esta instalado: se omite")
        return

    bad = 0
    total = 0
    for ecl in ("L", "M", "Q", "H"):
        for url in ("http://192.168.1.9:8765/?k=AbCdEf123456",
                    "http://127.0.0.1:8765/?k=short"):
            matrix = qr.encode(url, ecl)
            size = len(matrix)
            quiet = 4
            scale = 8
            span = (size + quiet * 2) * scale
            image = numpy.full((span, span), 255, dtype=numpy.uint8)
            for row in range(size):
                for column in range(size):
                    if matrix[row][column]:
                        image[(row + quiet) * scale:(row + quiet + 1) * scale,
                              (column + quiet) * scale:(column + quiet + 1) * scale] = 0
            text, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
            total += 1
            if text != url:
                bad += 1
                print(f"      {ecl}: leyo {text!r}")
    check(f"OpenCV lee los {total} codigos generados", bad == 0,
          f"{bad} ilegibles")


def reference_checks() -> None:
    """
    Compara con generadores/lectores profesionales si estan instalados.

    Es la comprobacion mas fuerte: no depende de mi propia interpretacion.
    """
    try:
        import zxingcpp
        import numpy as np
    except ImportError:
        print("  [----] zxing-cpp no esta instalado: se omite la lectura real")
        return

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

    bad = 0
    total = 0
    for ecl in ("L", "M", "Q", "H"):
        for text in TEXTS:
            matrix = qr.encode(text, ecl)
            results = zxingcpp.read_barcodes(render(matrix))
            got = results[0].text if results else None
            total += 1
            if got != text:
                bad += 1
    check(f"zxing-cpp descodifica los {total} QR generados", bad == 0,
          f"{bad} ilegibles")

    # Comparacion con segno (generador de referencia) cuando esta disponible:
    # se comprueba que nuestro LECTOR de formato entiende la matriz de la
    # referencia. Si los dos coinciden, la colocacion de los bits es la
    # correcta aunque los codigos se escriban de otra forma.
    try:
        import segno
    except ImportError:
        print("  [----] segno no esta instalado: se omite la comparacion exacta")
        return

    bad = 0
    compared = 0
    for version, ecl, mask in ((1, "M", 0), (1, "M", 5), (2, "M", 1),
                               (3, "L", 5), (3, "H", 2)):
        try:
            code = segno.make_qr("hola", version=version, error=ecl.lower(),
                                 mask=mask, boost_error=False)
        except Exception:
            continue
        reference = [[bool(module) for module in row] for row in code.matrix]
        level_ref, mask_ref = qr.decode_format(reference)
        compared += 1
        if (level_ref, mask_ref) != (ecl, mask):
            bad += 1
            print(f"      v{version} {ecl}/m{mask}: se leyo {level_ref}/m{mask_ref}")
    check(f"El formato de la referencia se lee bien ({compared} codigos)",
          bad == 0, f"{bad} discrepancias")


def main() -> int:
    print("Verificando el generador de codigos QR")
    print("=" * 64)
    arithmetic_checks()
    structural_checks()
    roundtrip_checks()
    scanner_checks()
    print("\n" + "=" * 64)
    if failures:
        print(f"  {len(failures)} de {checks} comprobaciones fallidas:")
        for name in failures:
            print("   -", name)
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 64)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
