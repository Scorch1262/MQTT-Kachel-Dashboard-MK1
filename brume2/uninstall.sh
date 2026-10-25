#!/bin/sh
# ------------------------------------------------------------------
# MQTT-Kachel-Dashboard-MK1 - Deinstallation auf dem GL.iNet Brume 2
#
#   sh uninstall.sh          Dienst + Firewall-Regel entfernen,
#                            Programmordner inkl. config.json bleibt
#   sh uninstall.sh --alles  zusaetzlich Programmordner inkl. config.json loeschen
#
# Python3 bleibt installiert (wird evtl. von anderen Programmen genutzt).
# ------------------------------------------------------------------
APP=MQTT-Kachel-Dashboard-MK1
SERVICE=mqtt-kachel-dashboard
ZIEL=/root/$APP

if [ -x /etc/init.d/$SERVICE ]; then
  /etc/init.d/$SERVICE stop >/dev/null 2>&1
  /etc/init.d/$SERVICE disable >/dev/null 2>&1
  rm -f /etc/init.d/$SERVICE
  echo "[$APP] Dienst entfernt."
fi
if command -v uci >/dev/null 2>&1 && uci -q get firewall.mqtt_kachel_dashboard >/dev/null; then
  uci delete firewall.mqtt_kachel_dashboard
  uci commit firewall
  /etc/init.d/firewall reload >/dev/null 2>&1
  echo "[$APP] Firewall-Regel entfernt."
fi
if [ "$1" = "--alles" ]; then
  rm -rf "$ZIEL"
  echo "[$APP] Programmordner $ZIEL geloescht."
else
  echo "[$APP] Programmordner $ZIEL (mit config.json) bleibt erhalten."
fi
