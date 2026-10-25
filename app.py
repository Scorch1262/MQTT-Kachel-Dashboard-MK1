#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT-Kachel-Dashboard-MK1
=========================

Lokales Web-Dashboard, das Werte aus MQTT-Topics als Kacheln anzeigt
(Design angelehnt an das Drucker Dashboard MK6).

- Nur Python-Standardbibliothek (kein Flask/paho noetig) -> laeuft als
  PyInstaller-exe/Mac-App UND direkt mit python3 auf einem GL.iNet Brume 2.
- Eigene, schlanke MQTT-3.1.1-Client-Implementierung (TCP/TLS, Login).
- Alle Einstellungen in einer menschenlesbaren "config.json" neben der
  exe/App bzw. neben app.py.
- Port der Webseite ueber die Webseite dauerhaft aenderbar (Server zieht
  ohne Neustart des Programms auf den neuen Port um).
"""

import json
import os
import random
import shutil
import socket
import ssl
import string
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

APP_NAME = "MQTT-Kachel-Dashboard-MK1"
APP_VERSION = "1.1.0"
DEFAULT_PORT = 8085
CONFIG_FILENAME = "config.json"

MAX_TOPICS = 5000            # max. gemerkte Topics (Kachel-Topics immer)
MAX_PAYLOAD_STORE = 65536    # groessere Payloads werden nur als Groesse gemerkt


# ----------------------------------------------------------------------
# Pfade: config.json liegt neben der exe / neben der Mac-App / neben app.py
# ----------------------------------------------------------------------
def program_dir():
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        marker = ".app" + os.sep + "Contents" + os.sep + "MacOS"
        if sys.platform == "darwin" and marker in exe:
            # .../Name.app/Contents/MacOS/Name -> Ordner, in dem Name.app liegt
            app_bundle = exe[: exe.index(marker) + 4]
            return os.path.dirname(app_bundle)
        return os.path.dirname(exe)
    return os.path.dirname(os.path.abspath(__file__))


def _dir_writable(path):
    try:
        test = os.path.join(path, ".schreibtest.tmp")
        with open(test, "w") as f:
            f.write("x")
        os.remove(test)
        return True
    except Exception:
        return False


def config_dir():
    d = program_dir()
    if _dir_writable(d):
        return d
    # Fallback (z. B. macOS "App Translocation" = schreibgeschuetzter
    # Zufallsordner, wenn die App direkt aus dem Downloads-Ordner gestartet
    # wurde): Konfiguration im Benutzerordner ablegen.
    fb = os.path.join(os.path.expanduser("~"), APP_NAME)
    os.makedirs(fb, exist_ok=True)
    return fb


CONFIG_PATH = os.path.join(config_dir(), CONFIG_FILENAME)


# ----------------------------------------------------------------------
# Symbole (eigene, einfache Linien-Icons, 24x24, stroke=currentColor)
# ----------------------------------------------------------------------
ICONS = [
    ("waschmaschine", "Waschmaschine",
     '<rect x="3" y="2" width="18" height="20" rx="2"/><path d="M3 7h18"/><circle cx="12" cy="14.5" r="4.5"/>'
     '<path d="M9.2 15c.9-.8 1.9.8 2.8 0s1.9-.8 2.8 0"/><path d="M6.5 4.5h.01M9 4.5h.01"/>'),
    ("trockner", "Trockner",
     '<rect x="3" y="2" width="18" height="20" rx="2"/><path d="M3 7h18"/><circle cx="12" cy="14.5" r="4.5"/>'
     '<path d="M10.5 12.5c.8.9.8 3 0 4M13.5 12.5c.8.9.8 3 0 4"/><path d="M6.5 4.5h.01M16 4.5h2"/>'),
    ("spuelmaschine", "Spülmaschine",
     '<rect x="3" y="2" width="18" height="20" rx="2"/><path d="M3 7h18M9 4.5h6"/>'
     '<path d="M8 11v7M12 10v8M16 11v7"/>'),
    ("kuehlschrank", "Kühlschrank",
     '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M5 10h14M8.5 5v2.5M8.5 13v3"/>'),
    ("backofen", "Backofen / Herd",
     '<rect x="2.5" y="4" width="19" height="16" rx="2"/><rect x="5.5" y="9" width="13" height="8" rx="1"/>'
     '<path d="M6 6.5h.01M9 6.5h.01M12 6.5h.01"/>'),
    ("server", "Server",
     '<rect x="3" y="3" width="18" height="7" rx="1.5"/><rect x="3" y="14" width="18" height="7" rx="1.5"/>'
     '<path d="M7 6.5h.01M7 17.5h.01M11 6.5h6M11 17.5h6"/>'),
    ("computer", "Computer",
     '<rect x="2" y="4" width="20" height="13" rx="1.5"/><path d="M8 21h8M12 17v4"/>'),
    ("router", "Router / Netzwerk",
     '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 13 5.5 7M17 13l1.5-6M7 16.5h.01M10 16.5h.01M14 16.5h3"/>'),
    ("wlan", "WLAN / Funk",
     '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><path d="M12 19.5h.01"/>'),
    ("solar", "Solaranlage",
     '<path d="M4 4h16l2 10H2z"/><path d="M3 9h18M9.3 4l-.6 10M14.7 4l.6 10M12 14v6M8 20h8"/>'),
    ("sonne", "Sonne",
     '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
     'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    ("lampe", "Lampe",
     '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z"/>'),
    ("steckdose", "Steckdose",
     '<circle cx="12" cy="12" r="9"/><path d="M8.5 12h.01M15.5 12h.01M12 4.5v2M12 17.5v2"/>'),
    ("strom", "Strom / Leistung",
     '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>'),
    ("batterie", "Batterie / Speicher",
     '<rect x="2" y="7" width="18" height="10" rx="2"/><path d="M22 11v2M6 10v4M10 10v4"/>'),
    ("zaehler", "Zähler / Messgerät",
     '<path d="M3.5 17a9 9 0 1 1 17 0"/><path d="M12 14l4-5"/><circle cx="12" cy="14.5" r="1.5"/>'),
    ("auto", "Auto / Wallbox",
     '<path d="M3 13l2-5a2 2 0 0 1 1.9-1.3h10.2A2 2 0 0 1 19 8l2 5v4H3z"/><path d="M3 13h18"/>'
     '<circle cx="7.5" cy="17" r="1.8"/><circle cx="16.5" cy="17" r="1.8"/>'),
    ("ebike", "E-Fahrrad",
     '<circle cx="5" cy="17.5" r="3.5"/><circle cx="19" cy="17.5" r="3.5"/>'
     '<path d="M5 17.5 8 12h7l4 5.5M8 12l3.5 5.5L15 12M6.5 10h3M8 12l-.5-2M15 12l-1-3h2"/><path d="M13 1.5 10.5 5H13l-2 3.5"/>'),
    ("thermometer", "Temperatur",
     '<path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"/><path d="M12 9v6"/>'),
    ("tropfen", "Feuchte / Wasser",
     '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>'),
    ("heizung", "Heizung",
     '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7.5 5v14M12 5v14M16.5 5v14M5 21h2M17 21h2"/>'),
    ("waermepumpe", "Wärmepumpe / Lüfter",
     '<rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="12" cy="12" r="5"/><path d="M12 7v10M7 12h10"/>'),
    ("flamme", "Gas / Flamme",
     '<path d="M12 22a6 6 0 0 0 6-6c0-4-3-6-4-10-2 2-3 4-3 6-1-1-2-2-2-3-2 2-3 4-3 7a6 6 0 0 0 6 6z"/>'),
    ("wasserhahn", "Wasserhahn",
     '<path d="M4 9h9a3 3 0 0 1 3 3v2M4 6v6M9 9V6M7 6h4"/><path d="M16 18v.01"/>'),
    ("haus", "Haus",
     '<path d="M3 11l9-8 9 8"/><path d="M5 9.5V21h14V9.5M10 21v-6h4v6"/>'),
    ("tuer", "Tür",
     '<path d="M6 22V3h12v19M3 22h18"/><path d="M15 12h.01"/>'),
    ("fenster", "Fenster",
     '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M12 3v18M4 12h16"/>'),
    ("rollladen", "Rollladen",
     '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M4 7h16M4 11h16M4 15h16"/>'),
    ("garage", "Garage / Tor",
     '<path d="M3 21V8l9-5 9 5v13"/><path d="M7 21v-9h10v9M7 15h10M7 18h10"/>'),
    ("schloss", "Schloss",
     '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
    ("kamera", "Kamera",
     '<rect x="2" y="6" width="14" height="12" rx="2"/><path d="M16 10l6-3v10l-6-3"/>'),
    ("drucker", "Drucker",
     '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/>'),
    ("drucker3d", "3D-Drucker",
     '<rect x="3" y="3" width="18" height="18" rx="1"/><path d="M3 7h18M10 7h4v3l-2 2-2-2z"/><path d="M6 18h12M9 18v-3h6v3"/>'),
    ("fernseher", "Fernseher",
     '<rect x="2" y="5" width="20" height="13" rx="2"/><path d="M8 21h8"/>'),
    ("musik", "Musik / Lautsprecher",
     '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'),
    ("glocke", "Alarm / Klingel",
     '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>'),
    ("uhr", "Uhr / Zeit",
     '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    ("pflanze", "Pflanze / Garten",
     '<path d="M12 22V12"/><path d="M12 12C12 7 8 5 4 5c0 4 3 7 8 7z"/><path d="M12 15c0-4 3-6 8-6 0 4-3 6-8 6z"/>'),
    ("wolke", "Wetter",
     '<path d="M17.5 19H8a5 5 0 1 1 1.3-9.8A6 6 0 0 1 20.4 11 4 4 0 0 1 17.5 19z"/>'),
    ("wind", "Wind / Luft",
     '<path d="M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7"/>'),
    ("person", "Person / Anwesenheit",
     '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
    ("info", "Allgemein / Info",
     '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>'),
]
ICON_KEYS = set(k for k, _, _ in ICONS)

FARBEN = {
    "gruen": ("Grün", "#3ddc97"),
    "orange": ("Orange", "#ff9142"),
    "rot": ("Rot", "#ff5d5d"),
    "blau": ("Blau", "#4aa3ff"),
    "gelb": ("Gelb", "#ffd24a"),
    "lila": ("Lila", "#b38cff"),
    "grau": ("Grau", "#8891a0"),
}

VERGLEICHE = [
    (">=", "erreicht oder überschreitet (>=)"),
    (">", "überschreitet (>)"),
    ("<=", "erreicht oder unterschreitet (<=)"),
    ("<", "unterschreitet (<)"),
    ("==", "erreicht genau / ist gleich (=)"),
    ("!=", "ist ungleich"),
    ("enthaelt", "Text enthält"),
]
VERGLEICH_KEYS = set(k for k, _ in VERGLEICHE)


# ----------------------------------------------------------------------
# Konfiguration (menschenlesbare JSON-Datei)
# ----------------------------------------------------------------------
def _gen_id(prefix="k"):
    return prefix + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def default_config():
    return {
        "_hinweis": ("Konfiguration von " + APP_NAME + ". Kann mit jedem Texteditor bearbeitet werden "
                     "(Programm vorher beenden). Die meisten Werte lassen sich bequemer auf der "
                     "Webseite unter 'Einstellungen' ändern."),
        "server": {
            "port": DEFAULT_PORT,
            "host": "0.0.0.0",
            "titel": "MQTT Kacheln",
            "browser_oeffnen": True,
        },
        "broker": {
            "host": "",
            "port": 1883,
            "benutzer": "",
            "passwort": "",
            "tls": False,
            "tls_zertifikat_nicht_pruefen": False,
            "client_id": "",
            "topic_filter": "#",
            "keepalive": 30,
        },
        "kacheln": [],
    }


def _as_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "ja", "yes", "on", "an")
    return default


def _as_int(v, default, lo=None, hi=None):
    try:
        n = int(str(v).strip())
    except Exception:
        return default
    if lo is not None and n < lo:
        return default
    if hi is not None and n > hi:
        return default
    return n


def _as_float(v, default):
    try:
        return float(str(v).strip().replace(",", "."))
    except Exception:
        return default


def normalize_tile(t, keep_id=True):
    t = t if isinstance(t, dict) else {}
    tid = str(t.get("id") or "").strip() if keep_id else ""
    if not tid or not all(c.isalnum() or c in "-_" for c in tid):
        tid = _gen_id()
    symbol = str(t.get("symbol") or "info")
    if symbol not in ICON_KEYS:
        symbol = "info"
    schwellen = []
    for s in (t.get("schwellwerte") or []):
        if not isinstance(s, dict):
            continue
        v = str(s.get("vergleich") or ">=")
        if v not in VERGLEICH_KEYS:
            v = ">="
        farbe = str(s.get("farbe") or "orange")
        if farbe not in FARBEN:
            farbe = "orange"
        schwellen.append({
            "vergleich": v,
            "wert": str(s.get("wert") if s.get("wert") is not None else "").strip()[:100],
            "text": str(s.get("text") or "").strip()[:80],
            "farbe": farbe,
        })
    modus = str(t.get("treffer_modus") or "alle")
    if modus not in ("alle", "erster"):
        modus = "alle"
    return {
        "id": tid,
        "name": str(t.get("name") or "").strip()[:60] or "Neue Kachel",
        "topic": str(t.get("topic") or "").strip()[:300],
        "json_feld": str(t.get("json_feld") or "").strip()[:200],
        "einheit": str(t.get("einheit") or "").strip()[:20],
        "nachkommastellen": _as_int(t.get("nachkommastellen"), -1, -1, 6),
        "faktor": _as_float(t.get("faktor"), 1.0) or 1.0,
        "symbol": symbol,
        "treffer_modus": modus,
        "schwellwerte": schwellen[:20],
    }


def normalize_config(raw):
    cfg = default_config()
    if not isinstance(raw, dict):
        return cfg
    s = raw.get("server") or {}
    if isinstance(s, dict):
        cfg["server"]["port"] = _as_int(s.get("port"), DEFAULT_PORT, 1, 65535)
        cfg["server"]["host"] = str(s.get("host") or "0.0.0.0").strip() or "0.0.0.0"
        cfg["server"]["titel"] = (str(s.get("titel") or "").strip() or "MQTT Kacheln")[:60]
        cfg["server"]["browser_oeffnen"] = _as_bool(s.get("browser_oeffnen"), True)
    b = raw.get("broker") or {}
    if isinstance(b, dict):
        cb = cfg["broker"]
        cb["host"] = str(b.get("host") or "").strip()
        cb["port"] = _as_int(b.get("port"), 1883, 1, 65535)
        cb["benutzer"] = str(b.get("benutzer") or "")
        cb["passwort"] = str(b.get("passwort") or "")
        cb["tls"] = _as_bool(b.get("tls"), False)
        cb["tls_zertifikat_nicht_pruefen"] = _as_bool(b.get("tls_zertifikat_nicht_pruefen"), False)
        cb["client_id"] = str(b.get("client_id") or "").strip()[:64]
        cb["topic_filter"] = str(b.get("topic_filter") or "#").strip() or "#"
        cb["keepalive"] = _as_int(b.get("keepalive"), 30, 5, 600)
    tiles = raw.get("kacheln") or []
    seen = set()
    if isinstance(tiles, list):
        for t in tiles:
            nt = normalize_tile(t)
            while nt["id"] in seen:
                nt["id"] = _gen_id()
            seen.add(nt["id"])
            cfg["kacheln"].append(nt)
    return cfg


class ConfigStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.cfg = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            cfg = default_config()
            cfg["broker"]["client_id"] = "kachel-" + _gen_id("")[:6]
            self._write(cfg)
            print("[Config] Neue Konfigurationsdatei angelegt: " + self.path)
            return cfg
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            # Kaputte Datei NICHT ueberschreiben, sondern sichern
            backup = self.path + ".defekt-" + time.strftime("%Y%m%d-%H%M%S")
            try:
                shutil.copy2(self.path, backup)
            except Exception:
                pass
            print("[Config] FEHLER beim Lesen von %s (%s) - Sicherung: %s - starte mit Standardwerten."
                  % (self.path, e, backup))
            cfg = default_config()
            self._write(cfg)
            return cfg
        cfg = normalize_config(raw)
        if cfg["broker"]["client_id"] == "":
            cfg["broker"]["client_id"] = "kachel-" + _gen_id("")[:6]
            self._write(cfg)
        return cfg

    def _write(self, cfg):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)

    def save(self):
        with self.lock:
            self._write(self.cfg)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.cfg))


# ----------------------------------------------------------------------
# Schlanker MQTT-3.1.1-Client (nur Standardbibliothek)
# ----------------------------------------------------------------------
CONNACK_TEXT = {
    1: "Protokollversion wird vom Broker nicht unterstützt",
    2: "Client-ID abgelehnt",
    3: "Broker nicht verfügbar",
    4: "Benutzername oder Passwort falsch",
    5: "Nicht autorisiert",
}


def _mqtt_str(s):
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _mqtt_remaining_length(n):
    out = bytearray()
    while True:
        d = n % 128
        n //= 128
        if n > 0:
            d |= 0x80
        out.append(d)
        if n == 0:
            return bytes(out)


def _mqtt_packet(header, body):
    return bytes([header]) + _mqtt_remaining_length(len(body)) + body


def _parse_packets(buf):
    """Zerlegt den Puffer in vollstaendige Pakete. Gibt (pakete, rest) zurueck."""
    packets = []
    pos = 0
    n = len(buf)
    while True:
        if n - pos < 2:
            break
        mult = 1
        length = 0
        i = pos + 1
        complete_len = False
        while i < n and i < pos + 5:
            b = buf[i]
            length += (b & 0x7F) * mult
            mult *= 128
            i += 1
            if not (b & 0x80):
                complete_len = True
                break
        if not complete_len:
            if i >= pos + 5:
                raise ValueError("Ungueltige Paketlaenge")
            break
        if n - i < length:
            break
        packets.append((buf[pos], bytes(buf[i:i + length])))
        pos = i + length
    return packets, buf[pos:]


def mqtt_open_socket(bcfg, timeout=10):
    sock = socket.create_connection((bcfg["host"], int(bcfg["port"])), timeout=timeout)
    if bcfg.get("tls"):
        ctx = ssl.create_default_context()
        if bcfg.get("tls_zertifikat_nicht_pruefen"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(sock, server_hostname=bcfg["host"])
    return sock


def mqtt_connect_packet(bcfg, client_id):
    flags = 0x02  # clean session
    payload = _mqtt_str(client_id)
    if bcfg.get("benutzer"):
        flags |= 0x80
        payload += _mqtt_str(bcfg["benutzer"])
        if bcfg.get("passwort"):
            flags |= 0x40
            payload += _mqtt_str(bcfg["passwort"])
    body = _mqtt_str("MQTT") + bytes([4, flags]) + struct.pack("!H", int(bcfg.get("keepalive", 30))) + payload
    return _mqtt_packet(0x10, body)


def _read_connack(sock, timeout=10):
    sock.settimeout(timeout)
    buf = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = sock.recv(4096)
        if not data:
            raise ConnectionError("Verbindung vom Broker geschlossen")
        buf += data
        packets, buf = _parse_packets(buf)
        for ptype, body in packets:
            if ptype >> 4 == 2:
                rc = body[1] if len(body) >= 2 else 255
                return rc, buf
    raise TimeoutError("Keine Antwort (CONNACK) vom Broker")


def mqtt_test_connection(bcfg):
    """Einmaliger Verbindungstest - liefert (ok, text)."""
    if not bcfg.get("host"):
        return False, "Kein Broker-Host angegeben"
    try:
        sock = mqtt_open_socket(bcfg, timeout=6)
    except Exception as e:
        return False, "Verbindung fehlgeschlagen: %s" % e
    try:
        sock.sendall(mqtt_connect_packet(bcfg, "kachel-test-" + _gen_id("")[:5]))
        rc, _ = _read_connack(sock, timeout=6)
        if rc == 0:
            try:
                sock.sendall(b"\xe0\x00")
            except Exception:
                pass
            return True, "Verbindung erfolgreich"
        return False, CONNACK_TEXT.get(rc, "Broker lehnte ab (Code %s)" % rc)
    except Exception as e:
        return False, "Fehler: %s" % e
    finally:
        try:
            sock.close()
        except Exception:
            pass


class MqttClient:
    def __init__(self, store, topic_cache):
        self.store = store
        self.cache = topic_cache
        self.sock = None
        self.send_lock = threading.Lock()
        self.wake = threading.Event()
        self.restart_flag = False
        self.running = True
        self.connected = False
        self.status = "Kein Broker eingerichtet"
        self.subscribed = set()
        self.denied = set()
        self.packet_id = 1
        self.last_send = 0.0
        self.thread = threading.Thread(target=self._run, name="mqtt", daemon=True)

    def start(self):
        self.thread.start()

    def restart(self):
        self.restart_flag = True
        self._close_socket()
        self.wake.set()

    def stop(self):
        self.running = False
        try:
            self._send(b"\xe0\x00")
        except Exception:
            pass
        self.restart()

    def _close_socket(self):
        s = self.sock
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

    def _send(self, data):
        s = self.sock
        if s is None:
            raise ConnectionError("nicht verbunden")
        with self.send_lock:
            s.sendall(data)
            self.last_send = time.time()

    def _next_pid(self):
        self.packet_id = self.packet_id % 65535 + 1
        return self.packet_id

    def wanted_filters(self):
        cfg = self.store.snapshot()
        f = [cfg["broker"]["topic_filter"] or "#"]
        for t in cfg["kacheln"]:
            if t["topic"] and t["topic"] not in f:
                f.append(t["topic"])
        return f

    def ensure_subscriptions(self):
        """Neue Kachel-Topics nachtraeglich abonnieren (ohne Neuverbindung)."""
        if not self.connected:
            return
        for flt in self.wanted_filters():
            if flt in self.subscribed:
                continue
            try:
                body = struct.pack("!H", self._next_pid()) + _mqtt_str(flt) + b"\x00"
                self._send(_mqtt_packet(0x82, body))
                self.subscribed.add(flt)
            except Exception:
                pass

    def _run(self):
        backoff = 2
        while self.running:
            self.restart_flag = False
            bcfg = self.store.snapshot()["broker"]
            if not bcfg["host"]:
                self.connected = False
                self.status = "Kein Broker eingerichtet"
                self.wake.wait(5)
                self.wake.clear()
                continue
            try:
                self.status = "Verbinde mit %s:%s ..." % (bcfg["host"], bcfg["port"])
                sock = mqtt_open_socket(bcfg, timeout=10)
                self.sock = sock
                sock.sendall(mqtt_connect_packet(bcfg, bcfg["client_id"] or ("kachel-" + _gen_id("")[:6])))
                self.last_send = time.time()
                rc, buf = _read_connack(sock, timeout=10)
                if rc != 0:
                    raise ConnectionError(CONNACK_TEXT.get(rc, "Broker lehnte ab (Code %s)" % rc))
                self.connected = True
                self.subscribed = set()
                self.denied = set()
                self.status = "Verbunden mit %s:%s" % (bcfg["host"], bcfg["port"])
                print("[MQTT] " + self.status)
                backoff = 2
                self.ensure_subscriptions()
                self._loop(sock, buf, int(bcfg.get("keepalive", 30)))
            except Exception as e:
                if self.running and not self.restart_flag:
                    self.status = "Fehler: %s" % e
                    print("[MQTT] " + self.status)
            finally:
                self.connected = False
                self._close_socket()
                self.sock = None
            if not self.running:
                break
            if self.restart_flag:
                continue
            self.wake.wait(backoff)
            self.wake.clear()
            backoff = min(backoff * 2, 30)

    def _loop(self, sock, buf, keepalive):
        sock.settimeout(1.0)
        last_rx = time.time()
        while self.running and not self.restart_flag:
            try:
                data = sock.recv(65536)
                if not data:
                    raise ConnectionError("Verbindung vom Broker getrennt")
                buf += data
                last_rx = time.time()
                packets, buf = _parse_packets(buf)
                for ptype, body in packets:
                    self._handle(ptype, body)
            except (socket.timeout, TimeoutError):
                pass
            now = time.time()
            if now - self.last_send > keepalive * 0.5:
                self._send(b"\xc0\x00")  # PINGREQ
            if now - last_rx > keepalive * 1.6:
                raise ConnectionError("Broker antwortet nicht mehr (Keepalive)")

    def _handle(self, ptype, body):
        kind = ptype >> 4
        if kind == 3:  # PUBLISH
            qos = (ptype >> 1) & 0x03
            retain = bool(ptype & 0x01)
            tlen = struct.unpack("!H", body[:2])[0]
            topic = body[2:2 + tlen].decode("utf-8", "replace")
            pos = 2 + tlen
            if qos > 0:
                pid = body[pos:pos + 2]
                pos += 2
                if qos == 1:
                    self._send(b"\x40\x02" + pid)        # PUBACK
                else:
                    self._send(b"\x50\x02" + pid)        # PUBREC
            self.cache.update(topic, body[pos:], retain)
        elif kind == 6:  # PUBREL
            self._send(b"\x70\x02" + body[:2])          # PUBCOMP
        elif kind == 9:  # SUBACK
            if any(b == 0x80 for b in body[2:]):
                self.status = self.status.split(" - ")[0] + " - ein Abo wurde vom Broker abgelehnt (Rechte?)"


class TopicCache:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.data = {}   # topic -> (text, ts, retained, size, binary)

    def _tile_topics(self):
        return set(t["topic"] for t in self.store.cfg["kacheln"])

    def update(self, topic, payload, retained):
        size = len(payload)
        binary = False
        if size > MAX_PAYLOAD_STORE:
            text = "[%d Bytes - zu groß für die Anzeige]" % size
            binary = True
        else:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                text = "[Binärdaten, %d Bytes]" % size
                binary = True
        with self.lock:
            if topic not in self.data and len(self.data) >= MAX_TOPICS and topic not in self._tile_topics():
                return
            self.data[topic] = (text, time.time(), retained, size, binary)

    def get(self, topic):
        with self.lock:
            return self.data.get(topic)

    def search(self, q, limit):
        q = (q or "").lower().strip()
        with self.lock:
            items = list(self.data.items())
        total = len(items)
        if q:
            parts = q.split()
            items = [it for it in items if all(p in it[0].lower() or p in it[1][0][:200].lower() for p in parts)]
        items.sort(key=lambda it: it[0])
        return total, len(items), items[:limit]


# ----------------------------------------------------------------------
# Kachel-Auswertung
# ----------------------------------------------------------------------
def extract_json_field(text, path):
    try:
        obj = json.loads(text)
    except Exception:
        return False, "Kein JSON"
    if not path:
        return True, obj
    for part in path.replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(obj, dict):
            if part in obj:
                obj = obj[part]
            else:
                low = {str(k).lower(): k for k in obj}
                if part.lower() in low:
                    obj = obj[low[part.lower()]]
                else:
                    return False, "Feld '%s' fehlt" % part
        elif isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except Exception:
                return False, "Index '%s' ungültig" % part
        else:
            return False, "Feld '%s' fehlt" % part
    return True, obj


def flatten_json(obj, prefix="", out=None, limit=300):
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten_json(v, (prefix + "." if prefix else "") + str(k), out, limit)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            flatten_json(v, (prefix + "." if prefix else "") + str(i), out, limit)
    else:
        val = "null" if obj is None else (("true" if obj else "false") if isinstance(obj, bool) else str(obj))
        out.append({"pfad": prefix, "wert": val[:80]})
    return out


def to_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", ".")
        if not s:
            return None
        try:
            f = float(s)
            if f != f or f in (float("inf"), float("-inf")):
                return None
            return f
        except Exception:
            return None
    return None


def format_number(x, decimals):
    if decimals is None or decimals < 0:
        if abs(x - round(x)) < 1e-9 and abs(x) < 1e15:
            s = "%d" % round(x)
        else:
            s = ("%.2f" % x).rstrip("0").rstrip(".")
    else:
        s = "%.*f" % (decimals, x)
    if s in ("-0",) or (s.startswith("-") and to_number(s) == 0):
        s = s[1:]
    return s.replace(".", ",")


def compare(op, value_num, value_text, ref):
    ref_num = to_number(ref)
    if op == "enthaelt":
        return ref != "" and ref.lower() in value_text.lower()
    if value_num is not None and ref_num is not None:
        if op == ">=":
            return value_num >= ref_num
        if op == ">":
            return value_num > ref_num
        if op == "<=":
            return value_num <= ref_num
        if op == "<":
            return value_num < ref_num
        if op == "==":
            return abs(value_num - ref_num) < 1e-9
        if op == "!=":
            return abs(value_num - ref_num) >= 1e-9
        return False
    if op == "==":
        return value_text.strip().lower() == ref.strip().lower()
    if op == "!=":
        return value_text.strip().lower() != ref.strip().lower()
    return False


def evaluate_tile(tile, cache):
    res = {
        "id": tile["id"], "name": tile["name"], "symbol": tile["symbol"], "topic": tile["topic"],
        "einheit": tile["einheit"], "wert": None, "hat_wert": False, "zeit": None,
        "fehler": None, "treffer": [], "farbe": None,
    }
    if not tile["topic"]:
        res["fehler"] = "Kein Topic gewählt"
        return res
    entry = cache.get(tile["topic"])
    if entry is None:
        return res
    text, ts, _retained, _size, binary = entry
    res["zeit"] = ts
    if binary:
        res["fehler"] = text
        return res
    raw = text
    if tile["json_feld"]:
        ok, val = extract_json_field(text, tile["json_feld"])
        if not ok:
            res["fehler"] = val
            return res
        raw = val
    num = to_number(raw)
    if isinstance(raw, bool):
        vtext = "true" if raw else "false"
    elif raw is None:
        vtext = "null"
    elif isinstance(raw, (dict, list)):
        vtext = json.dumps(raw, ensure_ascii=False)
    else:
        vtext = str(raw).strip()
    if num is not None:
        num = num * (tile["faktor"] or 1.0)
        shown = format_number(num, tile["nachkommastellen"])
        cmp_text = shown
    else:
        shown = vtext if len(vtext) <= 60 else vtext[:57] + "..."
        cmp_text = vtext
    res["wert"] = shown
    res["hat_wert"] = True
    for s in tile["schwellwerte"]:
        if compare(s["vergleich"], num, cmp_text, s["wert"]):
            res["treffer"].append({"text": s["text"], "farbe": FARBEN[s["farbe"]][1]})
            if tile["treffer_modus"] == "erster":
                break
    if res["treffer"]:
        res["farbe"] = res["treffer"][0]["farbe"]
    return res


# ----------------------------------------------------------------------
# Hilfen
# ----------------------------------------------------------------------
def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips or ["127.0.0.1"]


def openwrt_update_firewall(port):
    """Auf dem Brume 2 die vom Installer angelegte Firewall-Regel mitziehen."""
    if not os.path.exists("/etc/openwrt_release") or not shutil.which("uci"):
        return
    try:
        r = subprocess.run(["uci", "-q", "get", "firewall.mqtt_kachel_dashboard"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if r.returncode != 0:
            return
        subprocess.run(["uci", "set", "firewall.mqtt_kachel_dashboard.dest_port=%d" % port], timeout=10)
        subprocess.run(["uci", "commit", "firewall"], timeout=10)
        subprocess.run(["/etc/init.d/firewall", "reload"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=60)
        print("[Server] Firewall-Regel auf Port %d angepasst" % port)
    except Exception as e:
        print("[Server] Firewall-Regel konnte nicht angepasst werden: %s" % e)


# ----------------------------------------------------------------------
# Web-Server (http.server, Port zur Laufzeit wechselbar)
# ----------------------------------------------------------------------
class App:
    def __init__(self):
        self.store = ConfigStore(CONFIG_PATH)
        self.cache = TopicCache(self.store)
        self.mqtt = MqttClient(self.store, self.cache)
        self.server = None
        self.server_lock = threading.Lock()
        self.quit_event = threading.Event()

    # --- Server-Steuerung -------------------------------------------------
    def make_server(self, port):
        host = self.store.cfg["server"]["host"]
        srv = ThreadingHTTPServer((host, port), make_handler(self))
        srv.daemon_threads = True
        return srv

    def start_server(self, srv):
        t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
        t.start()

    def switch_port(self, new_port):
        with self.server_lock:
            old = self.server
            if old is not None and old.server_address[1] == new_port:
                return True, "Port unverändert"
            try:
                srv = self.make_server(new_port)
            except OSError as e:
                return False, "Port %d ist nicht nutzbar (%s)" % (new_port, e.strerror or e)
            self.start_server(srv)
            self.server = srv
            with self.store.lock:
                self.store.cfg["server"]["port"] = new_port
                self.store.save()
            print("[Server] Webseite jetzt erreichbar auf Port %d" % new_port)

        def _close_old():
            time.sleep(2.0)
            if old is not None:
                try:
                    old.shutdown()
                    old.server_close()
                except Exception:
                    pass
        threading.Thread(target=_close_old, daemon=True).start()
        threading.Thread(target=openwrt_update_firewall, args=(new_port,), daemon=True).start()
        return True, "Port geändert"

    # --- API --------------------------------------------------------------
    def api_state(self):
        cfg = self.store.snapshot()
        tiles = [evaluate_tile(t, self.cache) for t in cfg["kacheln"]]
        return {
            "titel": cfg["server"]["titel"],
            "version": APP_VERSION,
            "jetzt": time.time(),
            "broker": {
                "eingerichtet": bool(cfg["broker"]["host"]),
                "verbunden": self.mqtt.connected,
                "status": self.mqtt.status,
            },
            "kacheln": tiles,
        }

    def api_config(self):
        cfg = self.store.snapshot()
        b = cfg["broker"]
        b["passwort_gesetzt"] = bool(b.get("passwort"))
        b["passwort"] = ""
        port = self.server.server_address[1] if self.server else cfg["server"]["port"]
        return {
            "server": cfg["server"],
            "broker": b,
            "kacheln": cfg["kacheln"],
            "aktiver_port": port,
            "adressen": ["http://%s:%d" % (ip, port) for ip in local_ips()],
            "config_pfad": CONFIG_PATH,
            "version": APP_VERSION,
            "beenden_moeglich": bool(getattr(sys, "frozen", False)),
            "symbole": [{"key": k, "name": n, "svg": s} for k, n, s in ICONS],
            "farben": [{"key": k, "name": v[0], "hex": v[1]} for k, v in FARBEN.items()],
            "vergleiche": [{"key": k, "name": n} for k, n in VERGLEICHE],
        }

    def broker_from_input(self, data):
        cur = self.store.snapshot()["broker"]
        merged = dict(cur)
        for key in ("host", "port", "benutzer", "tls", "tls_zertifikat_nicht_pruefen", "client_id",
                    "topic_filter", "keepalive"):
            if key in data:
                merged[key] = data[key]
        if data.get("passwort_loeschen"):
            merged["passwort"] = ""
        elif data.get("passwort"):
            merged["passwort"] = data["passwort"]
        tmp = normalize_config({"broker": merged})["broker"]
        if not tmp["client_id"]:
            tmp["client_id"] = cur.get("client_id") or ("kachel-" + _gen_id("")[:6])
        return tmp


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MQTTKachelDashboard/" + APP_VERSION

        def log_message(self, fmt, *args):
            pass

        # --- Antworten ---------------------------------------------------
        def _send(self, code, body, ctype):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def _err(self, msg, code=400):
            self._json({"ok": False, "fehler": msg}, code)

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > 1_000_000:
                return {}
            try:
                data = json.loads(self.rfile.read(n).decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        # --- GET ---------------------------------------------------------
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            p = u.path
            if p in ("/", "/index.html"):
                html = INDEX_HTML.replace("__APP_VERSION__", APP_VERSION)
                return self._send(200, html, "text/html; charset=utf-8")
            if p == "/manifest.webmanifest":
                title = app.store.cfg["server"]["titel"]
                man = {"name": title, "short_name": title[:12], "start_url": "/", "display": "standalone",
                       "background_color": "#0a0c0f", "theme_color": "#0a0c0f",
                       "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}
                return self._send(200, json.dumps(man), "application/manifest+json")
            if p in ("/icon.svg", "/favicon.svg"):
                return self._send(200, ICON_SVG, "image/svg+xml")
            if p in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico"):
                return self._send(200, APPLE_ICON_PNG, "image/png")
            if p == "/api/state":
                return self._json(app.api_state())
            if p == "/api/config":
                return self._json(app.api_config())
            if p == "/api/topics":
                qs = (q.get("q") or [""])[0]
                limit = _as_int((q.get("limit") or ["300"])[0], 300, 1, 2000)
                total, found, items = app.cache.search(qs, limit)
                now = time.time()
                out = []
                for topic, (text, ts, retained, size, binary) in items:
                    out.append({"topic": topic, "wert": text[:120], "alter": round(now - ts, 1),
                                "retained": retained, "binaer": binary})
                return self._json({"gesamt": total, "gefunden": found, "topics": out,
                                   "verbunden": app.mqtt.connected})
            if p == "/api/topic":
                t = (q.get("t") or [""])[0]
                e = app.cache.get(t)
                if e is None:
                    return self._json({"vorhanden": False})
                text = e[0]
                felder = []
                if not e[4]:
                    ok, obj = extract_json_field(text, "")
                    if ok and isinstance(obj, (dict, list)):
                        felder = flatten_json(obj)
                return self._json({"vorhanden": True, "wert": text[:4000], "felder": felder,
                                   "alter": round(time.time() - e[1], 1)})
            return self._send(404, "Nicht gefunden", "text/plain; charset=utf-8")

        # --- POST --------------------------------------------------------
        def do_POST(self):
            p = urlparse(self.path).path
            data = self._body()

            if p == "/api/server":
                title = str(data.get("titel") or "").strip()
                if title:
                    with app.store.lock:
                        app.store.cfg["server"]["titel"] = title[:60]
                        app.store.save()
                if "browser_oeffnen" in data:
                    with app.store.lock:
                        app.store.cfg["server"]["browser_oeffnen"] = _as_bool(data["browser_oeffnen"])
                        app.store.save()
                if "port" in data:
                    port = _as_int(data.get("port"), 0, 1, 65535)
                    if not port:
                        return self._err("Ungültiger Port (erlaubt: 1-65535)")
                    ok, msg = app.switch_port(port)
                    if not ok:
                        return self._err(msg)
                    return self._json({"ok": True, "port": port, "meldung": msg})
                return self._json({"ok": True})

            if p == "/api/broker":
                bcfg = app.broker_from_input(data)
                if bcfg["host"] and any(c.isspace() for c in bcfg["host"]):
                    return self._err("Host darf keine Leerzeichen enthalten")
                with app.store.lock:
                    app.store.cfg["broker"] = bcfg
                    app.store.save()
                app.mqtt.restart()
                return self._json({"ok": True})

            if p == "/api/broker/test":
                bcfg = app.broker_from_input(data)
                ok, msg = mqtt_test_connection(bcfg)
                return self._json({"ok": ok, "meldung": msg})

            if p == "/api/tiles":
                tile = normalize_tile(data, keep_id=True)
                with app.store.lock:
                    tiles = app.store.cfg["kacheln"]
                    for i, t in enumerate(tiles):
                        if t["id"] == tile["id"]:
                            tiles[i] = tile
                            break
                    else:
                        tile = normalize_tile(data, keep_id=False)
                        tiles.append(tile)
                    app.store.save()
                app.mqtt.ensure_subscriptions()
                return self._json({"ok": True, "kachel": tile})

            if p == "/api/tiles/delete":
                tid = str(data.get("id") or "")
                with app.store.lock:
                    before = len(app.store.cfg["kacheln"])
                    app.store.cfg["kacheln"] = [t for t in app.store.cfg["kacheln"] if t["id"] != tid]
                    if len(app.store.cfg["kacheln"]) == before:
                        return self._err("Kachel nicht gefunden", 404)
                    app.store.save()
                return self._json({"ok": True})

            if p == "/api/tiles/order":
                ids = data.get("ids") or []
                with app.store.lock:
                    tiles = app.store.cfg["kacheln"]
                    by_id = {t["id"]: t for t in tiles}
                    new = [by_id[i] for i in ids if i in by_id]
                    new += [t for t in tiles if t["id"] not in set(ids)]
                    app.store.cfg["kacheln"] = new
                    app.store.save()
                return self._json({"ok": True})

            if p == "/api/preview":
                tile = normalize_tile(data, keep_id=True)
                return self._json(evaluate_tile(tile, app.cache))

            if p == "/api/quit":
                if not getattr(sys, "frozen", False):
                    return self._err("Beenden ist nur bei der exe/App vorgesehen")
                self._json({"ok": True})
                threading.Thread(target=lambda: (time.sleep(0.5), app.quit_event.set()), daemon=True).start()
                return None

            return self._err("Unbekannter Aufruf", 404)

    return Handler


# ----------------------------------------------------------------------
# App-Icon (SVG fuer Browser, PNG fuer iPhone-Homebildschirm)
# ----------------------------------------------------------------------
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#0a0c0f"/>
<rect x="12" y="12" width="18" height="18" rx="4" fill="#ff9142"/>
<rect x="34" y="12" width="18" height="18" rx="4" fill="#12151a" stroke="#3a4250" stroke-width="2"/>
<rect x="12" y="34" width="18" height="18" rx="4" fill="#12151a" stroke="#3a4250" stroke-width="2"/>
<rect x="34" y="34" width="18" height="18" rx="4" fill="#3ddc97"/>
</svg>"""

