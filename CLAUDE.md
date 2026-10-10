# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RemotePad turns an Android phone into a wireless touchpad (plus keyboard, gamepad, custom shortcuts…) for a **Windows** PC. A Python server (`server/`, aiohttp) serves a framework-free PWA (`web/`) to the phone over the LAN; the phone sends actions over a WebSocket as JSON and the server injects input via the Win32 API. Windows-only. The only runtime dependency is `aiohttp` (`tkinter` for the laser pointer ships with Python); `cryptography` is needed only for `--https`. No build step.

The project's language is Spanish: docs, UI text, commit messages, CHANGELOG. In-depth docs live in `docs/` (`arquitectura.md`, `protocolo.md` for the full WebSocket/HTTP reference, `desarrollo.md`, `seguridad.md`).

## Commands

```bash
# Run the server (from server/)
python app.py --no-browser                  # default port 8765
python app.py --port 8792 --no-browser      # another port, to avoid clashing with a running instance
# Other flags: --host 127.0.0.1, --no-auth (no PIN/QR), --no-qr, --https, --confirmar

# All tests: starts its own server on 8791 with temp state files, runs everything, stops it
python tools/run_tests.py                   # full (test_client/test_drag move the real mouse)
python tools/run_tests.py --ci              # skips desktop-moving tests (what GitHub Actions runs)
python tools/run_tests.py test_auth         # only tests whose filename contains the text
probar.bat                                  # double-click wrapper around run_tests.py
```

Tests are standalone scripts in `tools/` (no pytest); each prints `[OK]`/`[FALLO]` and exits non-zero on failure. The test list lives **only** in `tools/run_tests.py` — register new tests there (`servidor=True` gets `{puerto}`/`{pin}` of the shared server; `escritorio=True` is skipped in `--ci`; `cursor=True` appends `--cursor` except in `--ci`). Tests that start their own server use their own ports (879x).

**State-file isolation:** server state (`server/tokens.json`, `profiles.json`, `learning.json`, `history.json`, `config.json`, `https/`) is local and gitignored. `run_tests.py` redirects all of it to a temp dir via `REMOTEPAD_TOKENS`, `REMOTEPAD_PROFILES`, `REMOTEPAD_LEARNING`, `REMOTEPAD_HISTORY`, `REMOTEPAD_CONFIG`, `REMOTEPAD_HTTPS_DIR`, and sets `REMOTEPAD_SIN_VENTANAS=1` (new-device confirmation is answered via console stdin instead of a Windows dialog). Set these yourself if you run a server-starting test or the server by hand for experiments.

## Architecture

```
web/app.js ──WebSocket JSON──► server/app.py (Gateway) ──► controller.py (DesktopController) ──► native_input.py (SendInput)
                                       │
                                       └──► auth.py (ControlAcceso, Dispositivos)
```

- **`server/app.py`** — HTTP + WebSocket, `Gateway`, device management, console commands. `Gateway.handle_action()` dispatches each client action (write branches as `if action == "name":` — `check_ui.py` greps for that form). `Gateway.animation_loop()` is the performance core: pointer moves are **accumulated and applied once per tick** (~60–125 Hz); anything whose **order** matters (clicks, `mouse_down/up`, `key_down/up`) goes through `_queue_click`, executed one at a time by the loop; other blocking OS calls go to a 3-thread `ThreadPoolExecutor` (no ordering guarantee).
- **`server/auth.py`** — PIN rotation, one-time QR keys with grace window, failure lockouts, and `Dispositivos` (authorized devices stored **only as SHA-256 hashes** of their tokens, with name/addr/last-seen; old plaintext formats auto-migrate). Also `write_json_atomic`/`read_json`/`load_config`/`save_config` used for all state files. No network/Win32 code: testable without a server. `Gateway` uses it as `gateway.acceso`.
- **`server/controller.py`** — tracks a "virtual" pointer position and drag state (`_drag_button`) itself, because `GetAsyncKeyState` doesn't reflect buttons injected with `SendInput`. Clamps the pointer to the union of **all monitors** (cached list, refreshed every 3 s). Tracks held keys for gamepad mode; `release_all()` (called on client disconnect) releases buttons, held keys and modifiers. `run_macro()` executes validated custom-shortcut steps.
- **`server/native_input.py`** — the **only** Win32 boundary (ctypes). `argtypes`/`restype` prototypes are mandatory (64-bit pointers get truncated otherwise). `pynput` is deliberately not used (broken with Python 3.12 on Windows). `clamp_to_rects()` is pure so monitor layouts can be tested with fake rects.
- **`server/certificado.py`** — local CA + server cert for `--https` (re-signs the leaf with the same CA when the LAN IP changes).
- **`server/qr.py`** — dependency-free QR encoder. Bit placement is fragile; always verify with `test_qr.py` rather than by eye.
- **`server/learning.py`** — adaptive pointer gain per foreground application. Client-side learning lives in `app.js`.
- **`server/historial.py`** — history of programs used on the PC (recorded on foreground change in `Gateway.historial_tick`), relaunchable from the phone. The phone only sends an id; the server maps it to the path/AUMID. **`server/iconos.py`** — pure icon → PNG conversion and cache (Win32 drawing stays in `native_input.window_icon`).
- **`server/laser.py`** — separate process drawing a transparent click-through `tkinter` overlay.
- **`web/app.js`** — single `'use strict'` file, no modules/frameworks. Gesture state in `gesture`, app state in `state`. User settings (including custom shortcuts `atajos` and gamepad keys `mando`, stored as JSON strings) live in `settings`, are synced to the PC via `save_settings` and come back in the auth `ok` message. Render server-provided strings (device names come from User-Agents) with `textContent`, never `innerHTML`.
- **`web/qr.html`** — PC-side QR panel at `/qr`, served only to localhost.

### Security invariants (covered by `tools/test_seguridad.py`)

- Never send the PIN to an unauthenticated client (`auth_query` answers only `required`; `viewer` mode is loopback-only).
- The WebSocket rejects a foreign `Origin`.
- Never log the current PIN on failed attempts; never persist raw tokens.

### Adding a new action

1. Branch in `Gateway.handle_action()`; executor if it touches the OS, `_queue_click` if ordering matters.
2. Method on `DesktopController` using `native_input`.
3. Client: `send('action_name', {...})` in `app.js`.
4. Test in `tools/test_client.py` or a new test registered in `tools/run_tests.py`.

### Threading gotcha

Values passed to executor threads must be bound at dispatch time — the message loop reassigns variables. Pass copies (`list(mods)`) and bind lambdas with default args: `lambda x=x, y=y: c.mouse_move_to(x, y)`.

### Versioning / cache busting

When changing anything under `web/`, bump together (enforced by `test_version_cache.py`):
- `APP_VERSION` in `server/app.py`
- `REMOTEPAD_WEB` constant and the `?v=` query strings in `web/index.html`
- `CACHE` name in `web/sw.js` (keep its file list in sync — `check_ui.py` checks it)

The server injects `<meta name="remotepad-version">`; a mismatch makes the page force-reload to avoid phones running stale JS. Releases add an entry to `CHANGELOG.md`.

## Code style

- Python comments and log/console messages in Spanish **without accents** (old-console encoding safety); docs and UI text in Spanish **with** accents.
- Identifiers mostly in English (newer modules mix in Spanish names, e.g. `auth.py`, `learning.py`); follow the surrounding file. Prefer `pathlib` and `dataclasses`.
