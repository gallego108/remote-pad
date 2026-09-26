"""
Generador de codigos QR (sin dependencias externas).

Implementa lo necesario para codificar una URL corta en modo byte:
  - relleno y correccion de errores Reed-Solomon sobre GF(256)
  - reparto en bloques segun la version y el nivel de correccion
  - colocacion de modulos, patrones de posicion, alineacion y temporizacion
  - informacion de formato y de version
  - eleccion de la mascara optima por puntuacion de penalizacion

Permite dibujar el QR en la consola (media altura por linea, con colores
ANSI) o devolver la matriz de modulos para dibujarla en HTML.

Uso rapido:
    from qr import encode
    matrix = encode("http://192.168.1.9:8765/?k=abc")
    print(render_terminal(matrix))
"""

from __future__ import annotations

from typing import List, Optional, Sequence

# --------------------------------------------------------------------- tablas
# Numero de codigos de datos por version (indice 1..26) para cada nivel.
DATA_CODEWORDS = {
    "L": [None, 19, 34, 55, 80, 108, 136, 156, 194, 232, 274, 324, 370, 428, 461,
          523, 589, 647, 721, 795, 861, 932, 1006, 1094, 1174, 1276, 1370],
    "M": [None, 16, 28, 44, 64, 86, 108, 124, 154, 182, 216, 254, 290, 334, 365,
          415, 453, 507, 563, 627, 669, 714, 782, 860, 932, 1006, 1094],
    "Q": [None, 13, 22, 34, 48, 62, 76, 88, 110, 132, 154, 180, 206, 244, 261,
          295, 325, 367, 397, 445, 485, 512, 568, 614, 664, 718, 754],
    "H": [None, 9, 16, 26, 36, 46, 60, 66, 86, 100, 122, 140, 158, 180, 197,
          223, 253, 283, 313, 341, 385, 406, 442, 464, 514, 538, 596],
}

# Estructura de bloques: (total de codigos, codigos de correccion por bloque,
# [(bloques, codigos de datos por bloque), ...])
BLOCK_STRUCTURE = {
    ("L", 1): (26, 7, [(1, 19)]),
    ("L", 2): (44, 10, [(1, 34)]),
    ("L", 3): (70, 15, [(1, 55)]),
    ("L", 4): (100, 20, [(1, 80)]),
    ("L", 5): (134, 26, [(1, 108)]),
    ("L", 6): (172, 18, [(2, 68)]),
    ("L", 7): (196, 20, [(2, 78)]),
    ("L", 8): (242, 24, [(2, 97)]),
    ("L", 9): (292, 30, [(2, 116)]),
    ("L", 10): (346, 18, [(2, 68), (2, 69)]),
    ("M", 1): (26, 10, [(1, 16)]),
    ("M", 2): (44, 16, [(1, 28)]),
    ("M", 3): (70, 26, [(1, 44)]),
    ("M", 4): (100, 18, [(2, 32)]),
    ("M", 5): (134, 24, [(2, 43)]),
    ("M", 6): (172, 16, [(4, 27)]),
    ("M", 7): (196, 18, [(4, 31)]),
    ("M", 8): (242, 22, [(2, 38), (2, 39)]),
    ("M", 9): (292, 22, [(3, 36), (2, 37)]),
    ("M", 10): (346, 26, [(4, 43), (1, 44)]),
    ("Q", 1): (26, 13, [(1, 13)]),
    ("Q", 2): (44, 22, [(1, 22)]),
    ("Q", 3): (70, 18, [(2, 17)]),
    ("Q", 4): (100, 26, [(2, 24)]),
    ("Q", 5): (134, 18, [(2, 15), (2, 16)]),
    ("Q", 6): (172, 24, [(4, 19)]),
    ("Q", 7): (196, 18, [(2, 14), (4, 15)]),
    ("Q", 8): (242, 22, [(4, 18), (2, 19)]),
    ("Q", 9): (292, 20, [(4, 16), (4, 17)]),
    ("Q", 10): (346, 24, [(6, 19), (2, 20)]),
    ("H", 1): (26, 17, [(1, 9)]),
    ("H", 2): (44, 28, [(1, 16)]),
    ("H", 3): (70, 22, [(2, 13)]),
    ("H", 4): (100, 16, [(4, 9)]),
    ("H", 5): (134, 22, [(2, 11), (2, 12)]),
    ("H", 6): (172, 28, [(4, 15)]),
    ("H", 7): (196, 26, [(4, 13), (1, 14)]),
    ("H", 8): (242, 26, [(4, 14), (2, 15)]),
    ("H", 9): (292, 24, [(4, 12), (4, 13)]),
    ("H", 10): (346, 28, [(6, 15), (2, 16)]),
}

