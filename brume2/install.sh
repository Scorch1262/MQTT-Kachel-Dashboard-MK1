#!/bin/sh
# ------------------------------------------------------------------
# MQTT-Kachel-Dashboard-MK1 - Offline-Installation fuer GL.iNet Brume 2
#
# Aufruf (im entpackten Ordner auf dem Brume 2):
#   sh install.sh                 Installieren bzw. aktualisieren
#   sh install.sh --port=8091     beim ERSTEN Installieren anderen Port setzen
#   sh install.sh --ohne-firewall keine Firewall-Regel fuer den WAN-Port anlegen
#
# Erneutes Ausfuehren mit einem neueren Paket = Update (config.json bleibt).
# ------------------------------------------------------------------

APP=MQTT-Kachel-Dashboard-MK1
SERVICE=mqtt-kachel-dashboard
ZIEL=/root/$APP
QUELLE=$(cd "$(dirname "$0")" && pwd)
FIREWALL=1
PORT_ARG=""

say()  { echo "[$APP] $*"; }
fail() { echo "[$APP] FEHLER: $*" >&2; exit 1; }

for a in "$@"; do
  case "$a" in
    --ohne-firewall) FIREWALL=0 ;;
    --port=*) PORT_ARG="${a#--port=}" ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) fail "Unbekannte Option: $a" ;;
  esac
done

[ "$(id -u)" = "0" ] || fail "Bitte als root ausfuehren."
[ -f "$QUELLE/app.py" ] || fail "app.py nicht gefunden - install.sh bitte im entpackten Ordner starten."

# --- System pruefen ------------------------------------------------
if [ -f /etc/openwrt_release ]; then
  . /etc/openwrt_release
  say "System: ${DISTRIB_DESCRIPTION:-OpenWrt} (${DISTRIB_ARCH:-?})"
  if [ -f "$QUELLE/ipk/ziel.txt" ]; then
    PAKET_ARCH=$(sed -n 's/^arch=//p' "$QUELLE/ipk/ziel.txt")
    if [ -n "$PAKET_ARCH" ] && [ -n "$DISTRIB_ARCH" ] && [ "$PAKET_ARCH" != "$DISTRIB_ARCH" ]; then
      say "WARNUNG: Python-Pakete wurden fuer '$PAKET_ARCH' gebaut, dieses Geraet ist '$DISTRIB_ARCH'."
    fi
  fi
else
  say "WARNUNG: Kein OpenWrt erkannt - Installation wird trotzdem versucht."
fi

# --- Python3 (offline) ---------------------------------------------
python_ok() {
  command -v python3 >/dev/null 2>&1 && \
  python3 -c "import ssl, json, socket, struct, http.server, socketserver, urllib.parse, threading" >/dev/null 2>&1
}

if python_ok; then
  say "Python3 ist bereits vorhanden: $(python3 --version 2>&1)"
else
  set -- "$QUELLE"/ipk/*.ipk
  [ -f "$1" ] || fail "Python3 fehlt und das Paket enthaelt keine .ipk-Dateien (mit --ohne-python gebaut?)."
  say "Installiere Python3 offline aus $# Paketen (kann 1-2 Minuten dauern) ..."
  FREI=$(df -k /overlay 2>/dev/null | awk 'NR==2 {print $4}')
  [ -n "$FREI" ] && [ "$FREI" -lt 60000 ] && say "WARNUNG: nur $((FREI/1024)) MB frei auf /overlay."
  opkg install "$@" || say "opkg meldete Warnungen - pruefe Python ..."
  python_ok || fail "Python3 konnte nicht installiert werden (siehe Meldungen oben)."
  say "Python3 installiert: $(python3 --version 2>&1)"
fi
PY=$(command -v python3)

# --- Programm kopieren ---------------------------------------------
mkdir -p "$ZIEL" || fail "Ordner $ZIEL konnte nicht angelegt werden."
if [ -x /etc/init.d/$SERVICE ]; then
  /etc/init.d/$SERVICE stop >/dev/null 2>&1
fi
cp "$QUELLE/app.py" "$ZIEL/app.py" || fail "Kopieren von app.py fehlgeschlagen."
chmod 755 "$ZIEL/app.py"
[ -f "$QUELLE/LIESMICH-BRUME2.txt" ] && cp "$QUELLE/LIESMICH-BRUME2.txt" "$ZIEL/"
[ -f "$QUELLE/uninstall.sh" ] && cp "$QUELLE/uninstall.sh" "$ZIEL/" && chmod 755 "$ZIEL/uninstall.sh"

if [ -f "$ZIEL/config.json" ]; then
  say "Bestehende Konfiguration bleibt erhalten: $ZIEL/config.json"
  [ -n "$PORT_ARG" ] && say "Hinweis: --port wird ignoriert, Port bitte auf der Webseite aendern."
elif [ -n "$PORT_ARG" ]; then
  echo "{\"server\": {\"port\": $PORT_ARG}}" > "$ZIEL/config.json"
fi
PORT=$("$PY" -c "import json,sys; print(int(json.load(open(sys.argv[1]))['server']['port']))" "$ZIEL/config.json" 2>/dev/null)
[ -n "$PORT" ] || PORT=8090

# --- Autostart (procd) ---------------------------------------------
cat > /etc/init.d/$SERVICE <<EOF
#!/bin/sh /etc/rc.common
# Autostart fuer $APP (angelegt von install.sh)
START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command $PY -u $ZIEL/app.py
    procd_set_param respawn 3600 5 0
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
EOF
chmod 755 /etc/init.d/$SERVICE
/etc/init.d/$SERVICE enable

# --- Firewall (Zugriff auch ueber den WAN-Port) ----------------------
if [ "$FIREWALL" = "1" ] && command -v uci >/dev/null 2>&1; then
  uci -q delete firewall.mqtt_kachel_dashboard
  uci set firewall.mqtt_kachel_dashboard=rule
  uci set firewall.mqtt_kachel_dashboard.name='Allow-MQTT-Kachel-Dashboard'
  uci set firewall.mqtt_kachel_dashboard.src='wan'
  uci set firewall.mqtt_kachel_dashboard.proto='tcp'
  uci set firewall.mqtt_kachel_dashboard.dest_port="$PORT"
  uci set firewall.mqtt_kachel_dashboard.target='ACCEPT'
  uci commit firewall
  /etc/init.d/firewall reload >/dev/null 2>&1
  say "Firewall-Regel fuer TCP-Port $PORT (WAN) angelegt."
fi

# --- Starten ---------------------------------------------------------
/etc/init.d/$SERVICE start
sleep 4
OK=0
if command -v wget >/dev/null 2>&1; then
  wget -q -O /dev/null "http://127.0.0.1:$PORT/api/state" && OK=1
elif command -v curl >/dev/null 2>&1; then
  curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/state" && OK=1
fi
if [ "$OK" = "1" ]; then
  say "Dashboard laeuft."
else
  say "Dashboard antwortet noch nicht - Log ansehen mit: logread -e app.py"
fi

echo ""
say "Fertig! Erreichbar unter:"
IPS=$(ip -4 -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -v '^127\.')
[ -n "$IPS" ] || IPS=$(uci -q get network.lan.ipaddr 2>/dev/null)
[ -n "$IPS" ] || IPS="<IP-des-Brume>"
for ip in $IPS; do
  echo "      http://$ip:$PORT"
done
echo ""
say "Programmordner:  $ZIEL"
say "Steuerung:       /etc/init.d/$SERVICE start|stop|restart"
say "Deinstallation:  sh $ZIEL/uninstall.sh"
