#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baut das OFFLINE-Installationspaket fuer einen GL.iNet Brume 2 (GL-MT2500).

Das Paket enthaelt:
  - app.py (das Dashboard)
  - install.sh / uninstall.sh
  - alle Python3-Pakete (.ipk) inkl. Abhaengigkeiten fuer OpenWrt,
    damit der Brume 2 KEIN Internet fuer die Installation braucht.

Laeuft automatisch in GitHub Actions (siehe .github/workflows/build.yml),
kann aber auch auf jedem eigenen PC mit Internet und Python 3 gestartet werden:

    python3 brume2/build_offline_paket.py

Optionen:
    --release 21.02.7          OpenWrt-Version (Brume 2 / GL-Firmware 4.x = 21.02)
    --arch aarch64_cortex-a53  Paket-Architektur (Brume 2 = MediaTek MT7981)
    --pakete python3           zu installierende Pakete (mit Abhaengigkeiten)
    --ohne-python              nur app.py + Skripte (falls Python3 schon drauf ist)
    --out dist                 Ausgabeordner

Benoetigt nur die Python-Standardbibliothek.
"""

import argparse
import gzip
import hashlib
import os
import re
import shutil
import sys
import tarfile
import time
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
PROJEKT = os.path.dirname(HIER)

BASIS_URL = "https://downloads.openwrt.org/releases/{release}/packages/{arch}/{feed}"
FEEDS = ["base", "packages"]

# Diese Pakete sind auf jedem OpenWrt-/GL.iNet-System bereits Teil der
# Firmware und duerfen NICHT mit einer evtl. abweichenden Version
# ueberschrieben werden.
AUSSCHLUSS = {
    "libc", "libgcc", "libgcc1", "libpthread", "librt", "libatomic", "libatomic1",
    "kernel", "busybox", "base-files", "libubox", "libuci", "ubus", "procd",
}


def laden(url, versuche=4):
    letzter = None
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mqtt-kachel-dashboard-builder"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            letzter = e
            time.sleep(3 * (i + 1))
    raise RuntimeError("Download fehlgeschlagen: %s (%s)" % (url, letzter))


def packages_lesen(daten, feed_url):
    pakete = {}
    for block in daten.decode("utf-8", "replace").split("\n\n"):
        felder = {}
        letzter_key = None
        for zeile in block.splitlines():
            if zeile.startswith(" ") and letzter_key:
                felder[letzter_key] += " " + zeile.strip()
                continue
            if ":" in zeile:
                k, v = zeile.split(":", 1)
                felder[k.strip()] = v.strip()
                letzter_key = k.strip()
        if "Package" in felder and "Filename" in felder:
            felder["_url"] = feed_url + "/" + felder["Filename"]
            pakete.setdefault(felder["Package"], felder)
    return pakete


def abhaengigkeiten(pkg):
    deps = []
    for teil in (pkg.get("Depends") or "").split(","):
        teil = teil.strip()
        if not teil:
            continue
        alternativen = [re.sub(r"\(.*?\)", "", a).strip() for a in teil.split("|")]
        deps.append([a for a in alternativen if a])
    return deps


def aufloesen(wunsch, index, provides):
    ergebnis = {}
    offen = list(wunsch)
    fehlend = []
    while offen:
        name = offen.pop(0)
        if name in AUSSCHLUSS or name.startswith("kmod-"):
            continue
        pkg = index.get(name)
        if pkg is None and name in provides:
            pkg = provides[name]
        if pkg is None:
            fehlend.append(name)
            continue
        if pkg["Package"] in ergebnis:
            continue
        ergebnis[pkg["Package"]] = pkg
        for alternativen in abhaengigkeiten(pkg):
            gewaehlt = None
            for a in alternativen:
                if a in AUSSCHLUSS or a.startswith("kmod-") or a in index or a in provides:
                    gewaehlt = a
                    break
            if gewaehlt is None:
                fehlend.append("|".join(alternativen))
            else:
                offen.append(gewaehlt)
    return ergebnis, fehlend


def app_version():
    with open(os.path.join(PROJEKT, "app.py"), encoding="utf-8") as f:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', f.read())
    return m.group(1) if m else "0.0.0"


def main():
    ap = argparse.ArgumentParser(description="Offline-Paket fuer GL.iNet Brume 2 bauen")
    ap.add_argument("--release", default="21.02.7")
    ap.add_argument("--arch", default="aarch64_cortex-a53")
    ap.add_argument("--pakete", default="python3", help="Kommagetrennt, z. B. python3")
    ap.add_argument("--ohne-python", action="store_true")
    ap.add_argument("--out", default=os.path.join(PROJEKT, "dist"))
    args = ap.parse_args()

    version = app_version()
    ordner_name = "MQTT-Kachel-Dashboard-brume2"
    arbeit = os.path.join(args.out, "_brume2_build")
    stage = os.path.join(arbeit, ordner_name)
    shutil.rmtree(arbeit, ignore_errors=True)
    os.makedirs(os.path.join(stage, "ipk"))

    print("== Offline-Paket fuer Brume 2 - Dashboard v%s" % version)

    if not args.ohne_python:
        index, provides = {}, {}
        for feed in FEEDS:
            feed_url = BASIS_URL.format(release=args.release, arch=args.arch, feed=feed)
            print("-- Lade Paketliste: %s" % feed_url)
            roh = gzip.decompress(laden(feed_url + "/Packages.gz"))
            pk = packages_lesen(roh, feed_url)
            print("   %d Pakete" % len(pk))
            for name, p in pk.items():
                index.setdefault(name, p)
                for prov in (p.get("Provides") or "").split(","):
                    prov = re.sub(r"\(.*?\)", "", prov).strip()
                    if prov:
                        provides.setdefault(prov, p)
        wunsch = [p.strip() for p in args.pakete.split(",") if p.strip()]
        auswahl, fehlend = aufloesen(wunsch, index, provides)
        if fehlend:
            print("!! Nicht im Feed gefunden (vermutlich Teil der Firmware): %s" % ", ".join(sorted(set(fehlend))))
        if not auswahl:
            print("!! Keine Pakete gefunden - Abbruch")
            sys.exit(1)
        gesamt = 0
        liste = []
        for name in sorted(auswahl):
            p = auswahl[name]
            datei = os.path.basename(p["Filename"])
            print("-- %-40s %s" % (name, p.get("Version", "")))
            daten = laden(p["_url"])
            if p.get("SHA256sum") and hashlib.sha256(daten).hexdigest() != p["SHA256sum"]:
                print("!! Pruefsumme falsch: %s" % datei)
                sys.exit(1)
            with open(os.path.join(stage, "ipk", datei), "wb") as f:
                f.write(daten)
            gesamt += len(daten)
            liste.append("%s %s %s" % (name, p.get("Version", ""), datei))
        with open(os.path.join(stage, "ipk", "pakete.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(liste) + "\n")
        print("== %d Pakete, %.1f MB" % (len(auswahl), gesamt / 1048576.0))
    with open(os.path.join(stage, "ipk", "ziel.txt"), "w", encoding="utf-8") as f:
        f.write("release=%s\narch=%s\nversion=%s\n" % (args.release, args.arch, version))

    shutil.copy2(os.path.join(PROJEKT, "app.py"), os.path.join(stage, "app.py"))
    for name in ("install.sh", "uninstall.sh", "LIESMICH-BRUME2.txt"):
        shutil.copy2(os.path.join(HIER, name), os.path.join(stage, name))

    os.makedirs(args.out, exist_ok=True)
    ziel = os.path.join(args.out, "MQTT-Kachel-Dashboard-v%s-brume2-offline.tar.gz" % version)

    def filt(ti):
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = "root"
        if ti.isdir() or ti.name.endswith(".sh") or ti.name.endswith("app.py"):
            ti.mode = 0o755
        else:
            ti.mode = 0o644
        return ti

    with tarfile.open(ziel, "w:gz") as tar:
        tar.add(stage, arcname=ordner_name, filter=filt)
    shutil.rmtree(arbeit, ignore_errors=True)
    print("== Fertig: %s (%.1f MB)" % (ziel, os.path.getsize(ziel) / 1048576.0))


if __name__ == "__main__":
    main()
