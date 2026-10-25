@echo off
REM Baut das Brume-2-Offline-Paket lokal (PC braucht Internet + Python 3).
REM Ergebnis: dist\MQTT-Kachel-Dashboard-vX.Y.Z-brume2-offline.tar.gz
cd /d "%~dp0.."
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 brume2\build_offline_paket.py %*
) else (
  python brume2\build_offline_paket.py %*
)
echo.
pause
