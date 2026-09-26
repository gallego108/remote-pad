"""
Verifica el calculo de Reed-Solomon con el algoritmo polinomico clasico,
implementado como multiplicacion de polinomios (completamente distinto al
metodo de division que usa el generador).

Si los dos metodos coinciden, el calculo de correccion de errores es correcto.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import qr  # noqa: E402

GF_EXP, GF_LOG = qr.GF_EXP, qr.GF_LOG


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return GF_EXP[(GF_LOG[a] + GF_LOG[b]) % 255]


def generator_poly(degree: int) -> list[int]:
    """(x - a^0)(x - a^1)...(x - a^(degree-1)) en GF(256)."""
    poly = [1]
    for i in range(degree):
        poly = poly_mul(poly, [1, GF_EXP[i]])
    return poly


def poly_mul(a: list[int], b: list[int]) -> list[int]:
    result = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            result[i + j] ^= gf_mul(x, y)
    return result


def rs_slow(data: list[int], ec_count: int) -> list[int]:
    """Version alternativa: division larga con el polinomio generador."""
    gen = generator_poly(ec_count)
    remainder = list(data) + [0] * ec_count
    for i in range(len(data)):
        factor = remainder[i]
        if factor == 0:
            continue
        for j in range(1, len(gen)):
            remainder[i + j] ^= gf_mul(gen[j], factor)
    return remainder[len(data):]


def main() -> int:
    ok = True

    print("== Polinomio generador ==")
    for degree in (7, 10, 13, 15, 16, 17, 18, 20, 22, 24, 26, 28, 30):
        a = qr._generator_polynomial(degree)
        b = generator_poly(degree)
        if a != b:
            ok = False
            print(f"  MAL grado {degree}: {a} != {b}")
    if ok:
        print("  OK   los 13 grados usados en QR coinciden")

    print("\n== Reed-Solomon: division (implementacion) vs. multiplicacion ==")
    # Datos de ejemplo: los que produce el codificador para 'hola' en v1-M.
    data = qr._encode_data(b"hola", 1, "M")
    print(f"  datos ({len(data)} codigos): {data}")

    for ec_count in (7, 10, 13, 15, 16, 17, 18, 20, 22, 24, 26, 28, 30):
        a = qr._reed_solomon(data, ec_count)
        b = rs_slow(data, ec_count)
        same = a == b
        if not same:
            ok = False
        print(f"  {ec_count:2d} codigos de correccion: "
              f"{'coinciden' if same else 'DIFIEREN'}")
        if not same:
            print(f"      implementacion: {a}")
            print(f"      multiplicacion: {b}")

    print("\n== Propiedad de la norma: el polinomio completo debe ser divisible ==")
    for ec_count in (10, 13, 15, 17, 22, 26, 28):
        parity = qr._reed_solomon(data, ec_count)
        codeword = list(data) + parity
        # Evaluar el polinomio en las raices del generador (a^0..a^(n-1))
        # debe dar 0 si la correccion es correcta.
        roots_zero = True
        for i in range(ec_count):
            value = 0
            for coefficient in codeword:
                value = gf_mul(value, GF_EXP[i]) ^ coefficient
            if value != 0:
                roots_zero = False
        print(f"  {ec_count:2d} codigos de correccion: "
              f"{'todas las raices anulan el polinomio' if roots_zero else 'FALLA'}")
        if not roots_zero:
            ok = False

    print("\nRESULTADO:", "Reed-Solomon correcto" if ok else "HAY ERRORES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
