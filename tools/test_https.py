"""
Pruebas del modo HTTPS (--https).

  A) Se crean la autoridad local y el certificado del servidor.
  B) El certificado sirve para la IP de la red y para 127.0.0.1.
  C) Un cliente que confia en la autoridad conecta sin avisos (HTTPS + WSS).
  D) El QR y las direcciones usan https://.
  E) /ca.crt entrega la autoridad, nunca la clave privada.
  F) Se reutiliza la autoridad: si cambia la IP, solo se refirma el servidor.

Se omite (sin fallar) si no esta instalado el paquete 'cryptography'.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "server"
PUERTO = 8794
sys.path.insert(0, str(SERVIDOR))

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def prueba_certificados(carpeta: Path) -> None:
    import certificado
    from cryptography import x509

    print("\n== A/B) Creacion de los certificados ==")
    primero = certificado.preparar("192.168.1.9", carpeta)
    for nombre in ("ca.pem", "ca-key.pem", "cert.pem", "key.pem"):
        check(f"Existe {nombre}", (carpeta / nombre).is_file())
    cert = x509.load_pem_x509_certificate(primero.cert.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    ips = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    check("Vale para la IP de red", "192.168.1.9" in ips, str(ips))
    check("Vale para 127.0.0.1", "127.0.0.1" in ips)
    dias = (cert.not_valid_after_utc - cert.not_valid_before_utc).days
    check("Duracion aceptada por los navegadores (<= 398 dias)", dias <= 398, str(dias))

    print("\n== F) Cambio de IP ==")
    ca_antes = primero.ca.read_bytes()
    cert_antes = primero.cert.read_bytes()
    igual = certificado.preparar("192.168.1.9", carpeta)
    check("Con la misma IP no se regenera nada",
          igual.cert.read_bytes() == cert_antes)
    otra = certificado.preparar("10.0.0.7", carpeta)
    check("Con otra IP se refirma el certificado",
          otra.cert.read_bytes() != cert_antes)
    check("Pero la autoridad es la misma", otra.ca.read_bytes() == ca_antes)


async def prueba_servidor(carpeta: Path) -> None:
    import aiohttp

    entorno = dict(os.environ)
    entorno.update({
        "REMOTEPAD_HTTPS_DIR": str(carpeta),
        "REMOTEPAD_TOKENS": str(carpeta / "tokens.json"),
        "REMOTEPAD_PROFILES": str(carpeta / "profiles.json"),
        "REMOTEPAD_LEARNING": str(carpeta / "learning.json"),
        "REMOTEPAD_HISTORY": str(carpeta / "history.json"),
        "REMOTEPAD_CONFIG": str(carpeta / "config.json"),
        "PYTHONIOENCODING": "utf-8",
    })
    proceso = subprocess.Popen(
        [sys.executable, "-u", "app.py", "--port", str(PUERTO), "--no-browser", "--https"],
        cwd=str(SERVIDOR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env=entorno,
    )
    salida: list[str] = []
    try:
        pin = ""
        limite = time.time() + 30
        while time.time() < limite and not pin:
            linea = proceso.stdout.readline()
            salida.append(linea)
            encontrado = re.search(r"PIN DE ACCESO\s*->\s*(\d{3})\s*(\d{3})", linea)
            if encontrado:
                pin = encontrado.group(1) + encontrado.group(2)
        check("El servidor arranca con --https", bool(pin), "".join(salida[-10:]))
        if not pin:
            return
        # Se lee hasta el aviso de HTTPS (va despues del banner).
        while time.time() < limite:
            linea = proceso.stdout.readline()
            salida.append(linea)
            if "huella" in linea:
                break
        texto = "".join(salida)

        print("\n== D) Direcciones con https ==")
        check("La direccion para el celular es https", "https://" in texto)
        check("No queda ninguna direccion http://", "http://" not in texto)
        check("Explica como instalar la autoridad", "/ca.crt" in texto)

        print("\n== C) Conexion de confianza ==")
        confianza = ssl.create_default_context(cafile=str(carpeta / "ca.pem"))
        base = f"https://127.0.0.1:{PUERTO}"
        async with aiohttp.ClientSession() as sesion:
            async with sesion.get(f"{base}/healthz", ssl=confianza) as r:
                check("HTTPS valida contra la autoridad local", r.status == 200)
            async with sesion.ws_connect(f"wss://127.0.0.1:{PUERTO}/ws", ssl=confianza,
                                         headers={"Origin": base}) as ws:
                await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin}}))
                respuesta = json.loads((await ws.receive(timeout=5)).data)
                check("WSS: entra con el PIN", respuesta.get("status") == "auth")
        sin_confianza = ssl.create_default_context()
        try:
            async with aiohttp.ClientSession() as sesion:
                async with sesion.get(f"{base}/healthz", ssl=sin_confianza):
                    pass
            rechazo = False
        except aiohttp.ClientConnectorCertificateError:
            rechazo = True
        check("Sin la autoridad, el certificado no se acepta", rechazo)

        print("\n== E) /ca.crt ==")
        async with aiohttp.ClientSession() as sesion:
            async with sesion.get(f"{base}/ca.crt", ssl=confianza) as r:
                cuerpo = await r.read()
                check("Se descarga", r.status == 200)
                check("Es la autoridad", cuerpo == (carpeta / "ca.pem").read_bytes())
                check("No contiene ninguna clave privada", b"PRIVATE KEY" not in cuerpo)
    finally:
        try:
            proceso.stdin.write("q\n")
            proceso.stdin.flush()
            proceso.wait(timeout=10)
        except Exception:
            proceso.kill()


def main() -> int:
    print("Modo HTTPS")
    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("  (sin el paquete 'cryptography': se omite; instala con "
              "python -m pip install --user cryptography)")
        return 0
    prueba_certificados(Path(tempfile.mkdtemp(prefix="remotepad_cert_")))
    asyncio.run(prueba_servidor(Path(tempfile.mkdtemp(prefix="remotepad_https_"))))
    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