ALIGNMENT_POSITIONS = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

# Indicador de nivel de correccion usado por la informacion de formato.
ECL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

FORMAT_GENERATOR = 0b10100110111
FORMAT_MASK = 0b101010000010010

VERSION_GENERATOR = 0b1111100100101

MAX_VERSION = 10

# Modulos reservados (patrones). 1 = reservado, 0 = libre para datos.
RESERVED = 1
FREE = 0


# ------------------------------------------------------------ campo de Galois
def _build_gf() -> tuple[list[int], list[int]]:
    """Tablas de exponenciales y logaritmos de GF(256) con polinomio 0x11D."""
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for power in range(255):
        exp[power] = value
        log[value] = power
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for power in range(255, 512):
        exp[power] = exp[power - 255]
    return exp, log


GF_EXP, GF_LOG = _build_gf()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]


def _generator_polynomial(degree: int) -> list[int]:
    """Polinomio generador de Reed-Solomon de grado `degree`."""
    poly = [1]
    for index in range(degree):
        factor = [1, GF_EXP[index]]
        result = [0] * (len(poly) + 1)
        for i, coefficient in enumerate(poly):
            result[i] ^= coefficient
            result[i + 1] ^= _gf_mul(coefficient, factor[1])
        poly = result
    return poly


_GENERATOR_CACHE: dict[int, list[int]] = {}


def _reed_solomon(data: Sequence[int], ec_count: int) -> list[int]:
    """Calcula los `ec_count` codigos de correccion de un bloque de datos."""
    generator = _GENERATOR_CACHE.get(ec_count)
    if generator is None:
        generator = _generator_polynomial(ec_count)
        _GENERATOR_CACHE[ec_count] = generator

    remainder = [0] * ec_count
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor:
            for index, coefficient in enumerate(generator[1:]):
                remainder[index] ^= _gf_mul(coefficient, factor)
    return remainder


# ---------------------------------------------------------------- codificacion
def _character_count_bits(version: int) -> int:
    return 8 if version < 10 else 16


def _choose_version(length: int, ecl: str) -> int:
    for version in range(1, MAX_VERSION + 1):
        structure = BLOCK_STRUCTURE.get((ecl, version))
        if structure is None:
            continue
        capacity = DATA_CODEWORDS[ecl][version]
        count_bits = _character_count_bits(version)
        needed = 4 + count_bits + length * 8
        if needed <= capacity * 8:
            return version
    raise ValueError(
        f"El texto es demasiado largo para un QR (version maxima {MAX_VERSION}): "
        f"{length} caracteres"
    )


def _encode_data(payload: bytes, version: int, ecl: str) -> list[int]:
    """Cabecera + datos + terminador + relleno, y reparto en bloques."""
    total_data = DATA_CODEWORDS[ecl][version]
    count_bits = _character_count_bits(version)

    bits: list[int] = []

    def push(value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)

    push(0b0100, 4)                 # modo byte
    push(len(payload), count_bits)
    for byte in payload:
        push(byte, 8)

    capacity_bits = total_data * 8
    push(0, min(4, capacity_bits - len(bits)))       # terminador
    while len(bits) % 8:
        bits.append(0)

    codewords: list[int] = []
    for index in range(0, len(bits), 8):
        value = 0
        for bit in bits[index:index + 8]:
            value = (value << 1) | bit
        codewords.append(value)

    pad = (0xEC, 0x11)
    index = 0
    while len(codewords) < total_data:
        codewords.append(pad[index % 2])
        index += 1

    return codewords


