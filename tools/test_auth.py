"""
Pruebas del modulo de acceso (server/auth.py) y del guardado de estado.

  A) Los tokens no se guardan en claro: solo su huella SHA-256.
  B) Un tokens.json del formato antiguo se convierte sin perder accesos.
  C) Los accesos caducados se podan; revocar exige un codigo unico.
  D) La escritura es atomica: un fallo no deja el archivo a medias.
  E) Los fallos de PIN se olvidan pasado el tiempo (no crecen sin limite).
  F) Las preferencias se validan y se migran a la huella.
  G) Nombre del dispositivo a partir del User-Agent.

No hace falta servidor.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="remotepad_auth_"))
os.environ["REMOTEPAD_TOKENS"] = str(_TMP / "tokens.json")
os.environ["REMOTEPAD_PROFILES"] = str(_TMP / "profiles.json")
os.environ["REMOTEPAD_CONFIG"] = str(_TMP / "config.json")
os.environ["REMOTEPAD_LEARNING"] = str(_TMP / "learning.json")
sys.path.insert(0, str(RAIZ / "server"))

import auth  # noqa: E402
import app as servidor  # noqa: E402

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def prueba_huellas() -> None:
    print("\n== A) Tokens guardados solo como huella ==")
    archivo = _TMP / "a.json"
    registro = auth.Dispositivos(archivo)
    token, huella = registro.emitir("Pixel 7 (Android 14)", "192.168.1.40")
    contenido = archivo.read_text(encoding="utf-8")
    check("El token NO aparece en el archivo", token not in contenido)
    check("La huella si aparece", huella in contenido)
    check("La huella es el SHA-256 del token", huella == auth.token_hash(token))
    check("El token valida", auth.Dispositivos(archivo).validar(token) == huella)
    check("Un token inventado no valida", registro.validar("inventado") is None)
    check("Un token no textual no valida", registro.validar(12345) is None)
    check("Un token enorme no valida", registro.validar("x" * 5000) is None)
    filas = registro.listar()
    check("La lista no expone la huella entera como id",
          filas and len(filas[0]["id"]) == 8)
    check("La lista guarda nombre y direccion",
          filas and filas[0]["nombre"].startswith("Pixel 7")
          and filas[0]["addr"] == "192.168.1.40")


def prueba_migracion() -> None:
    print("\n== B) Migracion del formato antiguo ==")
    archivo = _TMP / "b.json"
    viejo = {"token-viejo-1": time.time() - 100, "token-viejo-2": time.time() - 50}
    archivo.write_text(json.dumps(viejo), encoding="utf-8")
    registro = auth.Dispositivos(archivo)
    check("Se conservan los dos accesos", len(registro) == 2)
    check("El token antiguo sigue entrando",
          registro.validar("token-viejo-1") == auth.token_hash("token-viejo-1"))
    contenido = archivo.read_text(encoding="utf-8")
    check("El archivo se reescribe sin tokens en claro",
          "token-viejo-1" not in contenido and '"version": 2' in contenido)

    roto = _TMP / "b_roto.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    check("Un archivo roto no impide arrancar", len(auth.Dispositivos(roto)) == 0)


def prueba_poda_y_revocar() -> None:
    print("\n== C) Caducidad y revocacion ==")
    archivo = _TMP / "c.json"
    registro = auth.Dispositivos(archivo)
    t1, h1 = registro.emitir("Uno", "1.1.1.1")
    t2, h2 = registro.emitir("Dos", "2.2.2.2")
    registro._datos[h1]["creado"] = time.time() - auth.TOKEN_TTL_SECONDS - 10
    check("El caducado ya no valida", registro.validar(t1) is None)
    check("Y desaparece de la lista", all(f["huella"] != h1 for f in registro.listar()))
    check("Un codigo demasiado corto no revoca nada", registro.revocar(h2[:3]) == [])
    check("Un codigo inexistente no revoca nada", registro.revocar("ffffffffff") == [] or h2.startswith("ffffffffff"))
    check("El codigo de 8 caracteres revoca", registro.revocar(h2[:8]) == [h2])
    check("El revocado ya no entra", auth.Dispositivos(archivo).validar(t2) is None)


def prueba_atomica() -> None:
    print("\n== D) Escritura atomica ==")
    archivo = _TMP / "d.json"
    check("Se escribe", auth.write_json_atomic(archivo, {"a": 1}))
    check("Se lee igual", auth.read_json(archivo) == {"a": 1})

    class NoSerializable:
        pass

    check("Un dato que no se puede guardar devuelve False",
          auth.write_json_atomic(archivo, {"b": NoSerializable()}) is False)
    check("Y el archivo anterior queda intacto", auth.read_json(archivo) == {"a": 1})
    check("No quedan temporales", not list(_TMP.glob(".d.json.*")))


def prueba_fallos() -> None:
    print("\n== E) Fallos de PIN ==")
    control = auth.ControlAcceso(dispositivos=auth.Dispositivos(_TMP / "e.json"))
    malo = "000000" if control.pin != "000000" else "111111"
    for _ in range(auth.MAX_PIN_FAILURES):
        control.check_pin(malo, "10.0.0.9")
    check("Tras los fallos, el PIN correcto no entra",
          control.check_pin(control.pin, "10.0.0.9") is False)
    check("Otra direccion si puede", control.check_pin(control.pin, "10.0.0.10"))
    # Se envejecen los fallos: pasado el tiempo se olvidan del todo.
    control._pin_failures["10.0.0.9"] = [time.time() - auth.FAILURE_WINDOW_SECONDS - 1]
    for i in range(50):
        control._pin_failures[f"10.1.0.{i}"] = [time.time() - 10_000]
    control.prune_failures()
    check("prune_failures vacia las direcciones antiguas",
          not control._pin_failures, f"quedan {len(control._pin_failures)}")
    check("Y la direccion vuelve a poder entrar", control.check_pin(control.pin, "10.0.0.9"))


def prueba_perfiles() -> None:
    print("\n== F) Preferencias ==")
    limpio = servidor.clean_settings({"sensitivity": 1.6, "nested": {"x": 1},
                                      "nan": float("nan"), "ok": "texto"})
    check("Se quedan los valores simples",
          limpio == {"sensitivity": 1.6, "ok": "texto"}, str(limpio))
    check("Demasiadas claves se rechaza",
          servidor.clean_settings({f"k{i}": 1 for i in range(500)}) is None)
    check("Un texto enorme se descarta",
          "t" not in (servidor.clean_settings({"t": "x" * 100_000}) or {}))
    check("Algo que no es un objeto se rechaza", servidor.clean_settings([1, 2]) is None)

    servidor.PROFILES_FILE.write_text(
        json.dumps({"token-en-claro": {"sensitivity": 2}}), encoding="utf-8")
    perfiles = servidor.load_profiles()
    check("El perfil antiguo pasa a la huella",
          perfiles == {auth.token_hash("token-en-claro"): {"sensitivity": 2}})
    check("Y el archivo ya no contiene el token",
          "token-en-claro" not in servidor.PROFILES_FILE.read_text(encoding="utf-8"))


def prueba_nombres() -> None:
    print("\n== G) Nombre del dispositivo ==")
    pixel = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")
    recortado = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/125.0 Mobile Safari/537.36")
    check("Modelo y version de Android",
          auth.device_name(pixel) == "Pixel 7 (Android 14)", auth.device_name(pixel))
    check("Si Chrome recorta el modelo, solo Android",
          auth.device_name(recortado) == "Android 10", auth.device_name(recortado))
    check("iPhone", auth.device_name("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)") == "iPhone")
    check("Sin User-Agent", auth.device_name("") == "Dispositivo")


def main() -> int:
    print("Modulo de acceso")
    print("=" * 62)
    prueba_huellas()
    prueba_migracion()
    prueba_poda_y_revocar()
    prueba_atomica()
    prueba_fallos()
    prueba_perfiles()
    prueba_nombres()
    print("\n" + "=" * 62)
    if failures:
        print(f"  {failures} de {checks} comprobaciones fallidas")
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
