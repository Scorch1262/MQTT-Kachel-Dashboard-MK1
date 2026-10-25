#!/bin/sh
# ------------------------------------------------------------------
# MQTT-Kachel-Dashboard-MK1 - Offline-Installation fuer GL.iNet Brume 2
#
# Normalerweise ueber die install.sh im Hauptordner der Zip gestartet.
# Direkter Aufruf auf dem Brume 2 (im entpackten Ordner):
#   sh install.sh                 Installieren bzw. aktualisieren
#   sh install.sh --port=8086     beim ERSTEN Installieren anderen Port setzen
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
# app.py liegt im Offline-Paket neben install.sh, im Projektordner eine Ebene hoeher
APP_SRC=""
for d in "$QUELLE" "$QUELLE/.."; do
  [ -f "$d/app.py" ] && APP_SRC="$d/app.py" && break
done
[ -n "$APP_SRC" ] || fail "app.py nicht gefunden - install.sh bitte im entpackten Ordner starten."

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

# --- Python3 (online per opkg oder offline aus ipk/) ----------------
# alle Module, die app.py beim Start braucht
PY_MODULE="import base64, json, os, random, shutil, socket, ssl, string, struct, subprocess, sys, threading, time, http.server, socketserver, urllib.parse"
python_ok() {
  command -v python3 >/dev/null 2>&1 && \
  python3 -c "$PY_MODULE" >/dev/null 2>&1
}

if python_ok; then
  say "Python3 ist bereits vorhanden: $(python3 --version 2>&1)"
else
  FREI=$(df -k /overlay 2>/dev/null | awk 'NR==2 {print $4}')
  [ -n "$FREI" ] && [ "$FREI" -lt 60000 ] && say "WARNUNG: nur $((FREI/1024)) MB frei auf /overlay."
  set -- "$QUELLE"/ipk/*.ipk
  if [ -f "$1" ]; then
    say "Installiere Python3 offline aus $# Paketen (kann 1-2 Minuten dauern) ..."
    opkg install "$@" || say "opkg meldete Warnungen - pruefe Python ..."
  else
    say "Python3 fehlt - installiere es aus dem Internet (opkg) ..."
    if opkg update; then
      opkg install python3 || say "opkg meldete Warnungen - pruefe Python ..."
    else
      fail "Python3 fehlt und der Brume erreicht die Paketquellen nicht (kein Internet?).
       Loesung: Brume kurz mit dem Internet verbinden oder am PC das Offline-Paket
       bauen (brume2/offline-paket-bauen-*) - siehe README Abschnitt 4."
    fi
  fi
  python_ok || fail "Python3 konnte nicht installiert werden (siehe Meldungen oben)."
  say "Python3 installiert: $(python3 --version 2>&1)"
fi
PY=$(command -v python3)

# --- Programm kopieren ---------------------------------------------
mkdir -p "$ZIEL" || fail "Ordner $ZIEL konnte nicht angelegt werden."
if [ -x /etc/init.d/$SERVICE ]; then
  /etc/init.d/$SERVICE stop >/dev/null 2>&1
fi
cp "$APP_SRC" "$ZIEL/app.py" || fail "Kopieren von app.py fehlgeschlagen."
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
[ -n "$PORT" ] || PORT=8085

# --- Port pruefen (eigener Dienst ist oben bereits gestoppt) ----------
port_belegt() {
  netstat -ltn 2>/dev/null | awk '{print $4}' | grep -q "[:.]$1\$"
}
if port_belegt "$PORT"; then
  WER=$(netstat -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$" {print $7}' | head -n 1)
  ALT=$PORT
  while port_belegt "$PORT"; do PORT=$((PORT + 1)); done
  say "Port $ALT ist auf dem Brume bereits belegt${WER:+ (von $WER)} - verwende Port $PORT."
  "$PY" - "$ZIEL/config.json" "$PORT" <<'PYEOF'
import json, os, sys
pfad, port = sys.argv[1], int(sys.argv[2])
cfg = {}
if os.path.exists(pfad):
    with open(pfad, encoding="utf-8") as f:
        cfg = json.load(f)
cfg.setdefault("server", {})["port"] = port
with open(pfad, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PYEOF
fi

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
say "Warte auf das Dashboard ..."
OK=0
i=0
while [ $i -lt 20 ]; do
  sleep 1
  i=$((i + 1))
  if command -v wget >/dev/null 2>&1; then
    wget -q -O /dev/null "http://127.0.0.1:$PORT/api/state" 2>/dev/null && OK=1
  elif command -v curl >/dev/null 2>&1; then
    curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/state" && OK=1
  fi
  [ "$OK" = "1" ] && break
done
if [ "$OK" = "1" ]; then
  say "Dashboard laeuft (Port $PORT)."
else
  say "FEHLER: Dashboard antwortet nicht auf Port $PORT."
  say "Letzte Log-Meldungen:"
  logread 2>/dev/null | grep -E "python|Server\]|MQTT\]|Config\]|Traceback|Error" | tail -n 20
  say "Direkter Test (Strg+C beendet):"
  say "  /etc/init.d/$SERVICE stop; $PY $ZIEL/app.py"
fi

echo ""
say "Fertig! Erreichbar unter:"
IPS=$(ip -4 addr show 2>/dev/null | awk '/inet / {split($2, a, "/"); print a[1]}' | grep -v '^127\.')
[ -n "$IPS" ] || IPS=$(uci -q get network.lan.ipaddr 2>/dev/null)
[ -n "$IPS" ] || IPS="<IP-des-Brume>"
for ip in $IPS; do
  echo "      http://$ip:$PORT"
done
echo ""
say "Programmordner:  $ZIEL"
say "Steuerung:       /etc/init.d/$SERVICE start|stop|restart"
say "Deinstallation:  sh $ZIEL/uninstall.sh"
