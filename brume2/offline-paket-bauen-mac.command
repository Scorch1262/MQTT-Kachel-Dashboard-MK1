#!/bin/bash
# Baut das Brume-2-Offline-Paket lokal (Mac braucht Internet + Python 3).
# Doppelklick im Finder oder im Terminal: ./offline-paket-bauen-mac.command
# Ergebnis: dist/MQTT-Kachel-Dashboard-vX.Y.Z-brume2-offline.tar.gz
cd "$(dirname "$0")/.." || exit 1
python3 brume2/build_offline_paket.py "$@"
echo
read -r -p "Fertig - Enter zum Schliessen ..." _