def _interleave(codewords: list[int], version: int, ecl: str) -> list[int]:
    """Reparte los datos en bloques, anade correccion y entrelaza todo."""
    total, ec_per_block, groups = BLOCK_STRUCTURE[(ecl, version)]
    blocks: list[list[int]] = []
    data_sizes: list[int] = []
    offset = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(codewords[offset:offset + size])
            data_sizes.append(size)
            offset += size

    ec_blocks = [_reed_solomon(block, ec_per_block) for block in blocks]

    result: list[int] = []
    for index in range(max(data_sizes)):
        for block in blocks:
            if index < len(block):
                result.append(block[index])
    for index in range(ec_per_block):
        for block in ec_blocks:
            result.append(block[index])
    return result


# -------------------------------------------------------------------- matriz
def _make_matrix(size: int) -> tuple[list[list[bool]], list[list[bool]]]:
    matrix = [[False] * size for _ in range(size)]
    reserved = [[FREE] * size for _ in range(size)]
    return matrix, reserved


def _place_finder(matrix, reserved, row: int, column: int) -> None:
    size = len(matrix)
    for dy in range(-1, 8):
        for dx in range(-1, 8):
            y, x = row + dy, column + dx
            if not (0 <= y < size and 0 <= x < size):
                continue
            inside = 0 <= dy <= 6 and 0 <= dx <= 6
            border = dy in (0, 6) or dx in (0, 6)
            core = 2 <= dy <= 4 and 2 <= dx <= 4
            matrix[y][x] = bool(inside and (border or core))
            reserved[y][x] = RESERVED


def _place_alignment(matrix, reserved, version: int) -> None:
    """
    Patrones de alineacion.

    Solo se omiten los tres que caerian dentro de un patron de posicion. El
    limite correcto es el indice 7 (ultima fila/columna del propio patron) y
    size-8: usar otro margen descarta patrones necesarios y la capacidad de
    datos deja de cuadrar con la norma.
    """
    positions = ALIGNMENT_POSITIONS.get(version, [])
    if not positions:
        return
    size = len(matrix)
    for y in positions:
        for x in positions:
            if (y <= 7 and x <= 7) or (y <= 7 and x >= size - 8) or (y >= size - 8 and x <= 7):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    target_y, target_x = y + dy, x + dx
                    if not (0 <= target_y < size and 0 <= target_x < size):
                        continue
                    is_border = max(abs(dy), abs(dx)) == 2
                    matrix[target_y][target_x] = bool(is_border or (dy == 0 and dx == 0))
                    reserved[target_y][target_x] = RESERVED


def _place_timing(matrix, reserved) -> None:
    """
    Patrones de temporizacion: fila 6 y columna 6, alternando.

    Van del centro de un patron de posicion al del siguiente, es decir hasta
    size-9 (centro del patron de la esquina opuesta). Parar antes dejaria
    celdas sin reservar y la capacidad de datos no cuadraria con la norma.
    """
    size = len(matrix)
    for index in range(8, size - 8):
        dark = index % 2 == 0
        matrix[6][index] = dark
        reserved[6][index] = RESERVED
        matrix[index][6] = dark
        reserved[index][6] = RESERVED


def _place_dark_module(matrix, reserved) -> None:
    size = len(matrix)
    matrix[size - 8][8] = True
    reserved[size - 8][8] = RESERVED


def poly_remainder(dividend: int, generator: int) -> int:
    """
    Resto de dividir dos polinomios sobre GF(2), representados como enteros
    (el bit N es el coeficiente de x^N).

    Se elimina el termino de mayor grado en cada paso desplazando el
    generador hasta alinearlo. El bucle sigue mientras el termino de mayor
    grado del dividendo no baje del grado del generador.
    """
    degree = generator.bit_length() - 1
    while dividend.bit_length() - 1 >= degree:
        dividend ^= generator << (dividend.bit_length() - 1 - degree)
    return dividend


