@echo off
REM ==================================================================
REM  MQTT-Kachel-Dashboard-MK1 - Installation auf GL.iNet Brume 2
REM  OHNE GitHub Actions: Doppelklick auf diese Datei.
REM
REM  Uebertraegt app.py + Installer per SSH auf den Brume und startet
REM  dort die Installation. Nur EINE Passwortabfrage (root-Passwort
REM  des Brume = Admin-Passwort der GL.iNet-Weboberflaeche).
REM  Benoetigt Windows 10/11 (ssh und tar sind dort eingebaut).
REM
REM  Optionen werden durchgereicht, z. B.:
REM    brume-installieren-windows.bat --port=8086
REM    brume-installieren-windows.bat --ohne-firewall
REM ==================================================================
setlocal
cd /d "%~dp0.."

where ssh >nul 2>nul
if errorlevel 1 (
  echo FEHLER: "ssh" wurde nicht gefunden.
  echo Windows-Einstellungen - Apps - Optionale Features - "OpenSSH-Client" hinzufuegen.
  pause
  exit /b 1
)
where tar >nul 2>nul
if errorlevel 1 (
  echo FEHLER: "tar" wurde nicht gefunden ^(Windows 10 ab Version 1803 noetig^).
  pause
  exit /b 1
)
if not exist "app.py" (
  echo FEHLER: app.py nicht gefunden - Datei bitte im Ordner brume2 des Projekts lassen.
  pause
  exit /b 1
)

set "BRUME_IP="
set /p BRUME_IP=IP-Adresse des Brume 2 [192.168.8.1]:
if "%BRUME_IP%"=="" set "BRUME_IP=192.168.8.1"

REM Offline-Python-Pakete mitschicken, falls vorher lokal gebaut (dist\ipk)
set "IPK="
if exist "dist\ipk\pakete.txt" set "IPK=dist/ipk"

echo.
echo Verbinde mit root@%BRUME_IP% ...
echo (Beim ersten Mal "yes" bestaetigen, dann das root-Passwort eingeben.)
echo.

tar -cf - app.py brume2/install.sh brume2/uninstall.sh brume2/LIESMICH-BRUME2.txt %IPK% | ssh -o StrictHostKeyChecking=accept-new root@%BRUME_IP% "rm -rf /tmp/mqtt-kachel-inst && mkdir -p /tmp/mqtt-kachel-inst && tar -xf - -C /tmp/mqtt-kachel-inst && cd /tmp/mqtt-kachel-inst && if [ -d dist/ipk ]; then mv dist/ipk brume2/ipk; fi && sed -i 's/\r$//' brume2/*.sh && sh brume2/install.sh %* ; RC=$? ; rm -rf /tmp/mqtt-kachel-inst ; exit $RC"

if errorlevel 1 (
  echo.
  echo Installation NICHT erfolgreich - Meldungen oben pruefen.
) else (
  echo.
  echo Installation abgeschlossen.
)
echo.
pause