# 180x180 PNG (base64) fuer den iPhone-Homebildschirm
APPLE_ICON_PNG_B64 = "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"


def _load_png():
    import base64
    try:
        return base64.b64decode(APPLE_ICON_PNG_B64)
    except Exception:
        return b""


APPLE_ICON_PNG = b""


# ----------------------------------------------------------------------
# Frontend (Design angelehnt an Drucker Dashboard MK6)
# ----------------------------------------------------------------------
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0a0c0f">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Kacheln">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<title>MQTT Kacheln</title>
<style>
  :root{
    --bg:#0a0c0f;
    --panel:#12151a;
    --panel-2:#171b21;
    --border:#242a33;
    --text:#e5e8ec;
    --text-dim:#8891a0;
    --accent:#ff9142;
    --accent-2:#3ddc97;
    --danger:#ff5d5d;
    --info:#4aa3ff;
    --mono: 'JetBrains Mono', 'Consolas', 'SFMono-Regular', ui-monospace, Menlo, monospace;
    --sans: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    --tile-min: 235px;
    --gut-l: max(32px, env(safe-area-inset-left));
    --gut-r: max(32px, env(safe-area-inset-right));
  }
  *{box-sizing:border-box;}
  html{ -webkit-text-size-adjust:100%; }
  body{
    margin:0; background:var(--bg); color:var(--text);
    font-family:var(--sans); letter-spacing:0.1px; min-height:100vh;
    padding-bottom:env(safe-area-inset-bottom);
  }

  header{
    display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap;
    padding:22px var(--gut-r) 22px var(--gut-l); border-bottom:1px solid var(--border);
    padding-top:max(22px, env(safe-area-inset-top));
    background:linear-gradient(180deg,#0d1014,#0a0c0f);
    position:sticky; top:0; z-index:20;
  }
  header h1{
    font-size:18px; font-weight:600; margin:0; letter-spacing:0.5px;
    text-transform:uppercase; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  header h1 span.acc{ color:var(--accent); }
  .ver-badge{
    font-family:var(--mono); font-size:11px; color:var(--text-dim);
    font-weight:400; vertical-align:middle; margin-left:4px; text-transform:none;
  }
  .head-controls{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .btn{
    background:var(--accent); color:#12100c; border:none; border-radius:6px;
    padding:10px 18px; font-weight:600; font-size:13px; cursor:pointer;
    letter-spacing:0.3px; transition:filter .15s ease; font-family:var(--sans);
    -webkit-tap-highlight-color:transparent;
  }
  .btn:hover{ filter:brightness(1.1); }
  .btn:disabled{ opacity:.5; cursor:default; }
  .btn-ghost{ background:transparent; color:var(--text-dim); border:1px solid var(--border); }
  .btn-ghost:hover{ color:var(--text); border-color:#3a4250; }
  .btn-danger{ background:transparent; color:var(--danger); border:1px solid #c0392b66; }
  .btn-danger:hover{ border-color:var(--danger); }
  .btn-mini{
    background:#1b2027; color:var(--text); border:1px solid var(--border);
    border-radius:5px; padding:6px 10px; font-size:11px; cursor:pointer;
    font-family:var(--mono);
  }
  .btn-mini:hover{ border-color:var(--accent-2); }
  .btn-mini.btn-delete{ color:var(--danger); border-color:#c0392b66; }
  .btn-mini.btn-delete:hover{ border-color:var(--danger); }
  .btn-mini:disabled{ opacity:.35; cursor:default; }


  .status-dot{
    width:9px; height:9px; border-radius:50%; display:inline-block; flex-shrink:0;
    background:var(--danger);
  }
  .status-dot.online{ background:var(--accent-2); box-shadow:0 0 6px var(--accent-2); }
  .status-dot.idle{ background:var(--text-dim); }

  /* ---------- Kacheln ---------- */
  #tiles{
    padding:28px var(--gut-r) 28px var(--gut-l); max-width:2400px; margin:0 auto;
    display:grid; grid-template-columns:repeat(auto-fill, minmax(min(var(--tile-min), 100%), 1fr));
    gap:18px; align-items:stretch;
  }
  .tile{
    background:var(--panel); border:1px solid var(--border); border-radius:10px;
    overflow:hidden; display:flex; flex-direction:column; container-type:inline-size;
    transition:border-color .25s ease, box-shadow .25s ease;
  }
  .tile-head{
    display:flex; align-items:center; gap:12px; padding:14px 16px;
    border-bottom:1px solid var(--border); background:var(--panel-2); min-width:0;
  }
  .tile-icon{
    width:40px; height:40px; border-radius:8px; flex-shrink:0;
    display:flex; align-items:center; justify-content:center;
    border:1px solid var(--border); background:#1b2027; color:var(--accent);
    transition:color .25s ease, border-color .25s ease;
  }
  .tile-icon svg{ width:23px; height:23px; }
  svg.ico{ fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
  .tile-titles{ min-width:0; flex:1; }
  .tile-name{ font-size:15px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .tile-topic{
    font-family:var(--mono); font-size:11px; color:var(--text-dim); margin-top:2px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  .tile-body{ padding:16px 16px 14px; flex:1; display:flex; flex-direction:column; gap:12px; justify-content:center; }
  .tile-value{
    font-family:var(--mono); font-weight:600; line-height:1.1; word-break:break-word;
    font-size:clamp(24px, 12cqi, 46px); letter-spacing:-0.5px;
  }
  .tile-unit{ font-size:.52em; color:var(--text-dim); margin-left:6px; font-weight:400; letter-spacing:0; white-space:nowrap; display:inline-block; }
  .tile-value.nodata{ font-size:14px; color:var(--text-dim); font-weight:400; font-family:var(--sans); letter-spacing:0; }
  .tile-value.err{ font-size:13px; color:var(--danger); font-weight:400; font-family:var(--mono); letter-spacing:0; }
  .tile-chips{ display:flex; flex-wrap:wrap; gap:6px; }
  .chip{
    font-family:var(--mono); font-size:11px; padding:3px 10px; border-radius:20px;
    border:1px solid currentColor; letter-spacing:.3px; font-weight:600;
    background:rgba(255,255,255,0.02); max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }

  .empty-state{ grid-column:1/-1; text-align:center; padding:70px 20px; color:var(--text-dim); }
  .empty-state h2{ color:var(--text); font-size:16px; text-transform:uppercase; letter-spacing:.5px; }
  .empty-state .btn{ margin-top:16px; }

  /* ---------- Einstellungen ---------- */
  #settingsPanel{ padding:28px var(--gut-r) 40px var(--gut-l); max-width:980px; margin:0 auto; }
  .settings-section{
    background:var(--panel); border:1px solid var(--border); border-radius:10px;
    padding:20px 24px; margin-bottom:22px;
  }
  .settings-section h2{ font-size:14px; margin:0 0 10px 0; text-transform:uppercase; letter-spacing:0.5px; }
  label.lbl{
    font-size:11px; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.5px;
    display:block; margin-bottom:6px;
  }
  input[type=text], input[type=number], input[type=password], input[type=search], select{
    width:100%; background:#0d1014; border:1px solid var(--border); color:var(--text);
    padding:9px 10px; border-radius:6px; font-family:var(--mono); font-size:13px;
  }
  input:focus, select:focus{ outline:none; border-color:var(--accent); }
  .hint-text{ font-size:11.5px; color:var(--text-dim); margin:0 0 14px 0; line-height:1.45; }
  .form-grid{ display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:4px 16px; }
  .form-grid .full{ grid-column:1/-1; }
  .field{ margin-bottom:12px; min-width:0; }
  .checkbox-row{ display:flex; align-items:center; gap:8px; margin:4px 0 12px; font-size:13px; }
  .checkbox-row input{ width:18px; height:18px; accent-color:var(--accent); margin:0; }
  .actions-row{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:6px; }
  .msg{ font-family:var(--mono); font-size:12px; }
  .msg.ok{ color:var(--accent-2); }
  .msg.err{ color:var(--danger); }
  .addr-list{ font-family:var(--mono); font-size:12.5px; margin:4px 0 14px; display:flex; flex-direction:column; gap:3px; }
  .addr-list a{ color:var(--info); text-decoration:none; }
  .manage-row{
    display:flex; align-items:center; justify-content:space-between; gap:10px;
    padding:10px 0; border-bottom:1px solid var(--border);
  }
  .manage-row:last-child{ border-bottom:none; }
  .manage-icon{ width:32px; height:32px; border-radius:7px; border:1px solid var(--border); background:#1b2027;
    display:flex; align-items:center; justify-content:center; color:var(--accent); flex-shrink:0; }
  .manage-icon svg{ width:19px; height:19px; }
  .manage-info{ font-size:13px; flex:1; min-width:0; }
  .manage-sub{ color:var(--text-dim); font-size:11px; font-family:var(--mono); margin-top:2px; word-break:break-all; }
  .manage-actions{ display:flex; align-items:center; gap:6px; flex-shrink:0; flex-wrap:wrap; justify-content:flex-end; }
  .topic-browser-list{ max-height:420px; overflow-y:auto; border:1px solid var(--border); border-radius:8px; margin-top:10px; }
  .topic-row{ display:flex; align-items:center; gap:10px; padding:8px 12px; border-bottom:1px solid var(--border); }
  .topic-row:last-child{ border-bottom:none; }
  .topic-row .t-info{ flex:1; min-width:0; }
  .topic-row .t-name{ font-family:var(--mono); font-size:12.5px; word-break:break-all; }
  .topic-row .t-val{ font-family:var(--mono); font-size:11px; color:var(--text-dim); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px; }
  .t-empty{ padding:14px; font-size:12px; color:var(--text-dim); font-style:italic; }

  /* ---------- Modal ---------- */
  .modal-backdrop{
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.65);
    align-items:center; justify-content:center; z-index:50; padding:16px;
  }
  .modal-backdrop.show{ display:flex; }
  .modal{
    background:var(--panel); border:1px solid var(--border); border-radius:10px;
    width:min(640px, 100%); padding:24px; max-height:calc(100dvh - 32px); max-height:calc(100vh - 32px); overflow-y:auto;
    -webkit-overflow-scrolling:touch;
  }
  @supports (height:100dvh){ .modal{ max-height:calc(100dvh - 32px); } }
  .modal.small{ width:min(400px, 100%); }
  .modal h2{ font-size:15px; margin:0 0 18px 0; text-transform:uppercase; letter-spacing:0.5px; }
  .modal-actions{ display:flex; justify-content:flex-end; gap:10px; margin-top:14px; flex-wrap:wrap; }
  .topic-pick{ position:relative; }
  .suggest{
    display:none; position:absolute; left:0; right:0; top:100%; margin-top:4px; z-index:5;
    background:#0d1014; border:1px solid var(--border); border-radius:6px; max-height:260px; overflow-y:auto;
    box-shadow:0 10px 30px rgba(0,0,0,.5);
  }
  .suggest.show{ display:block; }
  .suggest-item{ padding:8px 10px; cursor:pointer; border-bottom:1px solid var(--border); }
  .suggest-item:last-child{ border-bottom:none; }
  .suggest-item:hover, .suggest-item.active{ background:#1b2027; }
  .suggest-item .s-t{ font-family:var(--mono); font-size:12px; word-break:break-all; }
  .suggest-item .s-v{ font-family:var(--mono); font-size:11px; color:var(--text-dim); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .payload-box{
    font-family:var(--mono); font-size:11.5px; color:var(--text-dim); background:#0d1014;
    border:1px solid var(--border); border-radius:6px; padding:8px 10px; max-height:90px; overflow:auto;
    white-space:pre-wrap; word-break:break-all; margin-bottom:10px;
  }
  .json-fields{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; max-height:120px; overflow-y:auto; }
  .json-field{
    font-family:var(--mono); font-size:11px; padding:4px 8px; border-radius:5px; cursor:pointer;
    border:1px solid var(--border); background:#1b2027; color:var(--text);
  }
  .json-field i{ color:var(--text-dim); font-style:normal; }
  .json-field:hover, .json-field.active{ border-color:var(--accent); }
  .icon-grid{ display:grid; grid-template-columns:repeat(auto-fill, minmax(46px, 1fr)); gap:6px; margin-bottom:6px; }
  .icon-opt{
    height:46px; border-radius:7px; border:1px solid var(--border); background:#1b2027; color:var(--text-dim);
    display:flex; align-items:center; justify-content:center; cursor:pointer; padding:0;
  }
  .icon-opt svg{ width:22px; height:22px; }
  .icon-opt:hover{ color:var(--text); border-color:#3a4250; }
  .icon-opt.active{ color:var(--accent); border-color:var(--accent); box-shadow:inset 0 0 0 1px var(--accent); }
  .icon-name{ font-family:var(--mono); font-size:11px; color:var(--text-dim); margin-bottom:14px; min-height:14px; }
  .thr-row{
    display:grid; grid-template-columns:minmax(0,1.6fr) minmax(0,.9fr) minmax(0,1.5fr) minmax(0,.9fr) auto;
    gap:6px; align-items:center; margin-bottom:6px;
  }
  .thr-row select, .thr-row input{ padding:8px 7px; font-size:12px; }
  #tMode{ width:auto; max-width:100%; min-width:0; flex:1 1 240px; }
  .thr-head{ font-size:10.5px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.4px; margin-bottom:4px; }
  .preview-wrap{ border:1px dashed var(--border); border-radius:10px; padding:12px; margin:6px 0 4px; }
  .preview-wrap .tile{ max-width:320px; margin:0 auto; }
  .sep{ border:none; border-top:1px solid var(--border); margin:16px 0; }

  .offline-note{ display:none; font-family:var(--mono); font-size:11.5px; color:var(--danger); }
  .offline-note.show{ display:inline; }

  /* ---------- Handy / iPhone ---------- */
  @media (max-width:760px){
    :root{ --gut-l:max(14px, env(safe-area-inset-left)); --gut-r:max(14px, env(safe-area-inset-right)); }
    header{ padding-top:max(12px, env(safe-area-inset-top)); padding-bottom:12px; gap:10px; }
    header{ flex-wrap:nowrap; }
    header h1{ font-size:16px; flex:1 1 auto; min-width:0; }
    .head-controls{ gap:8px; flex-shrink:0; }
    .head-controls .btn{ padding:9px 14px; }
    #tiles{ padding-top:14px; padding-bottom:20px; gap:12px; }
    .tile-head{ padding:11px 12px; gap:10px; }
    .tile-icon{ width:36px; height:36px; }
    .tile-icon svg{ width:21px; height:21px; }
    .tile-name{ font-size:14px; }
    .tile-body{ padding:12px; gap:10px; }
    .tile-topic{ display:none; }
    #settingsPanel{ padding-top:14px; }
    .settings-section{ padding:16px; }
    .form-grid{ grid-template-columns:1fr; }
    .form-grid.keep2{ grid-template-columns:repeat(2, minmax(0,1fr)); gap:4px 10px; }
    .tile-name{ white-space:normal; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; -webkit-hyphens:auto; hyphens:auto; overflow-wrap:break-word; line-height:1.2; }
    /* iOS zoomt bei Eingabefeldern < 16px automatisch hinein */
    input[type=text], input[type=number], input[type=password], input[type=search], select{ font-size:16px; }
    .thr-row{ grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto; padding:8px; border:1px solid var(--border); border-radius:8px; }
    .thr-row .thr-op{ grid-column:1/-1; }
    .thr-row .thr-text{ grid-column:1/-1; order:5; }
    .thr-row select, .thr-row input{ font-size:16px; }
    .thr-head{ display:none; }
    .modal{ padding:18px; }
    .manage-row{ flex-wrap:wrap; }
    .manage-actions{ width:100%; justify-content:flex-start; padding-left:42px; }
  }
  /* iPhone (hoch und quer): immer genau zwei Kacheln nebeneinander.
     iPad/Rechner: Anzahl richtet sich nach der Fensterbreite (auto-fill oben). */
  @media (max-width:600px), (max-height:500px) and (pointer:coarse){
    #tiles{ grid-template-columns:repeat(2, minmax(0, 1fr)); }
    .tile-value{ font-size:clamp(22px, 13cqi, 40px); }
  }
  @media (hover:none){ .btn-mini{ padding:8px 12px; font-size:12px; } }
</style>
</head>
<body>

<header>
  <h1 id="appTitle"><span id="titleA">MQTT</span> <span class="acc" id="titleB">Kacheln</span> <span class="ver-badge">v__APP_VERSION__</span></h1>
  <div class="head-controls" id="operatorControls">
    <span class="offline-note" id="offlineNote">Dashboard nicht erreichbar</span>
    <button class="btn" onclick="enterSettings()">&#9881; Einstellungen</button>
  </div>
  <div class="head-controls" id="settingsControls" style="display:none;">
    <button class="btn" onclick="exitSettings()">&larr; Zur Anzeige</button>
  </div>
</header>

<main id="tiles"></main>

<div id="settingsPanel" style="display:none;">

  <div class="settings-section">
    <h2>MQTT-Broker</h2>
    <div class="hint-text">Verbindung zum MQTT-Broker (z. B. Mosquitto). Nach dem Speichern werden alle Topics
      des Filters (Standard <b>#</b> = alle) mitgelesen und stehen bei den Kacheln zur Auswahl.</div>
    <div class="form-grid">
      <div class="field"><label class="lbl">Host / IP</label><input type="text" id="bHost" placeholder="192.168.1.10" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
      <div class="field"><label class="lbl">Port</label><input type="number" id="bPort" min="1" max="65535" inputmode="numeric"></div>
      <div class="field"><label class="lbl">Benutzer (optional)</label><input type="text" id="bUser" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
      <div class="field"><label class="lbl">Passwort (optional)</label><input type="password" id="bPass" autocomplete="new-password"></div>
      <div class="field"><label class="lbl">Topic-Filter für die Topic-Suche</label><input type="text" id="bFilter" autocapitalize="off" spellcheck="false"></div>
      <div class="field"><label class="lbl">Client-ID</label><input type="text" id="bClient" autocapitalize="off" spellcheck="false"></div>
      <div class="full">
        <div class="checkbox-row"><input type="checkbox" id="bTls"><label for="bTls">TLS verwenden (meist Port 8883)</label></div>
        <div class="checkbox-row"><input type="checkbox" id="bInsecure"><label for="bInsecure">TLS-Zertifikat nicht prüfen (selbst signiert)</label></div>
        <div class="checkbox-row" id="bPassClearRow" style="display:none;"><input type="checkbox" id="bPassClear"><label for="bPassClear">Gespeichertes Passwort löschen</label></div>
      </div>
    </div>
    <div class="actions-row">
      <button class="btn" onclick="saveBroker()">Speichern &amp; verbinden</button>
      <button class="btn btn-ghost" onclick="testBroker()">Verbindung testen</button>
      <span class="msg" id="brokerMsg"></span>
    </div>
    <div class="hint-text" style="margin:12px 0 0;">Status: <span id="brokerStatusLine" class="msg"></span></div>
  </div>

  <div class="settings-section">
    <h2>Kacheln</h2>
    <div class="hint-text">Jede Kachel zeigt den Wert eines Topics mit Einheit, Symbol und optionalen Schwellwert-Texten.
      Reihenfolge mit den Pfeilen ändern.</div>
    <button class="btn" onclick="openTileModal()">+ Kachel hinzufügen</button>
    <div id="tileManageList" style="margin-top:14px;"></div>
  </div>

  <div class="settings-section">
    <h2>Topic-Browser</h2>
    <div class="hint-text">Alle bisher empfangenen Topics. Mit <b>+ Kachel</b> direkt eine Kachel für das Topic anlegen.</div>
    <input type="search" id="browserSearch" placeholder="Topic oder Wert suchen ..." oninput="loadBrowser()" autocapitalize="off" spellcheck="false">
    <div class="hint-text" id="browserCount" style="margin:8px 0 0;"></div>
    <div class="topic-browser-list" id="browserList"></div>
  </div>

  <div class="settings-section">
    <h2>Webseite</h2>
    <div class="hint-text">Titel der Webseite und Port, unter dem sie erreichbar ist. Ein neuer Port gilt sofort und
      dauerhaft (wird in der Konfigurationsdatei gespeichert) – die Seite leitet automatisch weiter.</div>
    <div class="form-grid">
      <div class="field"><label class="lbl">Titel</label><input type="text" id="sTitle" maxlength="60"></div>
      <div class="field"><label class="lbl">Port der Webseite</label><input type="number" id="sPort" min="1" max="65535" inputmode="numeric"></div>
      <div class="full"><div class="checkbox-row"><input type="checkbox" id="sBrowser"><label for="sBrowser">Browser beim Programmstart automatisch öffnen (exe/App)</label></div></div>
    </div>
    <div class="actions-row">
      <button class="btn" id="serverSaveBtn" onclick="saveServer()">Speichern</button>
      <span class="msg" id="serverMsg"></span>
    </div>
    <label class="lbl" style="margin-top:16px;">Erreichbar unter</label>
    <div class="addr-list" id="addrList"></div>
  </div>

  <div class="settings-section">
    <h2>Info</h2>
    <div class="hint-text" style="margin-bottom:6px;">Version: <span class="msg" id="infoVersion"></span></div>
    <div class="hint-text">Konfigurationsdatei: <span class="msg" id="infoConfig" style="word-break:break-all;"></span></div>
    <button class="btn btn-danger" id="quitBtn" style="display:none;" onclick="quitApp()">Programm beenden</button>
  </div>
</div>

<!-- Kachel bearbeiten -->
<div class="modal-backdrop" id="tileModal">
  <div class="modal">
    <h2 id="tileModalTitle">Kachel</h2>
    <div class="form-grid">
      <div class="field full"><label class="lbl">Name</label><input type="text" id="tName" maxlength="60" placeholder="z. B. Waschmaschine"></div>
      <div class="field full topic-pick">
        <label class="lbl">MQTT-Topic</label>
        <input type="text" id="tTopic" placeholder="Topic suchen oder eingeben ..." autocomplete="off" autocapitalize="off" spellcheck="false">
        <div class="suggest" id="topicSuggest"></div>
      </div>
    </div>
    <label class="lbl">Aktueller Inhalt des Topics</label>
    <div class="payload-box" id="tPayload">-</div>
    <div id="jsonFieldWrap" style="display:none;">
      <label class="lbl">JSON-Feld wählen (Klick übernimmt)</label>
      <div class="json-fields" id="jsonFields"></div>
    </div>
    <div class="form-grid keep2">
      <div class="field"><label class="lbl">JSON-Feld (optional)</label><input type="text" id="tJson" placeholder="z. B. ENERGY.Power" autocapitalize="off" spellcheck="false"></div>
      <div class="field"><label class="lbl">Einheit</label><input type="text" id="tUnit" maxlength="20" list="unitList" placeholder="z. B. W"></div>
      <div class="field"><label class="lbl">Nachkommastellen</label>
        <select id="tDec"><option value="-1">automatisch</option><option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></div>
      <div class="field"><label class="lbl">Faktor (Umrechnung)</label><input type="text" id="tFactor" inputmode="decimal" placeholder="1"></div>
    </div>
    <datalist id="unitList">
      <option value="°C"><option value="%"><option value="W"><option value="kW"><option value="Wh"><option value="kWh">
      <option value="V"><option value="A"><option value="hPa"><option value="lx"><option value="ppm"><option value="l">
      <option value="m³"><option value="km/h"><option value="dBm"><option value="€"><option value="min"><option value="h">
    </datalist>

    <label class="lbl">Symbol</label>
    <div class="icon-grid" id="iconGrid"></div>
    <div class="icon-name" id="iconName"></div>

    <hr class="sep">
    <label class="lbl">Schwellwerte &amp; Texte</label>
    <div class="hint-text">Erreicht, überschreitet oder unterschreitet der Wert eine Schwelle, erscheint der Text auf der Kachel
      (Vergleich mit dem angezeigten Wert, also nach Faktor). Für Text-Werte (z. B. ON/OFF) &quot;ist gleich&quot; oder &quot;Text enthält&quot; nutzen.</div>
    <div id="thrList"></div>
    <div class="actions-row" style="margin-top:8px;">
      <button class="btn-mini" onclick="addThreshold()">+ Schwellwert</button>
      <select id="tMode" style="width:auto; flex:0 1 auto;">
        <option value="alle">Alle Treffer anzeigen</option>
        <option value="erster">Nur ersten Treffer anzeigen</option>
      </select>
    </div>

    <hr class="sep">
    <label class="lbl">Vorschau</label>
    <div class="preview-wrap" id="previewWrap"></div>

    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeTileModal()">Abbrechen</button>
      <button class="btn" onclick="saveTile()">Speichern</button>
    </div>
    <div class="msg err" id="tileMsg" style="text-align:right; margin-top:8px;"></div>
  </div>
</div>

<!-- Bestaetigung -->
<div class="modal-backdrop" id="confirmModal">
  <div class="modal small">
    <h2 id="confirmTitle">Bestätigen</h2>
    <div class="hint-text" id="confirmText" style="font-size:13px; color:var(--text);"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="confirmNo">Abbrechen</button>
      <button class="btn" id="confirmYes">OK</button>
    </div>
  </div>
</div>

<script>
let CFG = null;            // /api/config (Symbole, Farben, Vergleiche, Kacheln ...)
let STATE = null;          // /api/state
let STATE_AT = 0;
let settingsMode = false;
let editTile = null;       // Kachel im Modal
let previewTimer = null;
let suggestIdx = -1;

function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function iconSvg(key){
  const list = (CFG && CFG.symbole) || [];
  const it = list.find(i => i.key === key) || list.find(i => i.key === 'info');
  return '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">' + (it ? it.svg : '') + '</svg>';
}
function lsGet(k, d){ try{ const v = localStorage.getItem(k); return v == null ? d : v; }catch(e){ return d; } }
function lsSet(k, v){ try{ localStorage.setItem(k, v); }catch(e){} }

async function api(path, body){
  const opt = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const r = await fetch(path, opt);
  let j = null;
  try{ j = await r.json(); }catch(e){ j = {ok:false, fehler:'Ungültige Antwort ('+r.status+')'}; }
  return j;
}

/* ---------- Titel ---------- */
function setTitle(t){
  t = (t || 'MQTT Kacheln').trim();
  document.title = t;
  const parts = t.split(/\s+/);
  const a = parts.length > 1 ? parts.slice(0, -1).join(' ') : '';
  const b = parts[parts.length - 1];
  document.getElementById('titleA').textContent = a;
  document.getElementById('titleB').textContent = b;
}

/* ---------- Kachel-HTML ---------- */
function tileHtml(t, nowServer){
  const col = t.farbe;
  const styleTile = col ? ` style="border-color:${col}99; box-shadow:0 0 0 1px ${col}33, 0 0 18px ${col}14;"` : '';
  const styleIcon = col ? ` style="color:${col}; border-color:${col}88;"` : '';
  let valueHtml;
  if(t.fehler){
    valueHtml = `<div class="tile-value err">${esc(t.fehler)}</div>`;
  }else if(!t.hat_wert){
    valueHtml = `<div class="tile-value nodata">Noch kein Wert empfangen</div>`;
  }else{
    const vstyle = col ? ` style="color:${col}"` : '';
    valueHtml = `<div class="tile-value"${vstyle}>${esc(t.wert)}${t.einheit ? `<span class="tile-unit">${esc(t.einheit)}</span>` : ''}</div>`;
  }
  const chips = (t.treffer || []).filter(m => m.text).map(m =>
    `<span class="chip" style="color:${m.farbe}" title="${esc(m.text)}">${esc(m.text)}</span>`).join('');
  return `<div class="tile"${styleTile} data-id="${esc(t.id)}">
    <div class="tile-head">
      <div class="tile-icon"${styleIcon}>${iconSvg(t.symbol)}</div>
      <div class="tile-titles"><div class="tile-name" title="${esc(t.name)}">${esc(t.name)}</div>
        <div class="tile-topic" title="${esc(t.topic)}">${esc(t.topic || '-')}</div></div>
    </div>
    <div class="tile-body">${valueHtml}${chips ? `<div class="tile-chips">${chips}</div>` : ''}</div>
  </div>`;
}

function renderTiles(){
  const main = document.getElementById('tiles');
  if(!STATE) return;
  const nowServer = STATE.jetzt + (Date.now() - STATE_AT) / 1000;
  if(!STATE.kacheln.length){
    const noBroker = !STATE.broker.eingerichtet;
    main.innerHTML = `<div class="empty-state"><h2>Noch keine Kacheln</h2>
      <div>${noBroker ? 'Zuerst unter Einstellungen den MQTT-Broker eintragen, danach Topics als Kacheln anlegen.' : 'Unter Einstellungen Topics auswählen und als Kacheln anlegen.'}</div>
      <button class="btn" onclick="enterSettings()">&#9881; Einstellungen öffnen</button></div>`;
    return;
  }
  main.innerHTML = STATE.kacheln.map(t => tileHtml(t, nowServer)).join('');
}

function renderBroker(){
  if(!STATE) return;
  const b = STATE.broker;
  const line = document.getElementById('brokerStatusLine');
  line.textContent = b.status;
  line.className = 'msg ' + (b.verbunden ? 'ok' : (b.eingerichtet ? 'err' : ''));
}

async function refresh(){
  if(document.hidden) return;
  try{
    const s = await fetch('/api/state', {cache:'no-store'}).then(r => r.json());
    STATE = s; STATE_AT = Date.now();
    document.getElementById('offlineNote').classList.remove('show');
    setTitle(s.titel);
    renderBroker();
    if(!settingsMode) renderTiles();
  }catch(e){
    document.getElementById('offlineNote').classList.add('show');
  }
}

/* ---------- Einstellungen ---------- */
async function loadConfig(){
  CFG = await api('/api/config');
  return CFG;
}

async function enterSettings(){
  settingsMode = true;
  document.getElementById('tiles').style.display = 'none';
  document.getElementById('settingsPanel').style.display = '';
  document.getElementById('operatorControls').style.display = 'none';
  document.getElementById('settingsControls').style.display = 'flex';
  window.scrollTo(0, 0);
  await loadConfig();
  fillSettings();
  loadBrowser();
}
function exitSettings(){
  settingsMode = false;
  document.getElementById('tiles').style.display = '';
  document.getElementById('settingsPanel').style.display = 'none';
  document.getElementById('operatorControls').style.display = 'flex';
  document.getElementById('settingsControls').style.display = 'none';
  window.scrollTo(0, 0);
  refresh();
}

function fillSettings(){
  const b = CFG.broker, s = CFG.server;
  document.getElementById('bHost').value = b.host;
  document.getElementById('bPort').value = b.port;
  document.getElementById('bUser').value = b.benutzer;
  document.getElementById('bPass').value = '';
  document.getElementById('bPass').placeholder = b.passwort_gesetzt ? '(gespeichert - leer lassen = unverändert)' : '';
  document.getElementById('bPassClearRow').style.display = b.passwort_gesetzt ? 'flex' : 'none';
  document.getElementById('bPassClear').checked = false;
  document.getElementById('bFilter').value = b.topic_filter;
  document.getElementById('bClient').value = b.client_id;
  document.getElementById('bTls').checked = b.tls;
  document.getElementById('bInsecure').checked = b.tls_zertifikat_nicht_pruefen;
  document.getElementById('sTitle').value = s.titel;
  document.getElementById('sPort').value = CFG.aktiver_port;
  document.getElementById('sBrowser').checked = s.browser_oeffnen;
  document.getElementById('addrList').innerHTML = CFG.adressen.map(a => `<a href="${esc(a)}">${esc(a)}</a>`).join('');
  document.getElementById('infoVersion').textContent = 'v' + CFG.version;
  document.getElementById('infoConfig').textContent = CFG.config_pfad;
  document.getElementById('quitBtn').style.display = CFG.beenden_moeglich ? '' : 'none';
  renderManageList();
}

function renderManageList(){
  const el = document.getElementById('tileManageList');
  const tiles = CFG.kacheln;
  if(!tiles.length){ el.innerHTML = '<div class="t-empty">Noch keine Kacheln angelegt.</div>'; return; }
  el.innerHTML = tiles.map((t, i) => `<div class="manage-row">
      <div class="manage-icon">${iconSvg(t.symbol)}</div>
      <div class="manage-info">${esc(t.name)}<div class="manage-sub">${esc(t.topic || '(kein Topic)')}${t.json_feld ? ' &rarr; ' + esc(t.json_feld) : ''}${t.einheit ? ' &middot; ' + esc(t.einheit) : ''}${t.schwellwerte.length ? ' &middot; ' + t.schwellwerte.length + ' Schwellwert(e)' : ''}</div></div>
      <div class="manage-actions">
        <button class="btn-mini" onclick="moveTile(${i},-1)" ${i === 0 ? 'disabled' : ''} title="nach oben">&uarr;</button>
        <button class="btn-mini" onclick="moveTile(${i},1)" ${i === tiles.length - 1 ? 'disabled' : ''} title="nach unten">&darr;</button>
        <button class="btn-mini" onclick="openTileModal('${esc(t.id)}')">Bearbeiten</button>
        <button class="btn-mini btn-delete" onclick="deleteTile('${esc(t.id)}')">Löschen</button>
      </div></div>`).join('');
}

async function moveTile(i, d){
  const ids = CFG.kacheln.map(t => t.id);
  const j = i + d;
  if(j < 0 || j >= ids.length) return;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  await api('/api/tiles/order', {ids});
  await loadConfig(); renderManageList();
}

async function deleteTile(id){
  const t = CFG.kacheln.find(x => x.id === id);
  if(!await confirmDialog('Kachel löschen', `Kachel "${t ? t.name : ''}" wirklich löschen?`, 'Löschen')) return;
  await api('/api/tiles/delete', {id});
  await loadConfig(); renderManageList();
}

function brokerInput(){
  return {
    host: document.getElementById('bHost').value.trim(),
    port: document.getElementById('bPort').value,
    benutzer: document.getElementById('bUser').value,
    passwort: document.getElementById('bPass').value,
    passwort_loeschen: document.getElementById('bPassClear').checked,
    topic_filter: document.getElementById('bFilter').value.trim() || '#',
    client_id: document.getElementById('bClient').value.trim(),
    tls: document.getElementById('bTls').checked,
    tls_zertifikat_nicht_pruefen: document.getElementById('bInsecure').checked,
  };
}
function setMsg(id, text, ok){
  const el = document.getElementById(id);
  el.textContent = text || '';
  el.className = 'msg ' + (ok ? 'ok' : 'err');
}
async function saveBroker(){
  const r = await api('/api/broker', brokerInput());
  if(r.ok){ setMsg('brokerMsg', 'Gespeichert - verbinde ...', true); await loadConfig(); fillSettings(); setTimeout(loadBrowser, 2500); }
  else setMsg('brokerMsg', r.fehler, false);
}
async function testBroker(){
  setMsg('brokerMsg', 'Teste ...', true);
  const r = await api('/api/broker/test', brokerInput());
  setMsg('brokerMsg', r.meldung || r.fehler, r.ok);
}

async function saveServer(){
  const newPort = parseInt(document.getElementById('sPort').value, 10);
  const body = {titel: document.getElementById('sTitle').value.trim(), browser_oeffnen: document.getElementById('sBrowser').checked};
  const portChanged = newPort && newPort !== CFG.aktiver_port;
  if(portChanged){
    if(!await confirmDialog('Port ändern', `Die Webseite zieht auf Port ${newPort} um. Lesezeichen/Homebildschirm-Verknüpfungen müssen danach angepasst werden.`, 'Port ändern')) return;
    body.port = newPort;
  }
  const r = await api('/api/server', body);
  if(!r.ok){ setMsg('serverMsg', r.fehler, false); return; }
  if(portChanged){
    setMsg('serverMsg', `Port ${newPort} aktiv - Weiterleitung ...`, true);
    const url = `${location.protocol}//${location.hostname}:${newPort}${location.pathname}`;
    setTimeout(() => { location.href = url; }, 1200);
    return;
  }
  setMsg('serverMsg', 'Gespeichert', true);
  refresh();
}

async function quitApp(){
  if(!await confirmDialog('Programm beenden', 'Das Dashboard-Programm wird beendet. Die Webseite ist danach nicht mehr erreichbar.', 'Beenden')) return;
  await api('/api/quit', {});
  document.body.innerHTML = '<div class="empty-state" style="padding-top:120px;"><h2>Programm beendet</h2><div>Dieses Fenster kann geschlossen werden.</div></div>';
}

/* ---------- Topic-Browser ---------- */
let browserTimer = null;
function loadBrowser(){
  clearTimeout(browserTimer);
  browserTimer = setTimeout(async () => {
    const q = document.getElementById('browserSearch').value;
    const r = await fetch('/api/topics?limit=300&q=' + encodeURIComponent(q)).then(r => r.json());
    document.getElementById('browserCount').textContent =
      `${r.gesamt} Topics empfangen` + (q ? `, ${r.gefunden} passend` : '') + (r.gefunden > r.topics.length ? ` (erste ${r.topics.length} angezeigt)` : '') + (r.verbunden ? '' : ' - Broker nicht verbunden');
    const el = document.getElementById('browserList');
    if(!r.topics.length){ el.innerHTML = `<div class="t-empty">${r.gesamt ? 'Keine Treffer.' : 'Noch keine Topics empfangen.'}</div>`; return; }
    el.innerHTML = r.topics.map(t => `<div class="topic-row">
        <div class="t-info"><div class="t-name">${esc(t.topic)}</div><div class="t-val">${esc(t.wert)}</div></div>
        <button class="btn-mini" data-topic="${esc(t.topic)}" onclick="openTileModal(null, this.dataset.topic)">+ Kachel</button></div>`).join('');
  }, 200);
}

/* ---------- Kachel-Modal ---------- */
function blankTile(){
  return {id:'', name:'', topic:'', json_feld:'', einheit:'', nachkommastellen:-1, faktor:1, symbol:'info', treffer_modus:'alle', schwellwerte:[]};
}
async function openTileModal(id, topic){
  if(!CFG) await loadConfig();
  const src = id ? CFG.kacheln.find(t => t.id === id) : null;
  editTile = JSON.parse(JSON.stringify(src || blankTile()));
  if(topic){
    editTile.topic = topic;
    if(!editTile.name){ const p = topic.split('/').filter(Boolean); editTile.name = p.slice(-2).join(' ').slice(0, 60); }
  }
  document.getElementById('tileModalTitle').textContent = src ? 'Kachel bearbeiten' : 'Neue Kachel';
  document.getElementById('tName').value = editTile.name;
  document.getElementById('tTopic').value = editTile.topic;
  document.getElementById('tJson').value = editTile.json_feld;
  document.getElementById('tUnit').value = editTile.einheit;
  document.getElementById('tDec').value = String(editTile.nachkommastellen);
  document.getElementById('tFactor').value = String(editTile.faktor).replace('.', ',');
  document.getElementById('tMode').value = editTile.treffer_modus;
  document.getElementById('tileMsg').textContent = '';
  renderIconGrid();
  renderThresholds();
  document.getElementById('tileModal').classList.add('show');
  loadTopicDetail();
  schedulePreview();
  clearInterval(previewTimer);
  previewTimer = setInterval(() => { loadTopicDetail(true); schedulePreview(); }, 3000);
}
function closeTileModal(){
  document.getElementById('tileModal').classList.remove('show');
  clearInterval(previewTimer);
  hideSuggest();
}
function readTileForm(){
  editTile.name = document.getElementById('tName').value.trim();
  editTile.topic = document.getElementById('tTopic').value.trim();
  editTile.json_feld = document.getElementById('tJson').value.trim();
  editTile.einheit = document.getElementById('tUnit').value.trim();
  editTile.nachkommastellen = parseInt(document.getElementById('tDec').value, 10);
  editTile.faktor = document.getElementById('tFactor').value.trim() || '1';
  editTile.treffer_modus = document.getElementById('tMode').value;
  editTile.schwellwerte = Array.from(document.querySelectorAll('#thrList .thr-row:not(.thr-head)')).map(r => ({
    vergleich: r.querySelector('.thr-op').value,
    wert: r.querySelector('.thr-val').value,
    text: r.querySelector('.thr-text').value,
    farbe: r.querySelector('.thr-col').value,
  }));
  return editTile;
}
async function saveTile(){
  const t = readTileForm();
  if(!t.topic){ document.getElementById('tileMsg').textContent = 'Bitte ein Topic wählen.'; return; }
  if(!t.name){ document.getElementById('tileMsg').textContent = 'Bitte einen Namen eingeben.'; return; }
  const r = await api('/api/tiles', t);
  if(!r.ok){ document.getElementById('tileMsg').textContent = r.fehler || 'Fehler'; return; }
  closeTileModal();
  await loadConfig();
  if(settingsMode) renderManageList();
  refresh();
}

function renderIconGrid(){
  document.getElementById('iconGrid').innerHTML = CFG.symbole.map(s =>
    `<button type="button" class="icon-opt ${s.key === editTile.symbol ? 'active' : ''}" title="${esc(s.name)}" data-key="${s.key}" onclick="pickIcon('${s.key}')">
      <svg class="ico" viewBox="0 0 24 24">${s.svg}</svg></button>`).join('');
  const cur = CFG.symbole.find(s => s.key === editTile.symbol);
  document.getElementById('iconName').textContent = cur ? cur.name : '';
}
function pickIcon(k){
  readTileForm();
  editTile.symbol = k;
  renderIconGrid();
  schedulePreview();
}

function thrRowHtml(s){
  const ops = CFG.vergleiche.map(v => `<option value="${v.key}" ${v.key === s.vergleich ? 'selected' : ''}>${esc(v.name)}</option>`).join('');
  const cols = CFG.farben.map(f => `<option value="${f.key}" ${f.key === s.farbe ? 'selected' : ''}>${esc(f.name)}</option>`).join('');
  return `<div class="thr-row">
    <select class="thr-op" onchange="schedulePreview()">${ops}</select>
    <input type="text" class="thr-val" value="${esc(s.wert)}" placeholder="Wert" oninput="schedulePreview()" autocapitalize="off">
    <input type="text" class="thr-text" value="${esc(s.text)}" placeholder="Text, z. B. Läuft" maxlength="80" oninput="schedulePreview()">
    <select class="thr-col" onchange="schedulePreview()">${cols}</select>
    <button type="button" class="btn-mini btn-delete" onclick="removeThreshold(this)" title="entfernen">&#10005;</button>
  </div>`;
}
function renderThresholds(){
  const head = editTile.schwellwerte.length ? '<div class="thr-row thr-head"><span>Bedingung</span><span>Wert</span><span>Text auf der Kachel</span><span>Farbe</span><span></span></div>' : '';
  document.getElementById('thrList').innerHTML = head + editTile.schwellwerte.map(thrRowHtml).join('');
}
function removeThreshold(btn){
  btn.parentElement.remove();
  readTileForm();
  renderThresholds();
  schedulePreview();
}
function addThreshold(){
  readTileForm();
  editTile.schwellwerte.push({vergleich:'>=', wert:'', text:'', farbe: editTile.schwellwerte.length ? 'orange' : 'gruen'});
  renderThresholds();
  const rows = document.querySelectorAll('#thrList .thr-row:not(.thr-head)');
  rows[rows.length - 1].querySelector('.thr-val').focus();
}

let pvTimer = null;
function schedulePreview(){
  clearTimeout(pvTimer);
  pvTimer = setTimeout(async () => {
    if(!document.getElementById('tileModal').classList.contains('show')) return;
    const t = readTileForm();
    const r = await api('/api/preview', Object.assign({}, t, {name: t.name || 'Vorschau'}));
    if(r && r.id !== undefined){
      const now = (STATE ? STATE.jetzt + (Date.now() - STATE_AT) / 1000 : Date.now() / 1000);
      document.getElementById('previewWrap').innerHTML = tileHtml(r, now);
    }
  }, 250);
}

let lastDetailTopic = null;
async function loadTopicDetail(silent){
  const topic = document.getElementById('tTopic').value.trim();
  const box = document.getElementById('tPayload');
  const fw = document.getElementById('jsonFieldWrap');
  if(!topic){ box.textContent = '-'; fw.style.display = 'none'; lastDetailTopic = null; return; }
  const r = await fetch('/api/topic?t=' + encodeURIComponent(topic)).then(r => r.json());
  if(!r.vorhanden){ box.textContent = 'Für dieses Topic wurde noch nichts empfangen.'; fw.style.display = 'none'; return; }
  box.textContent = r.wert;
  if(silent && lastDetailTopic === topic) return;
  lastDetailTopic = topic;
  if(r.felder && r.felder.length){
    fw.style.display = '';
    const cur = document.getElementById('tJson').value.trim();
    document.getElementById('jsonFields').innerHTML = r.felder.map(f =>
      `<span class="json-field ${f.pfad === cur ? 'active' : ''}" data-p="${esc(f.pfad)}" onclick="pickJsonField(this.dataset.p)">${esc(f.pfad)} <i>${esc(f.wert)}</i></span>`).join('');
  }else{
    fw.style.display = 'none';
  }
}
function pickJsonField(p){
  document.getElementById('tJson').value = p;
  document.querySelectorAll('.json-field').forEach(el => el.classList.toggle('active', el.dataset.p === p));
  schedulePreview();
}

/* Topic-Vorschlagsliste */
let sgTimer = null;
function hideSuggest(){ document.getElementById('topicSuggest').classList.remove('show'); suggestIdx = -1; }
function updateSuggest(){
  clearTimeout(sgTimer);
  sgTimer = setTimeout(async () => {
    const q = document.getElementById('tTopic').value.trim();
    const r = await fetch('/api/topics?limit=60&q=' + encodeURIComponent(q)).then(r => r.json());
    const el = document.getElementById('topicSuggest');
    if(!r.topics.length){
      el.innerHTML = `<div class="t-empty">${r.gesamt ? 'Kein passendes Topic - Eingabe wird übernommen.' : (r.verbunden ? 'Noch keine Topics empfangen.' : 'Broker nicht verbunden - Topic kann trotzdem eingegeben werden.')}</div>`;
    }else{
      el.innerHTML = r.topics.map(t => `<div class="suggest-item" data-topic="${esc(t.topic)}" onmousedown="event.preventDefault(); chooseTopic(this.dataset.topic)">
        <div class="s-t">${esc(t.topic)}</div><div class="s-v">${esc(t.wert)}</div></div>`).join('');
    }
    suggestIdx = -1;
    el.classList.add('show');
  }, 150);
}
function chooseTopic(t){
  document.getElementById('tTopic').value = t;
  hideSuggest();
  const nameEl = document.getElementById('tName');
  if(!nameEl.value.trim()){ const p = t.split('/').filter(Boolean); nameEl.value = p.slice(-2).join(' ').slice(0, 60); }
  document.getElementById('tJson').value = '';
  lastDetailTopic = null;
  loadTopicDetail();
  schedulePreview();
}

/* ---------- Bestaetigungsdialog ---------- */
function confirmDialog(title, text, yesText){
  return new Promise(resolve => {
    const m = document.getElementById('confirmModal');
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmText').textContent = text;
    const yes = document.getElementById('confirmYes'), no = document.getElementById('confirmNo');
    yes.textContent = yesText || 'OK';
    const done = v => { m.classList.remove('show'); yes.onclick = no.onclick = null; resolve(v); };
    yes.onclick = () => done(true);
    no.onclick = () => done(false);
    m.classList.add('show');
  });
}

/* ---------- Start ---------- */
document.addEventListener('DOMContentLoaded', () => {
  const tt = document.getElementById('tTopic');
  tt.addEventListener('focus', updateSuggest);
  tt.addEventListener('input', () => { updateSuggest(); schedulePreview(); });
  tt.addEventListener('blur', () => setTimeout(() => { hideSuggest(); loadTopicDetail(); }, 150));
  tt.addEventListener('keydown', e => {
    const items = document.querySelectorAll('#topicSuggest .suggest-item');
    if(e.key === 'ArrowDown' || e.key === 'ArrowUp'){
      if(!items.length) return;
      e.preventDefault();
      suggestIdx = (suggestIdx + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items.forEach((it, i) => it.classList.toggle('active', i === suggestIdx));
      items[suggestIdx].scrollIntoView({block:'nearest'});
    }else if(e.key === 'Enter'){
      if(suggestIdx >= 0 && items[suggestIdx]){ e.preventDefault(); chooseTopic(items[suggestIdx].dataset.topic); }
      else { hideSuggest(); loadTopicDetail(); schedulePreview(); }
    }else if(e.key === 'Escape'){ hideSuggest(); }
  });
  ['tName','tJson','tUnit','tFactor'].forEach(id => document.getElementById(id).addEventListener('input', schedulePreview));
  ['tDec','tMode'].forEach(id => document.getElementById(id).addEventListener('change', schedulePreview));
  document.getElementById('tJson').addEventListener('input', () =>
    document.querySelectorAll('.json-field').forEach(el => el.classList.toggle('active', el.dataset.p === document.getElementById('tJson').value.trim())));
  document.addEventListener('keydown', e => {
    if(e.key === 'Escape' && document.getElementById('tileModal').classList.contains('show') && !document.getElementById('topicSuggest').classList.contains('show')) closeTileModal();
  });
  document.addEventListener('visibilitychange', () => { if(!document.hidden) refresh(); });
});

(async function init(){
  try{ await loadConfig(); }catch(e){}
  await refresh();
  setInterval(refresh, 1500);
})();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------
# Start
# ----------------------------------------------------------------------
def main():
    global APPLE_ICON_PNG
    APPLE_ICON_PNG = _load_png()
    try:
        sys.stdout.reconfigure(line_buffering=True)   # Log sofort sichtbar (z. B. logread)
    except Exception:
        pass
    print("=" * 60)
    print(" %s  v%s" % (APP_NAME, APP_VERSION))
    print(" Konfiguration: %s" % CONFIG_PATH)
    print("=" * 60)
    app = App()
    port = app.store.cfg["server"]["port"]
    try:
        srv = app.make_server(port)
    except OSError as e:
        print("[Server] Port %d ist belegt (%s) - versuche einen freien Port ..." % (port, e))
        srv = None
        for alt in list(range(port + 1, port + 20)) + [0]:
            try:
                srv = app.make_server(alt)
                break
            except OSError:
                continue
        if srv is None:
            print("[Server] Kein freier Port gefunden - Abbruch.")
            sys.exit(1)
        port = srv.server_address[1]
        print("[Server] Ausweich-Port %d wird genutzt (gespeicherter Port bleibt %d)." %
              (port, app.store.cfg["server"]["port"]))
    app.server = srv
    app.start_server(srv)
    app.mqtt.start()
    for ip in local_ips():
        print("[Server] Webseite: http://%s:%d" % (ip, port))
    if getattr(sys, "frozen", False) and app.store.cfg["server"].get("browser_oeffnen", True):
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open("http://127.0.0.1:%d/" % port)),
                         daemon=True).start()
    try:
        while not app.quit_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    print("[Server] Wird beendet ...")
    app.mqtt.stop()
    try:
        app.server.shutdown()
    except Exception:
        pass


if __name__ == "__main__":
    main()
