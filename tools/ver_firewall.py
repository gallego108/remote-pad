"""Muestra las reglas del Firewall de Windows relacionadas con Python y TCP."""

from __future__ import annotations

import re
import subprocess

FIELDS = {
    "name": r"(?:Nombre de regla|Rule Name)",
    "enabled": r"(?:Habilitada|Enabled)",
    "direction": r"(?:Direcci\u00f3n|Direccion|Direction)",
    "profiles": r"(?:Perfiles|Profiles)",
    "action": r"(?:Acci\u00f3n|Accion|Action)",
    "program": r"(?:Programa|Program)",
    "protocol": r"(?:Protocolo|Protocol)",
    "local_port": r"(?:Puerto local|LocalPort)",
}

output = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule",
                         "name=all", "dir=in"],
                        capture_output=True, text=True, timeout=60).stdout
blocks = re.split(r"(?m)^-{5,}\s*$", output)

interesting = []
for block in blocks:
    if "python" not in block.lower():
        continue
    rule = {}
    for key, pattern in FIELDS.items():
        match = re.search(rf"(?mi)^\s*{pattern}\s*:\s*(.+?)\s*$", block)
        rule[key] = match.group(1) if match else "?"
    interesting.append(rule)

print(f"Reglas de entrada que mencionan Python: {len(interesting)}\n")
tcp_rules = []
for rule in interesting:
    protocol = rule["protocol"]
    mark = "TCP" if protocol.upper().startswith("TCP") else protocol
    print(f"  [{'habilitada' if rule['enabled'].lower().startswith(('s', 'y')) else 'DESHABILITADA'}]"
          f" {mark:<6} puerto={rule['local_port']:<12} perfiles={rule['profiles']}")
    if protocol.upper().startswith("TCP"):
        tcp_rules.append(rule)

print()
if tcp_rules:
    print("Hay reglas TCP para Python. Detalle:")
    for rule in tcp_rules:
        print(f"  - {rule['name']}")
        print(f"      perfiles: {rule['profiles']}   accion: {rule['action']}")
        print(f"      programa: {rule['program']}")
else:
    print("NO HAY NINGUNA REGLA TCP DE ENTRADA PARA PYTHON.")
    print("Ese es el motivo de que el celular no pueda conectarse: Windows deja")
    print("entrar solo UDP, y el servidor usa TCP.")

print()
print("Reglas de entrada para el puerto 8765:")
found = False
for line in output.splitlines():
    if ":8765" in line:
        print("  ", line.strip())
        found = True
if not found:
    print("   ninguna")