def _format_bits(ecl: str, mask: int) -> int:
    """
    Informacion de formato: 5 bits de datos, 10 de correccion BCH y una
    mascara fija.

    Los 5 bits de datos se desplazan 10 posiciones (los que ocupa la
    correccion) y el resto de esa division es el BCH. Ojo: hay que reducir el
    DIVIDENDO, no el resto, que es donde es facil equivocarse.
    """
    data = (ECL_BITS[ecl] << 3) | mask
    remainder = poly_remainder(data << 10, FORMAT_GENERATOR)
    return ((data << 10) | remainder) ^ FORMAT_MASK


def _format_bit(ecl: str, mask: int, position: int) -> bool:
    """Bit `position` (0 = el menos significativo) de la informacion de formato."""
    return bool((_format_bits(ecl, mask) >> position) & 1)


def _place_format(matrix, reserved, ecl: str, mask: int) -> None:
    """
    Coloca las dos copias de la informacion de formato.

    Orden de los bits: la norma numera la palabra de formato con el bit 14
    (el mas significativo) en la primera posicion. Es decir, la primera celda
    de la fila 8 lleva el bit 14, la siguiente el 13, y asi hasta el bit 0.
    Confundir ese orden (escribirlos al reves) produce un QR que se ve
    perfecto pero que ningun lector reconoce: la mascara leida es otra.

    Posiciones:
      primera copia -> fila 8 columnas 0..5, columna 6 fila 8, fila 8 columna
                       7, fila 8 columna 8, y columna 8 filas 5..0
      segunda copia -> columna 8 filas size-1..size-7 y fila 8 columnas
                       size-8..size-1
      el modulo oscuro de (size-8, 8) NO es formato: queda fuera de la mascara
    """
    size = len(matrix)
    value = _format_bits(ecl, mask)

    def bit(position: int) -> bool:
        """
        Bit que va en la celda de indice `position` de la secuencia de formato.

        Verificado con dos lectores independientes (zxing y segno): la
        secuencia empieza por el bit 14 y termina en el bit 0.
        """
        return bool((value >> (14 - position)) & 1)

    # --- Primera copia -------------------------------------------------
    #   (8,0)..(8,5) -> bits 14..9
    #   (8,7)        -> bit 8
    #   (7,8)        -> bit 7
    #   (8,8)        -> bit 6
    #   (5,8)..(0,8) -> bits 5..0
    for index in range(6):
        matrix[8][index] = bit(index)
        reserved[8][index] = RESERVED
    matrix[8][7] = bit(6)
    reserved[8][7] = RESERVED
    matrix[7][8] = bit(7)
    reserved[7][8] = RESERVED
    matrix[8][8] = bit(8)
    reserved[8][8] = RESERVED
    for index in range(9, 15):
        matrix[14 - index][8] = bit(index)
        reserved[14 - index][8] = RESERVED

    # --- Segunda copia -------------------------------------------------
    for index in range(7):
        matrix[size - 1 - index][8] = bit(index)
        reserved[size - 1 - index][8] = RESERVED
    for index in range(7, 15):
        matrix[8][size - 15 + index] = bit(index)
        reserved[8][size - 15 + index] = RESERVED


def _version_bits(version: int) -> int:
    """Informacion de version (solo para versiones 7 o superiores)."""
    remainder = poly_remainder(version << 12, VERSION_GENERATOR)
    return (version << 12) | remainder


def _place_version(matrix, reserved, version: int) -> None:
    if version < 7:
        return
    size = len(matrix)
    bits = _version_bits(version)
    for index in range(18):
        bit = bool((bits >> index) & 1)
        row = index // 3
        column = index % 3
        matrix[size - 11 + column][row] = bit
        reserved[size - 11 + column][row] = RESERVED
        matrix[row][size - 11 + column] = bit
        reserved[row][size - 11 + column] = RESERVED


def _place_data(matrix, reserved, codewords: list[int]) -> None:
    size = len(matrix)
    bits: list[int] = []
    for codeword in codewords:
        for shift in range(7, -1, -1):
            bits.append((codeword >> shift) & 1)

    index = 0
    upward = True
    column = size - 1
    while column > 0:
        if column == 6:
            column -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for offset in range(2):
                x = column - offset
                if reserved[row][x] == RESERVED:
                    continue
                value = False
                if index < len(bits):
                    value = bool(bits[index])
                    index += 1
                matrix[row][x] = value
        upward = not upward
        column -= 2


