#!/bin/bash
# ==================================================================
#  MQTT-Kachel-Dashboard-MK1 - Installation auf GL.iNet Brume 2
#  OHNE GitHub Actions: Doppelklick im Finder (oder im Terminal starten).
#  Funktioniert auch unter Linux.
#
#  Überträgt app.py + Installer per SSH auf den Brume und startet dort
#  die Installation. Nur EINE Passwortabfrage (root-Passwort des Brume =
#  Admin-Passwort der GL.iNet-Weboberfläche).
#
#  Optionen werden durchgereicht, z. B.:
#    ./brume-installieren-mac.command --port=8086
#    ./brume-installieren-mac.command --ohne-firewall
# ==================================================================
cd "$(dirname "$0")/.." || exit 1

if [ ! -f app.py ]; then
  echo "FEHLER: app.py nicht gefunden - Datei bitte im Ordner brume2 des Projekts lassen."
  read -r -p "Enter zum Schließen ..." _; exit 1
fi

read -r -p "IP-Adresse des Brume 2 [192.168.8.1]: " BRUME_IP
BRUME_IP=${BRUME_IP:-192.168.8.1}

# Offline-Python-Pakete mitschicken, falls vorher lokal gebaut (dist/ipk)
DATEIEN=(app.py brume2/install.sh brume2/uninstall.sh brume2/LIESMICH-BRUME2.txt)
[ -f dist/ipk/pakete.txt ] && DATEIEN+=(dist/ipk)

ARGS=""
for a in "$@"; do ARGS="$ARGS '$a'"; done

echo
echo "Verbinde mit root@$BRUME_IP ..."
echo "(Beim ersten Mal 'yes' bestätigen, dann das root-Passwort eingeben.)"
echo

# COPYFILE_DISABLE verhindert macOS-Zusatzdateien (._*) im Archiv
COPYFILE_DISABLE=1 tar -cf - "${DATEIEN[@]}" | ssh -o StrictHostKeyChecking=accept-new "root@$BRUME_IP" \
  "rm -rf /tmp/mqtt-kachel-inst && mkdir -p /tmp/mqtt-kachel-inst && tar -xf - -C /tmp/mqtt-kachel-inst && cd /tmp/mqtt-kachel-inst && if [ -d dist/ipk ]; then mv dist/ipk brume2/ipk; fi && sed -i 's/\r\$//' brume2/*.sh && sh brume2/install.sh $ARGS ; RC=\$? ; rm -rf /tmp/mqtt-kachel-inst ; exit \$RC"
RC=$?

echo
if [ $RC -eq 0 ]; then echo "Installation abgeschlossen."; else echo "Installation NICHT erfolgreich - Meldungen oben prüfen."; fi
read -r -p "Enter zum Schließen ..." _
