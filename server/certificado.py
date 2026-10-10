"""
Certificados para servir RemotePad por HTTPS (opcional, con --https).

Se crean dos piezas, guardadas en server/https/ (no se versiona):

  - una autoridad local (ca.pem / ca-key.pem), que se puede instalar en el
    celular para que el navegador confie sin avisos;
  - el certificado del servidor (cert.pem / key.pem), firmado por esa
    autoridad, valido para la IP de la red, 127.0.0.1 y el nombre de la PC.

Si la IP de la PC cambia, se vuelve a firmar el del servidor con la MISMA
autoridad: el celular que ya la tenia instalada sigue confiando.

Necesita el paquete `cryptography`, que solo hace falta para HTTPS:
    python -m pip install --user cryptography
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import os
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("remotepad")

HTTPS_DIR = Path(
    os.environ.get("REMOTEPAD_HTTPS_DIR")
    or (Path(__file__).resolve().parent / "https")
)
CA_DAYS = 3650
CERT_DAYS = 397          # limite que aceptan los navegadores para un certificado


class FaltaCryptography(RuntimeError):
    """No esta instalado el paquete necesario para crear certificados."""


@dataclass
class Certificados:
    cert: Path
    key: Path
    ca: Path
    huella_ca: str        # SHA-256 de la autoridad, para comprobarla a ojo

    def contexto_ssl(self) -> ssl.SSLContext:
        contexto = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        contexto.load_cert_chain(str(self.cert), str(self.key))
        return contexto


def _modulos():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as exc:
        raise FaltaCryptography(
            "Para usar HTTPS hace falta el paquete 'cryptography':\n"
            "    python -m pip install --user cryptography"
        ) from exc
    return x509, hashes, serialization, ec, ExtendedKeyUsageOID, NameOID


def _guardar_privado(ruta: Path, datos: bytes) -> None:
    ruta.write_bytes(datos)
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass


def _ahora() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _nombres(ip_red: str) -> tuple[list, set[str]]:
    """Nombres alternativos del certificado: IP de red, loopback y nombre."""
    x509 = _modulos()[0]
    ips = {"127.0.0.1"}
    if ip_red:
        ips.add(ip_red)
    dns = {"localhost"}
    try:
        dns.add(socket.gethostname())
    except Exception:
        pass
    entradas = [x509.IPAddress(ipaddress.ip_address(ip)) for ip in sorted(ips)]
    entradas += [x509.DNSName(nombre) for nombre in sorted(dns) if nombre]
    return entradas, ips


def _crear_ca(carpeta: Path):
    x509, hashes, serialization, ec, _eku, NameOID = _modulos()
    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "RemotePad - autoridad local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RemotePad"),
    ])
    ahora = _ahora()
    ca = (
        x509.CertificateBuilder()
        .subject_name(nombre).issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(clave.public_key()),
                       critical=False)
        .sign(clave, hashes.SHA256())
    )
    _guardar_privado(carpeta / "ca-key.pem", clave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    (carpeta / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    log.info("Creada la autoridad local de RemotePad (%s)", carpeta / "ca.pem")
    return ca, clave


def _crear_servidor(carpeta: Path, ca, ca_clave, ip_red: str) -> None:
    x509, hashes, serialization, ec, ExtendedKeyUsageOID, NameOID = _modulos()
    clave = ec.generate_private_key(ec.SECP256R1())
    alternativos, _ips = _nombres(ip_red)
    ahora = _ahora()
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, ip_red or "RemotePad"),
        ]))
        .issuer_name(ca.subject)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=CERT_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                       critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
            ca_clave.public_key()), critical=False)
        .sign(ca_clave, hashes.SHA256())
    )
    _guardar_privado(carpeta / "key.pem", clave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    (carpeta / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("Creado el certificado HTTPS para %s", ", ".join(sorted(_ips_de(cert))))


def _ips_de(cert) -> set[str]:
    x509 = _modulos()[0]
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return set()
    return {str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)}


def preparar(ip_red: str, carpeta: Optional[Path] = None) -> Certificados:
    """
    Devuelve certificados listos para usar, creandolos si hace falta.

    Se regenera el del servidor si no existe, si caduca en menos de 30 dias
    o si no incluye la IP de red actual.
    """
    x509, hashes, serialization, *_ = _modulos()
    carpeta = Path(carpeta or HTTPS_DIR)
    carpeta.mkdir(parents=True, exist_ok=True)

    ruta_ca, ruta_ca_clave = carpeta / "ca.pem", carpeta / "ca-key.pem"
    if ruta_ca.is_file() and ruta_ca_clave.is_file():
        ca = x509.load_pem_x509_certificate(ruta_ca.read_bytes())
        ca_clave = serialization.load_pem_private_key(ruta_ca_clave.read_bytes(), None)
    else:
        ca, ca_clave = _crear_ca(carpeta)

    ruta_cert, ruta_clave = carpeta / "cert.pem", carpeta / "key.pem"
    renovar = True
    if ruta_cert.is_file() and ruta_clave.is_file():
        actual = x509.load_pem_x509_certificate(ruta_cert.read_bytes())
        quedan = actual.not_valid_after_utc - _ahora()
        renovar = (
            quedan < datetime.timedelta(days=30)
            or (ip_red and ip_red not in _ips_de(actual))
            or actual.issuer != ca.subject
        )
    if renovar:
        _crear_servidor(carpeta, ca, ca_clave, ip_red)

    huella = ca.fingerprint(hashes.SHA256()).hex().upper()
    return Certificados(cert=ruta_cert, key=ruta_clave, ca=ruta_ca,
                        huella_ca=":".join(huella[i:i + 2] for i in range(0, 16, 2)))