# --------------------------------------------------------------------- mascara
def _mask_condition(mask: int, row: int, column: int) -> bool:
    if mask == 0:
        return (row + column) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return column % 3 == 0
    if mask == 3:
        return (row + column) % 3 == 0
    if mask == 4:
        return (row // 2 + column // 3) % 2 == 0
    if mask == 5:
        return (row * column) % 2 + (row * column) % 3 == 0
    if mask == 6:
        return ((row * column) % 2 + (row * column) % 3) % 2 == 0
    return ((row + column) % 2 + (row * column) % 3) % 2 == 0


def _apply_mask(matrix, reserved, mask: int) -> list[list[bool]]:
    size = len(matrix)
    result = [row[:] for row in matrix]
    for row in range(size):
        for column in range(size):
            if reserved[row][column] == RESERVED:
                continue
            if _mask_condition(mask, row, column):
                result[row][column] = not result[row][column]
    return result


def _penalty(matrix: list[list[bool]]) -> int:
    size = len(matrix)
    score = 0

    # Regla 1: tramos de 5 o mas modulos iguales seguidos.
    for line in list(matrix) + [list(column) for column in zip(*matrix)]:
        run = 1
        for index in range(1, size):
            if line[index] == line[index - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)

    # Regla 2: bloques 2x2 del mismo color.
    for row in range(size - 1):
        for column in range(size - 1):
            block = (matrix[row][column], matrix[row][column + 1],
                     matrix[row + 1][column], matrix[row + 1][column + 1])
            if block[0] == block[1] == block[2] == block[3]:
                score += 3

    # Regla 3: patron 1:1:3:1:1 (parecido a un patron de posicion).
    pattern_a = [True, False, True, True, True, False, True,
                 False, False, False, False]
    pattern_b = list(reversed(pattern_a))
    for row in range(size):
        for column in range(size - 10):
            window = [matrix[row][column + offset] for offset in range(11)]
            if window == pattern_a or window == pattern_b:
                score += 40
    for column in range(size):
        for row in range(size - 10):
            window = [matrix[row + offset][column] for offset in range(11)]
            if window == pattern_a or window == pattern_b:
                score += 40

    # Regla 4: proporcion de modulos oscuros.
    dark = sum(1 for row in matrix for value in row if value)
    percent = dark * 100 / (size * size)
    score += 10 * (abs(percent - 50) // 5)
    return score


# ------------------------------------------------------------------------ API
def encode(text: str, ecl: str = "M") -> list[list[bool]]:
    """
    Codifica `text` y devuelve la matriz de modulos (True = modulo oscuro).

    `ecl` es el nivel de correccion: L (7%), M (15%), Q (25%) o H (30%).
    """
    ecl = ecl.upper()
    if ecl not in ECL_BITS:
        raise ValueError(f"Nivel de correccion invalido: {ecl}")

    payload = text.encode("utf-8")
    version = _choose_version(len(payload), ecl)
    size = 17 + 4 * version

    matrix, reserved = _make_matrix(size)
    _place_finder(matrix, reserved, 0, 0)
    _place_finder(matrix, reserved, 0, size - 7)
    _place_finder(matrix, reserved, size - 7, 0)
    _place_alignment(matrix, reserved, version)
    _place_timing(matrix, reserved)
    _place_dark_module(matrix, reserved)
    _place_version(matrix, reserved, version)

    codewords = _encode_data(payload, version, ecl)
    interleaved = _interleave(codewords, version, ecl)

    # Hay que marcar las posiciones de la informacion de formato ANTES de
    # colocar los datos: si no, esas 30 celdas cuentan como libres y los
    # datos se reparten por encima, desplazando todo el flujo de bits. Los
    # valores se reescriben luego para cada mascara.
    _place_format(matrix, reserved, ecl, 0)
    _place_data(matrix, reserved, interleaved)

    best: Optional[list[list[bool]]] = None
    best_score = None
    for mask in range(8):
        _place_format(matrix, reserved, ecl, mask)
        candidate = _apply_mask(matrix, reserved, mask)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    assert best is not None
    return best


def read_format_bits(matrix: Sequence[Sequence[bool]]) -> int:
    """
    Lee la informacion de formato de la primera copia.

    Devuelve la palabra de 15 bits ya enmascarada, tal como esta en la matriz.
    Sirve para comprobar el generador y como documentacion viva del orden: la
    primera celda lleva el bit 0 (el menos significativo).
    """
    def cell(position: int) -> bool:
        if position < 6:
            return bool(matrix[8][position])
        if position == 6:
            return bool(matrix[8][7])
        if position == 7:
            return bool(matrix[7][8])
        if position == 8:
            return bool(matrix[8][8])
        return bool(matrix[14 - position][8])

    value = 0
    for position in range(15):
        if cell(position):
            value |= 1 << (14 - position)
    return value


def decode_format(matrix: Sequence[Sequence[bool]]) -> tuple[str, int]:
    """Devuelve (nivel, mascara) que declara la informacion de formato."""
    unmasked = read_format_bits(matrix) ^ FORMAT_MASK
    level_bits = (unmasked >> 13) & 0b11
    level = {value: name for name, value in ECL_BITS.items()}[level_bits]
    return level, (unmasked >> 10) & 0b111


def to_ascii(matrix: Sequence[Sequence[bool]]) -> str:
    """Representacion en texto (util para guardar o depurar)."""
    return "\n".join(
        "".join("#" if value else "." for value in row) for row in matrix
    )


# --------------------------------------------------------------- consola ANSI
RESET = "\x1b[0m"
LIGHT = "\x1b[47m"      # fondo blanco
DARK = "\x1b[40m"       # fondo negro


def render_terminal(
    matrix: Sequence[Sequence[bool]],
    quiet_zone: int = 4,
    invert: bool = False,
) -> str:
    """
    Dibuja el QR en la consola usando medio bloque por linea.

    Cada caracter "▀" pinta dos modulos verticales (el de arriba con el color
    de texto y el de abajo con el de fondo), asi el codigo sale con la
    proporcion correcta y el doble de pequeno.

    `invert` no deberia usarse: los lectores esperan modulos oscuros sobre
    fondo claro. Aun asi se deja la opcion por si la consola tiene el tema
    invertido.
    """
    size = len(matrix)
    padded = size + quiet_zone * 2
    light, dark = (DARK, LIGHT) if invert else (LIGHT, DARK)

    def module(row: int, column: int) -> bool:
        y = row - quiet_zone
        x = column - quiet_zone
        if 0 <= y < size and 0 <= x < size:
            return bool(matrix[y][x])
        return False          # la zona de silencio es clara

    lines: list[str] = []
    # Solo se usan colores (no se cambia el caracter), asi que los espacios
    # conservan exactamente el ancho de cada modulo.
    lines.append(light + " " * padded + RESET)
    for row in range(0, padded, 2):
        parts: list[str] = []
        current = None
        for column in range(padded):
            top = module(row, column)
            bottom = module(row + 1, column) if row + 1 < padded else False
            if top and bottom:
                color = " "      # bloque lleno: color de texto
                cell = (dark, color)
            elif top:
                cell = (dark, "▀")
            elif bottom:
                cell = (light, "▄")
            else:
                cell = (light, " ")
            if cell[0] != current:
                parts.append(RESET if current is not None else "")
                parts.append(cell[0])
                current = cell[0]
            parts.append(cell[1])
        parts.append(RESET)
        lines.append("".join(parts))
    lines.append(light + " " * padded + RESET)
    return "\n".join(lines)


def enable_ansi() -> bool:
    """Activa las secuencias ANSI en la consola de Windows. True si se pudo."""
    try:
        import ctypes
        import sys
        if sys.platform != "win32":
            return True
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def supports_color() -> bool:
    import os
    import sys
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        return enable_ansi()
    return True
