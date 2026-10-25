#!/bin/sh
# ------------------------------------------------------------------
# MQTT-Kachel-Dashboard-MK1 - Installation auf GL.iNet Brume 2
#
#   scp MQTT-Kachel-Dashboard-MK1-*.zip root@<BRUME-IP>:/tmp/
#   ssh root@<BRUME-IP>
#   cd /tmp && unzip -o MQTT-Kachel-Dashboard-MK1-*.zip
#   sh MQTT-Kachel-Dashboard-MK1/install.sh
#
# Optionen: --port=8086  --ohne-firewall
# Erneut ausfuehren = Update (config.json bleibt erhalten).
# ------------------------------------------------------------------
cd "$(dirname "$0")" || exit 1
# Windows-Zeilenenden entfernen, falls die Zip unter Windows bearbeitet wurde
sed -i 's/\r$//' brume2/*.sh 2>/dev/null
exec sh brume2/install.sh "$@"
