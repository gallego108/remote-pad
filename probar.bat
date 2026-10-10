@echo off
REM ===================================================================
REM  RemotePad - Verificacion completa
REM  Arranca un servidor temporal, ejecuta todas las pruebas y lo para.
REM
REM  La lista de pruebas vive en tools\run_tests.py (la misma que usa la
REM  integracion continua). Las pruebas usan archivos de estado temporales:
REM  no tocan server\tokens.json, profiles.json, learning.json ni config.json.
REM
REM  Sin mover el puntero de verdad:   probar.bat --ci
REM  Solo algunas pruebas:             probar.bat test_qr test_auth
REM ===================================================================
setlocal
cd /d "%~dp0"

python tools\run_tests.py %*
exit /b %errorlevel%
