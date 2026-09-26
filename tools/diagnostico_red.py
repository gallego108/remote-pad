"""
Diagnostico de conectividad: por que el celular no llega al servidor.

Comprueba, en orden:
  1. En que direccion escucha el servidor (debe ser 0.0.0.0).
  2. Si se puede conectar a traves de la IP de la red local (no solo 127.0.0.1).
  3. Como esta clasificada la red WiFi (Publica o Privada).
  4. Que reglas del Firewall de Windows afectan al puerto.

Todo lo que no requiera administrador se intenta; lo demas se avisa.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
failures: list[str] = []
notes: list[str] = []


def powershell(script: str, timeout: int = 25) -> str:
    """Ejecuta PowerShell y devuelve su salida (vacia si falla)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return f"<error: {exc}>"


def local_ips() -> list[str]:
    """IPv4 activas, sin la de loopback."""
    found: list[str] = []
    try:
        for line in subprocess.run(["ipconfig"], capture_output=True, text=True,
                                   timeout=10).stdout.splitlines():
            match = re.search(r"IPv4[^:]*:\s*([\d.]+)", line)
            if match and not match.group(1).startswith("127."):
                found.append(match.group(1))
    except Exception:
        pass
    if not found:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                found.append(sock.getsockname()[0])
        except Exception:
            pass
    return found


def check_listening() -> None:
    print("\n== 1. En que direccion escucha el servidor ==")
    output = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, timeout=15
    ).stdout
    listening = [
        line.split() for line in output.splitlines()
        if ":{}".format(PORT) in line and "LISTENING" in line
    ]
    if not listening:
        print(f"  [FALLO] Nada escucha en el puerto {PORT}: el servidor no esta en marcha")
        failures.append(f"el puerto {PORT} no esta a la escucha")
        return

    for parts in listening:
        address = parts[1]
        print(f"  [OK   ] Escuchando en {address}")
        if address.startswith("127."):
            print("           ^ solo loopback: el celular NO podra conectarse")
            failures.append("el servidor escucha solo en 127.0.0.1")
        elif address.startswith("0.0.0.0"):
            print("           ^ todas las interfaces: correcto")


def check_reachable() -> None:
    print("\n== 2. Alcance a traves de la IP de la red local ==")
    for ip in local_ips():
        for label, host in (("loopback", "127.0.0.1"), ("red local", ip)):
            try:
                with socket.create_connection((host, PORT), timeout=3):
                    print(f"  [OK   ] {label}: {host}:{PORT} responde")
            except Exception as exc:
                print(f"  [FALLO] {label}: {host}:{PORT} no responde ({exc})")
                if label == "red local":
                    failures.append(f"no responde en la IP de red local {ip}")

    print("\n  Direccion que debe abrir el celular:")
    for ip in local_ips():
        print(f"     http://{ip}:{PORT}")
    print("  (el celular debe estar en la MISMA red WiFi que esta PC)")


def check_network_profile() -> None:
    print("\n== 3. Clasificacion de la red (Publica o Privada) ==")
    output = powershell(
        "Get-NetConnectionProfile | "
        "Select-Object Name,InterfaceAlias,NetworkCategory | ConvertTo-Json -Compress"
    )
    text = output.strip()
    if not text or text.startswith("<error") or "Get-NetConnectionProfile" in text:
        print("  [----] No se pudo consultar (requiere permisos o el servicio no responde)")
        notes.append("no se pudo comprobar el tipo de red")
        return

    try:
        profiles = json.loads(text)
    except json.JSONDecodeError:
        print(f"  [----] Respuesta inesperada: {text[:120]}")
        return
    if isinstance(profiles, dict):
        profiles = [profiles]

    for profile in profiles:
        category = str(profile.get("NetworkCategory", "?"))
        name = profile.get("Name", "?")
        print(f"  Red: {name}  ->  {category}")
        if category.lower() == "public":
            print("  [AVISO] En redes PUBLICAS el Firewall de Windows bloquea las")
            print("          conexiones entrantes. Hay que cambiarla a Privada o")
            print("          crear una regla para el puerto.")
            failures.append("la red esta clasificada como Publica")
        elif category.lower() == "private":
            print("  [OK   ] Red privada: el Firewall permite lo que hayas autorizado")


def check_firewall_rules() -> None:
    print("\n== 4. Reglas del Firewall para este puerto ==")
    output = powershell(
        f"$ErrorActionPreference='SilentlyContinue';"
        f"Get-NetFirewallPortFilter | Where-Object {{ $_.LocalPort -eq {PORT} }} | "
        f"ForEach-Object {{ $r = $_ | Get-NetFirewallRule; "
        f"'{{0}}|{{1}}|{{2}}' -f $r.DisplayName,$r.Direction,$r.Action }}"
    )
    lines = [line.strip() for line in output.splitlines() if "|" in line]
    if not lines:
        print(f"  [AVISO] No hay ninguna regla especifica para el puerto {PORT}.")
        print("          Windows solo lo permitira si el perfil de red es Privado")
        print("          y autorizaste Python cuando aparecio el aviso.")
        notes.append(f"sin regla de firewall para el puerto {PORT}")
    else:
        allow_in = False
        for line in lines:
            name, direction, action = (line.split("|") + ["", ""])[:3]
            print(f"  {direction:<8} {action:<8} {name}")
            if direction.lower().startswith("in") and action.lower() == "allow":
                allow_in = True
        if allow_in:
            print("  [OK   ] Hay al menos una regla de entrada que permite el puerto")
        else:
            print("  [FALLO] No hay ninguna regla de ENTRADA que permita el puerto")
            failures.append("el firewall no permite la entrada en ese puerto")


def main() -> int:
    print("Diagnostico de conexion del celular")
    print("=" * 62)
    check_listening()
    check_reachable()
    check_network_profile()
    check_firewall_rules()

    print("\n" + "=" * 62)
    if failures:
        print("  Problemas encontrados:")
        for item in failures:
            print("   -", item)
        print()
        print("  La causa mas habitual es el Firewall de Windows. Para abrir el")
        print(f"  puerto {PORT} hace falta una consola COMO ADMINISTRADOR y ejecutar:")
        print()
        print(f'    netsh advfirewall firewall add rule name="RemotePad" '
              f'dir=in action=allow protocol=TCP localport={PORT}')
        print()
        print("  O bien cambiar la red WiFi a Privada:")
        print('    Set-NetConnectionProfile -NetworkCategory Private')
    else:
        print("  Todo correcto: el servidor escucha y la red deberia permitirlo.")
        print("  Si el celular sigue sin conectar, comprueba que este en la MISMA")
        print("  red WiFi (no en datos moviles) y que la red no aísle los equipos.")
    if notes:
        print("\n  Notas:")
        for item in notes:
            print("   -", item)
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
