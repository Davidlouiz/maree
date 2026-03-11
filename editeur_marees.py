#!/usr/bin/env python3
"""
Éditeur interactif de ports de marée.

Serveur HTTP qui :
  1. Génère et sert la page éditeur (même présentation que carte_marees.html)
  2. Sert les fichiers .har statiques
  3. Expose une API POST /api/create_har pour générer un nouveau fichier .har
  4. Expose une API POST /api/delete_har pour supprimer un fichier .har

Les ports dont le fichier est préfixé « - » sont affichés en bleu (nouveaux).

Usage:
    python editeur_marees.py [--har-dir har_ports] [--port 8000]
"""

import argparse
import html
import json
import re
import sys
import traceback
import unicodedata
from datetime import datetime
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

# Réutilise les fonctions de carte_marees.py et genere_har.py
from carte_marees import (
    export_mappings_json,
    export_utide_json,
    extract_har_metadata,
    scan_har_files,
)
from genere_har import extract_constituents, find_best_atlas, move_grid_point, write_har
from genere_tous_ports import (
    PORTS as ALL_PORTS,
    fetch_maree_info,
    fetch_maree_info_courbe,
)


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────────


def safe_filename(nom: str) -> str:
    """Transforme un nom en nom de fichier sûr (sans accents, espaces → tirets)."""
    # Décomposition Unicode, suppression des accents
    nfkd = unicodedata.normalize("NFKD", nom)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    # Remplacements
    ascii_name = ascii_name.replace(" ", "-").replace("'", "-").replace("/", "-")
    ascii_name = re.sub(r"[^a-zA-Z0-9\-]", "", ascii_name)
    ascii_name = re.sub(r"-+", "-", ascii_name).strip("-")
    return ascii_name


# ─────────────────────────────────────────────────────────────────────────────
# Génération du HTML éditeur
# ─────────────────────────────────────────────────────────────────────────────


def _build_ports_maree_info_json() -> str:
    """Construit le mapping nom → maree_info_id pour le JS."""
    mapping = {nom: port_id for port_id, nom, _lat, _lon in ALL_PORTS}
    return json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))


def generate_editor_html(har_dir: str) -> str:
    """Génère le HTML de l'éditeur de marées."""
    har_files = scan_har_files(har_dir)
    utide_json = export_utide_json()
    shom_json, extra_json = export_mappings_json()
    har_files_json = json.dumps(har_files, ensure_ascii=False, separators=(",", ":"))
    ports_mi_json = _build_ports_maree_info_json()

    return (
        EDITOR_HTML_TEMPLATE.replace("__UTIDE_JSON__", utide_json)
        .replace("__SHOM_JSON__", shom_json)
        .replace("__EXTRA_JSON__", extra_json)
        .replace("__HAR_DIR__", har_dir)
        .replace("__HAR_FILES_JSON__", har_files_json)
        .replace("__PORTS_MAREE_INFO_JSON__", ports_mi_json)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Serveur HTTP
# ─────────────────────────────────────────────────────────────────────────────


class EditorHandler(SimpleHTTPRequestHandler):
    """Gestionnaire HTTP : sert l'éditeur + API de création HAR."""

    har_dir = "har_ports"
    atlas_base = "MARC_L1-ATLAS-AHRMONIQUES"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/editeur_marees.html", "/index.html"):
            # Génère et sert le HTML éditeur
            try:
                body = generate_editor_html(self.har_dir).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_error(500, str(e))
            return

        if path == "/api/list_ports":
            # Retourne la liste des ports actuels
            try:
                har_files = scan_har_files(self.har_dir)
                body = json.dumps(har_files, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_error(500, str(e))
            return

        if path == "/api/maree_info":
            self._handle_maree_info(parsed)
            return

        if path == "/api/maree_info_courbe":
            self._handle_maree_info_courbe(parsed)
            return

        # Servir les fichiers statiques normalement
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/create_har":
            self._handle_create_har()
            return

        if parsed.path == "/api/delete_har":
            self._handle_delete_har()
            return

        if parsed.path == "/api/move_grid":
            self._handle_move_grid()
            return

        if parsed.path == "/api/relocate_har":
            self._handle_relocate_har()
            return

        self._send_error(404, "Endpoint inconnu")

    def _handle_create_har(self):
        """Crée un fichier .har pour un nouveau port."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            data = json.loads(body.decode("utf-8"))

            nom = data.get("nom", "").strip()
            lat = float(data.get("lat", 0))
            lon = float(data.get("lon", 0))

            if not nom:
                self._send_json(400, {"error": "Nom requis"})
                return

            # Nom de fichier : préfixé avec -
            fname = "-" + safe_filename(nom) + ".har"
            filepath = Path(self.har_dir) / fname

            if filepath.exists():
                self._send_json(409, {"error": f"Le fichier {fname} existe déjà"})
                return

            # Trouver le meilleur atlas
            print(f"[API] Création HAR pour '{nom}' ({lat:.4f}, {lon:.4f})...")
            atlas_dir = find_best_atlas(self.atlas_base, lat, lon)
            print(f"  → Atlas : {Path(atlas_dir).name}")

            # Extraire les constituants
            constituents, atlas_name, actual_lat, actual_lon = extract_constituents(
                atlas_dir, lat, lon
            )
            print(
                f"  → {len(constituents)} constituants, point ({actual_lat:.4f}, {actual_lon:.4f})"
            )

            # Écrire le fichier HAR
            write_har(str(filepath), nom, lat, lon, constituents, atlas_name)
            print(f"  → Fichier créé : {filepath}")

            # Lire les métadonnées
            meta = extract_har_metadata(filepath)

            result = {
                "ok": True,
                "filename": fname,
                "nom": meta["nom"],
                "lat": meta["lat"],
                "lon": meta["lon"],
                "z0": meta["z0"],
            }
            self._send_json(200, result)

        except Exception as e:
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})

    def _handle_delete_har(self):
        """Supprime un fichier .har existant."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            data = json.loads(body.decode("utf-8"))

            filename = str(data.get("filename", "")).strip()
            if not filename:
                self._send_json(400, {"error": "Nom de fichier requis"})
                return
            if filename != Path(filename).name or not filename.endswith(".har"):
                self._send_json(400, {"error": "Nom de fichier invalide"})
                return

            har_dir_path = Path(self.har_dir).resolve()
            filepath = (har_dir_path / filename).resolve()
            if filepath.parent != har_dir_path:
                self._send_json(400, {"error": "Chemin de fichier invalide"})
                return
            if not filepath.exists():
                self._send_json(404, {"error": f"Fichier introuvable: {filename}"})
                return

            filepath.unlink()
            print(f"[API] Fichier supprimé : {filepath}")
            self._send_json(200, {"ok": True, "filename": filename})

        except Exception as e:
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})

    def _handle_relocate_har(self):
        """Déplace un port à de nouvelles coordonnées et régénère le HAR."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            data = json.loads(body.decode("utf-8"))

            filename = str(data.get("filename", "")).strip()
            lat = float(data.get("lat", 0))
            lon = float(data.get("lon", 0))
            nom = str(data.get("nom", "")).strip()

            if not filename:
                self._send_json(400, {"error": "filename requis"})
                return

            har_dir_path = Path(self.har_dir).resolve()
            filepath = (har_dir_path / filename).resolve()
            if filepath.parent != har_dir_path or not filepath.exists():
                self._send_json(404, {"error": f"Fichier introuvable: {filename}"})
                return

            meta = extract_har_metadata(filepath)
            port_nom = nom or meta["nom"]

            print(f"[API] Relocalisation '{port_nom}' vers ({lat:.6f}, {lon:.6f})...")

            atlas_dir = find_best_atlas(self.atlas_base, lat, lon)
            constituents, atlas_name, actual_lat, actual_lon = extract_constituents(
                atlas_dir, lat, lon
            )
            print(
                f"  \u2192 Point oc\u00e9anique : ({actual_lat:.6f}, {actual_lon:.6f}), {len(constituents)} constituants"
            )

            write_har(
                str(filepath),
                port_nom,
                actual_lat,
                actual_lon,
                constituents,
                atlas_name,
            )
            print(f"  \u2192 Fichier r\u00e9\u00e9crit : {filepath}")

            new_meta = extract_har_metadata(filepath)

            self._send_json(
                200,
                {
                    "ok": True,
                    "filename": filename,
                    "nom": new_meta["nom"],
                    "lat": new_meta["lat"],
                    "lon": new_meta["lon"],
                    "z0": new_meta["z0"],
                },
            )

        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})

    def _handle_move_grid(self):
        """D\u00e9place un port d'une case sur la grille atlas et r\u00e9g\u00e9n\u00e8re le HAR."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            data = json.loads(body.decode("utf-8"))

            filename = str(data.get("filename", "")).strip()
            direction = str(data.get("direction", "")).strip().upper()
            nom = str(data.get("nom", "")).strip()

            if not filename or not direction or direction not in ("N", "S", "E", "O"):
                self._send_json(
                    400, {"error": "filename et direction (N/S/E/O) requis"}
                )
                return

            har_dir_path = Path(self.har_dir).resolve()
            filepath = (har_dir_path / filename).resolve()
            if filepath.parent != har_dir_path or not filepath.exists():
                self._send_json(404, {"error": f"Fichier introuvable: {filename}"})
                return

            # Lire les coordonnées actuelles du HAR
            meta = extract_har_metadata(filepath)
            current_lat = meta["lat"]
            current_lon = meta["lon"]
            port_nom = nom or meta["nom"]

            print(
                f"[API] Déplacement {direction} pour '{port_nom}' depuis ({current_lat:.6f}, {current_lon:.6f})..."
            )

            # Déplacer d'une case
            constituents, atlas_name, new_lat, new_lon = move_grid_point(
                self.atlas_base, current_lat, current_lon, direction
            )
            print(
                f"  → Nouveau point : ({new_lat:.6f}, {new_lon:.6f}), {len(constituents)} constituants"
            )

            # Réécrire le fichier HAR
            write_har(
                str(filepath), port_nom, new_lat, new_lon, constituents, atlas_name
            )
            print(f"  → Fichier réécrit : {filepath}")

            # Relire les métadonnées
            new_meta = extract_har_metadata(filepath)

            self._send_json(
                200,
                {
                    "ok": True,
                    "filename": filename,
                    "nom": new_meta["nom"],
                    "lat": new_meta["lat"],
                    "lon": new_meta["lon"],
                    "z0": new_meta["z0"],
                },
            )

        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})

    def _handle_maree_info(self, parsed):
        """Proxy vers maree.info pour éviter les problèmes CORS."""
        try:
            qs = parse_qs(parsed.query)
            port_id = int(qs.get("port_id", [0])[0])
            if not port_id:
                self._send_json(400, {"error": "port_id requis"})
                return
            data = fetch_maree_info(port_id)
            if data is None:
                self._send_json(502, {"error": "Impossible de contacter maree.info"})
                return
            self._send_json(200, data)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_maree_info_courbe(self, parsed):
        """Proxy vers maree.info — hauteurs heure par heure (24 pts/jour)."""
        try:
            qs = parse_qs(parsed.query)
            port_id = int(qs.get("port_id", [0])[0])
            if not port_id:
                self._send_json(400, {"error": "port_id requis"})
                return
            data = fetch_maree_info_courbe(port_id)
            if data is None:
                self._send_json(502, {"error": "Impossible de contacter maree.info"})
                return
            # Convertir les clés int du dict hourly en string pour JSON
            hourly_str = {str(k): v for k, v in data["hourly"].items()}
            self._send_json(200, {"dates": data["dates"], "hourly": hourly_str})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code, message):
        self._send_json(code, {"error": message})

    def log_message(self, format, *args):
        # Filtrer les logs trop verbeux des fichiers statiques
        msg = format % args
        if "/har_ports/" not in msg and "/api/" not in msg:
            return
        super().log_message(format, *args)


# ─────────────────────────────────────────────────────────────────────────────
# Template HTML éditeur
# ─────────────────────────────────────────────────────────────────────────────

EDITOR_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Éditeur de marées — Ports de France</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; overflow: hidden; }
  body { display: flex; flex-direction: row; }

  #tide-panel {
    display: none; background: #fff; border-right: 2px solid #ccc;
    padding: 10px 14px; position: relative; flex-shrink: 0;
    width: 33.33vw; overflow-y: auto;
    flex-direction: column;
  }
  #tide-panel h3 { margin: 0 0 4px; font-size: 17px; color: #333; }
  #tide-panel .info { font-size: 12px; color: #666; margin-bottom: 4px; line-height: 1.5; }
  #tide-panel .info a { color: #2d8a4e; text-decoration: none; }
  #tide-panel .info a:hover { text-decoration: underline; }
  .buggy-tag { color: #c00; font-weight: bold; }
  .new-tag { color: #2563eb; font-weight: bold; }

  .danger-btn {
    margin: 6px 0 4px;
    border: 1px solid #e74c3c;
    background: #fff5f5;
    color: #c0392b;
    border-radius: 5px;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    width: fit-content;
  }
  .danger-btn:hover { background: #ffe9e9; }

  #close-panel {
    position: absolute; top: 6px; right: 10px;
    background: none; border: none; font-size: 22px; cursor: pointer;
    color: #888; line-height: 1;
  }
  #close-panel:hover { color: #333; }

  .nav-bar {
    display: flex; align-items: center; justify-content: center;
    gap: 8px; margin: 4px 0 6px 0;
  }
  .nav-bar button {
    border: none; background: #eee; border-radius: 4px;
    padding: 3px 12px; font-size: 18px; cursor: pointer; line-height: 1;
  }
  .nav-bar button:hover { background: #ddd; }
  .nav-bar .date-label {
    font-size: 13px; font-weight: 600; min-width: 200px; text-align: center;
  }

  .extremes-list {
    display: flex; flex-direction: column; gap: 2px;
    font-size: 12px; margin-bottom: 6px; color: #444;
  }
  .extremes-list .pm { color: #d35400; font-weight: 600; }
  .extremes-list .bm { color: #2980b9; font-weight: 600; }

  .chart-wrap { position: relative; width: 100%; }
  .chart-wrap canvas { display: block; }

  #map { flex: 1; min-height: 0; }

  .legend {
    background: white; padding: 8px 12px; border-radius: 6px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-size: 13px; line-height: 1.6;
  }
  .legend i {
    display: inline-block; width: 12px; height: 12px; border-radius: 50%;
    margin-right: 6px; vertical-align: middle;
  }
  .legend .green { background: #2d8a4e; }
  .legend .red { background: #c0392b; }
  .legend .blue { background: #2563eb; }

  /* Mode ajout */
  .add-mode-banner {
    position: fixed; top: 0; left: 0; right: 0;
    background: #2563eb; color: #fff; text-align: center;
    padding: 8px 16px; font-size: 14px; font-weight: 600;
    z-index: 2000; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  }
  .add-mode-banner button {
    margin-left: 16px; background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.5);
    color: #fff; padding: 4px 14px; border-radius: 4px; cursor: pointer; font-size: 13px;
  }
  .add-mode-banner button:hover { background: rgba(255,255,255,0.35); }

  /* Bouton Ajouter */
  .add-port-btn {
    background: #2563eb; color: #fff; border: 2px solid #fff;
    border-radius: 6px; padding: 6px 14px; font-size: 13px; font-weight: 600;
    cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
  }
  .add-port-btn:hover { background: #1d4ed8; }

  /* Modal */
  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    z-index: 3000; align-items: center; justify-content: center;
  }
  .modal-overlay.active { display: flex; }
  .modal {
    background: #fff; border-radius: 10px; padding: 24px; min-width: 360px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
  }
  .modal h3 { margin: 0 0 12px; font-size: 18px; color: #333; }
  .modal label { font-size: 13px; color: #555; display: block; margin-bottom: 4px; }
  .modal input {
    width: 100%; padding: 8px 10px; border: 1px solid #ccc; border-radius: 5px;
    font-size: 14px; margin-bottom: 12px;
  }
  .modal input:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37,99,235,0.2); }
  .modal .coords { font-size: 12px; color: #888; margin-bottom: 12px; }
  .modal .btn-row { display: flex; gap: 8px; justify-content: flex-end; }
  .modal .btn-row button {
    padding: 8px 18px; border: none; border-radius: 5px; font-size: 14px; cursor: pointer;
  }
  .modal .btn-cancel { background: #eee; color: #333; }
  .modal .btn-cancel:hover { background: #ddd; }
  .modal .btn-ok { background: #2563eb; color: #fff; font-weight: 600; }
  .modal .btn-ok:hover { background: #1d4ed8; }
  .modal .btn-ok:disabled { background: #93c5fd; cursor: not-allowed; }
  .modal .status { font-size: 12px; color: #666; margin-top: 8px; min-height: 18px; }
  .modal .status.error { color: #c00; }

  /* Boutons grille N/S/O/E */
  .grid-nav {
    display: none; margin: 6px 0 4px;
  }
  .grid-nav .grid-btns {
    display: inline-grid;
    grid-template-columns: 28px 28px 28px;
    grid-template-rows: 28px 28px 28px;
    gap: 2px;
    vertical-align: middle;
  }
  .grid-nav .grid-btns button {
    width: 28px; height: 28px; padding: 0;
    border: 1px solid #2563eb; border-radius: 4px;
    background: #eff6ff; color: #2563eb;
    font-size: 13px; font-weight: 700; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
  }
  .grid-nav .grid-btns button:hover { background: #dbeafe; }
  .grid-nav .grid-btns button:disabled { opacity: 0.4; cursor: not-allowed; }
  .grid-nav .grid-btns .empty { border: none; background: none; cursor: default; }
  .grid-nav .grid-lbl { font-size: 11px; color: #666; margin-left: 8px; vertical-align: middle; }
  .grid-nav .grid-status { font-size: 11px; color: #c00; margin-top: 2px; min-height: 16px; }
</style>
</head>
<body>
<div id="add-banner" class="add-mode-banner" style="display:none">
  Cliquez sur la carte pour placer le nouveau port
  <button onclick="cancelAddMode()">Annuler</button>
</div>
<div id="tide-panel">
  <button id="close-panel" onclick="closePanel()">✕</button>
  <h3 id="port-title"></h3>
  <div class="info" id="port-info"></div>
  <button id="delete-port-btn" class="danger-btn" onclick="deleteActivePort()">Supprimer ce port</button>
  <div class="grid-nav" id="grid-nav">
    <div class="grid-btns">
      <button class="empty"></button>
      <button onclick="moveGrid('N')" title="Nord">N</button>
      <button class="empty"></button>
      <button onclick="moveGrid('O')" title="Ouest">O</button>
      <button class="empty"></button>
      <button onclick="moveGrid('E')" title="Est">E</button>
      <button class="empty"></button>
      <button onclick="moveGrid('S')" title="Sud">S</button>
      <button class="empty"></button>
    </div>
    <span class="grid-lbl">Déplacer sur la grille atlas</span>
    <div class="grid-status" id="grid-status"></div>
  </div>
  <div class="nav-bar">
    <button onclick="navigateDay(-1)">◀</button>
    <span class="date-label" id="date-lbl"></span>
    <button onclick="navigateDay(1)">▶</button>
  </div>
  <div class="extremes-list" id="extremes"></div>
  <div class="chart-wrap"><canvas id="tide-chart"></canvas></div>
  <div id="ref-section" style="display:none; margin-top:10px; border-top:1px solid #ddd; padding-top:8px;">
    <div id="ref-header" style="font-size:13px; font-weight:600; color:#555; margin-bottom:4px;">Référence maree.info (SHOM)</div>
    <div class="extremes-list" id="ref-extremes"></div>
    <div class="chart-wrap"><canvas id="ref-chart"></canvas></div>
  </div>
</div>
<div id="map"></div>

<!-- Modal de création -->
<div id="add-modal" class="modal-overlay">
  <div class="modal">
    <h3>Ajouter un port</h3>
    <div class="coords" id="modal-coords"></div>
    <label for="modal-nom">Nom du port</label>
    <input type="text" id="modal-nom" placeholder="Ex: Saint-Malo" autofocus />
    <div class="btn-row">
      <button class="btn-cancel" onclick="closeModal()">Annuler</button>
      <button class="btn-ok" id="modal-ok" onclick="confirmAddPort()">Créer</button>
    </div>
    <div class="status" id="modal-status"></div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
//  CONSTANTES UTIDE
// ═══════════════════════════════════════════════════════════════
const UTIDE = __UTIDE_JSON__;

const SHOM_TO_UTIDE = __SHOM_JSON__;
const EXTRA_CONSTITUENTS = __EXTRA_JSON__;

const HAR_DIR = '__HAR_DIR__';
let HAR_FILES = __HAR_FILES_JSON__;
const PORTS_MAREE_INFO = __PORTS_MAREE_INFO_JSON__;

const UTIDE_NAMES = UTIDE.c.map(c => c.n);
const UTIDE_NAME_IDX = {};
UTIDE_NAMES.forEach((n, i) => UTIDE_NAME_IDX[n] = i);

const NCONST = UTIDE.c.length;
const IS_SHALLOW = new Array(NCONST);
for (let i = 0; i < NCONST; i++) {
  IS_SHALLOW[i] = UTIDE.c[i].ns !== undefined;
}

// ═══════════════════════════════════════════════════════════════
//  ASTRONOMIE
// ═══════════════════════════════════════════════════════════════

const _ASTRO_COEFS = [
  [270.434164, 13.1763965268, -0.0000850,  0.000000039],
  [279.696678,  0.9856473354,  0.00002267, 0.000000000],
  [334.329556,  0.1114040803, -0.0007739, -0.00000026],
  [-259.183275, 0.0529539222, -0.0001557, -0.000000050],
  [281.220844,  0.0000470684,  0.0000339,  0.000000070],
];

function utAstron(jd) {
  const daten = 693595.5;
  const d = jd - daten;
  const D = d / 10000;
  const D2 = D * D;
  const D3 = D2 * D;
  const astro = new Float64Array(6);
  const ader  = new Float64Array(6);
  for (let i = 0; i < 5; i++) {
    const c = _ASTRO_COEFS[i];
    const val = c[0] + c[1] * d + c[2] * D2 + c[3] * D3;
    astro[i + 1] = (val / 360) % 1;
    const dval = c[1] + c[2] * 2e-4 * D + c[3] * 3e-4 * D2;
    ader[i + 1] = dval / 360;
  }
  astro[0] = (jd % 1) + astro[2] - astro[1];
  ader[0] = 1.0 + ader[2] - ader[1];
  return { astro, ader };
}

// ═══════════════════════════════════════════════════════════════
//  CALCUL FUV
// ═══════════════════════════════════════════════════════════════

function computeAllFUV(t_ord, lat) {
  const { astro } = utAstron(t_ord);
  const TWO_PI = 2 * Math.PI;
  if (Math.abs(lat) < 5) lat = Math.sign(lat || 1) * 5;
  const slat = Math.sin(lat * Math.PI / 180);
  const sats = UTIDE.s;
  const nsat = sats.length;
  const Fr = new Float64Array(NCONST).fill(1);
  const Fi = new Float64Array(NCONST).fill(0);
  for (let i = 0; i < nsat; i++) {
    let r = sats[i][3];
    const ilatfac = sats[i][4];
    if (ilatfac === 1) r *= 0.36309 * (1.0 - 5.0 * slat * slat) / slat;
    else if (ilatfac === 2) r *= 2.59808 * slat;
    const dd = sats[i][1];
    let u = dd[0] * astro[3] + dd[1] * astro[4] + dd[2] * astro[5] + sats[i][2];
    u = u % 1;
    const angle = TWO_PI * u;
    const ic = sats[i][0];
    Fr[ic] += r * Math.cos(angle);
    Fi[ic] += r * Math.sin(angle);
  }
  const F = new Float64Array(NCONST);
  const U = new Float64Array(NCONST);
  for (let i = 0; i < NCONST; i++) {
    F[i] = Math.sqrt(Fr[i] * Fr[i] + Fi[i] * Fi[i]);
    U[i] = Math.atan2(Fi[i], Fr[i]) / TWO_PI;
  }
  const shData = UTIDE.sh;
  for (let i = 0; i < NCONST; i++) {
    const ci = UTIDE.c[i];
    if (ci.ns === undefined) continue;
    const nshal = ci.ns;
    const i0 = ci.is;
    let fProd = 1.0, uSum = 0.0;
    for (let k = 0; k < nshal; k++) {
      const j = shData[i0 + k][0];
      const coef = shData[i0 + k][1];
      fProd *= Math.pow(F[j], Math.abs(coef));
      uSum += U[j] * coef;
    }
    F[i] = fProd;
    U[i] = uSum;
  }
  const V = new Float64Array(NCONST);
  for (let i = 0; i < NCONST; i++) {
    if (IS_SHALLOW[i]) continue;
    const ci = UTIDE.c[i];
    let v = 0;
    for (let j = 0; j < 6; j++) v += ci.d[j] * astro[j];
    if (ci.s) v += ci.s;
    v = v % 1;
    V[i] = v;
  }
  for (let i = 0; i < NCONST; i++) {
    const ci = UTIDE.c[i];
    if (ci.ns === undefined) continue;
    const nshal = ci.ns;
    const i0 = ci.is;
    let v = 0;
    for (let k = 0; k < nshal; k++) {
      const j = shData[i0 + k][0];
      const coef = shData[i0 + k][1];
      v += V[j] * coef;
    }
    V[i] = v;
  }
  return { F, U, V };
}

// ═══════════════════════════════════════════════════════════════
//  PARSEUR .har
// ═══════════════════════════════════════════════════════════════

function parseHAR(text, filename) {
  const lines = text.split(/\r?\n/);
  let section = null;
  let nom = filename.replace(/\.har$/, '');
  let lat = null, lon = null, z0 = null;
  const constituents = {};
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('[') && line.endsWith(']')) {
      section = line.slice(1, -1).toLowerCase();
      continue;
    }
    if (section === 'port' && line.includes('=')) {
      const eqIdx = line.indexOf('=');
      const k = line.slice(0, eqIdx).trim().toLowerCase();
      const v = line.slice(eqIdx + 1).trim();
      if (k === 'nom') nom = v;
      else if (k === 'latitude') lat = parseFloat(v);
      else if (k === 'longitude') lon = parseFloat(v);
      else if (k === 'z0') z0 = parseFloat(v);
    } else if (section === 'constituants') {
      const parts = line.split(/\s+/);
      if (parts.length >= 3) {
        const amp = parseFloat(parts[1]);
        const phase = parseFloat(parts[2]);
        if (!isNaN(amp) && !isNaN(phase)) {
          constituents[parts[0]] = [amp, phase];
        }
      }
    }
  }
  if (lat === null || lon === null) return null;
  return { nom, lat, lon, z0, constituents, filename };
}

// ═══════════════════════════════════════════════════════════════
//  PRÉPARATION D'UN PORT
// ═══════════════════════════════════════════════════════════════

function resolveUtideName(shomName) {
  if (SHOM_TO_UTIDE.hasOwnProperty(shomName)) return SHOM_TO_UTIDE[shomName];
  if (UTIDE_NAME_IDX.hasOwnProperty(shomName)) return shomName;
  return shomName;
}

function datetimeToOrdinal(date) {
  const epochOrdinal = 719163;
  return epochOrdinal + date.getTime() / 86400000;
}

function ordinalToJD(ordinal) {
  return ordinal + 1721424.5;
}

function preparePort(harData, FUV_all, t0_ord) {
  const DEG = 360;
  const cList = [];
  const jd0 = ordinalToJD(t0_ord);
  const t0_hours_j2000 = (jd0 - 2451545.0) * 24.0;
  const parentCache = {};

  for (const [shomName, [amp, phaseG]] of Object.entries(harData.constituents)) {
    if (shomName === 'Z0') continue;
    const utideName = resolveUtideName(shomName);
    if (utideName !== null && UTIDE_NAME_IDX.hasOwnProperty(utideName)) {
      const idx = UTIDE_NAME_IDX[utideName];
      const speed = UTIDE.c[idx].f * DEG;
      const effAmp = FUV_all.F[idx] * amp;
      const effPhase = FUV_all.V[idx] * DEG + FUV_all.U[idx] * DEG - phaseG;
      if (effAmp > 1e-7) {
        cList.push({ w: speed, a: effAmp, p: effPhase });
      }
      parentCache[utideName] = {
        f: FUV_all.F[idx],
        u: FUV_all.U[idx] * DEG,
        v: FUV_all.V[idx] * DEG,
      };
      continue;
    }
    if (EXTRA_CONSTITUENTS.hasOwnProperty(shomName)) {
      const extra = EXTRA_CONSTITUENTS[shomName];
      const speed = extra.w;
      const decomp = extra.d;
      let V_c = 0, U_c = 0, f_c = 1;
      if (decomp.length > 0) {
        for (const [pname, coef] of decomp) {
          if (!parentCache[pname] && UTIDE_NAME_IDX.hasOwnProperty(pname)) {
            const pidx = UTIDE_NAME_IDX[pname];
            parentCache[pname] = {
              f: FUV_all.F[pidx],
              u: FUV_all.U[pidx] * DEG,
              v: FUV_all.V[pidx] * DEG,
            };
          }
          if (parentCache[pname]) {
            const pd = parentCache[pname];
            V_c += coef * pd.v;
            U_c += coef * pd.u;
            f_c *= Math.pow(pd.f, Math.abs(coef));
          }
        }
      } else {
        V_c = speed * t0_hours_j2000;
        f_c = 1.0;
      }
      const effAmp = f_c * amp;
      const effPhase = V_c + U_c - phaseG;
      if (effAmp > 1e-7) {
        cList.push({ w: speed, a: effAmp, p: effPhase });
      }
      continue;
    }
  }

  return {
    nom: harData.nom,
    lat: harData.lat,
    lon: harData.lon,
    z0: harData.z0 || 0,
    filename: harData.filename,
    buggy: harData.filename.startsWith('_'),
    isNew: harData.filename.startsWith('-'),
    c: cList,
  };
}

// ═══════════════════════════════════════════════════════════════
//  PRÉDICTION HARMONIQUE
// ═══════════════════════════════════════════════════════════════

function predict(port, dayOffset) {
  const STEP = 10;
  const N = 24 * 60 / STEP + 1;
  const times = new Array(N);
  const heights = new Array(N);
  for (let i = 0; i < N; i++) {
    const minute = i * STEP;
    const h = harmonicHeightAtMinute(port, dayOffset, minute);
    times[i] = minute;
    heights[i] = Math.round(h * 1000) / 1000;
  }
  return { times, heights };
}

function harmonicHeightAtMinute(port, dayOffset, minuteLocal) {
  const baseH = dayOffset * 24 - localUtcOffsetHoursForDay(dayOffset);
  const dt = baseH + minuteLocal / 60;
  const DEG2RAD = Math.PI / 180;
  const nc = port.c.length;
  let h = port.z0;
  for (let j = 0; j < nc; j++) {
    const c = port.c[j];
    h += c.a * Math.cos((c.w * dt + c.p) * DEG2RAD);
  }
  return h;
}

function findExtremes(port, dayOffset, times, heights) {
  const pm = [], bm = [];
  const stepMin = times.length > 1 ? Math.max(1, Math.round(times[1] - times[0])) : 10;
  for (let i = 1; i < heights.length - 1; i++) {
    const isPeak = heights[i] > heights[i-1] && heights[i] >= heights[i+1];
    const isTrough = heights[i] < heights[i-1] && heights[i] <= heights[i+1];
    if (!isPeak && !isTrough) continue;

    const center = times[i];
    const tStart = Math.max(0, center - stepMin);
    const tEnd = Math.min(1440, center + stepMin);
    let bestT = center;
    let bestH = harmonicHeightAtMinute(port, dayOffset, center);

    for (let t = tStart; t <= tEnd; t += 1) {
      const h = harmonicHeightAtMinute(port, dayOffset, t);
      if ((isPeak && h > bestH) || (isTrough && h < bestH)) {
        bestH = h;
        bestT = t;
      }
    }

    const extreme = { t: Math.round(bestT), h: Math.round(bestH * 1000) / 1000 };
    if (isPeak) pm.push(extreme);
    else bm.push(extreme);
  }
  return { pm, bm };
}

function pad2(n) { return String(n).padStart(2, '0'); }
function minutesToHHMM(m) {
  const mm = ((m % 1440) + 1440) % 1440;
  return pad2(Math.floor(mm/60)) + 'h' + pad2(mm%60);
}

// ═══════════════════════════════════════════════════════════════
//  CHARGEMENT & STATE
// ═══════════════════════════════════════════════════════════════

const PORT_CACHE = {};
let activePort = null;
let activePortIdx = -1;
let activeDayOffset = 0;
let activeChart = null;
let refChart = null;
let refCache = {};
let map;
let T0, T0_ORD;

// Éditeur : état ajout
let addMode = false;
let addLatLng = null;
let allMarkers = [];

function init() {
  const now = new Date();
  T0 = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  T0_ORD = datetimeToOrdinal(T0);
  initMap();
}

function localUtcOffsetHoursForDay(off) {
  const d = dateForOffset(off);
  const localMidnight = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  return -localMidnight.getTimezoneOffset() / 60;
}

function dateForOffset(off) {
  return new Date(T0.getTime() + off * 86400000);
}
function dateLabel(off) {
  return dateForOffset(off).toLocaleDateString('fr-FR', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
  });
}
function dateISO(off) {
  return dateForOffset(off).toISOString().slice(0, 10);
}

function makeIcon(color) {
  return L.divIcon({
    className: '',
    html: `<svg width="20" height="28" viewBox="0 0 20 28">
      <path d="M10 0C4.5 0 0 4.5 0 10c0 7.5 10 18 10 18s10-10.5 10-18C20 4.5 15.5 0 10 0z"
            fill="${color}" stroke="#fff" stroke-width="1.5"/>
      <circle cx="10" cy="10" r="4" fill="#fff"/>
    </svg>`,
    iconSize: [20, 28], iconAnchor: [10, 28],
  });
}

// ═══════════════════════════════════════════════════════════════
//  CARTE LEAFLET
// ═══════════════════════════════════════════════════════════════

function initMap() {
  map = L.map('map').setView([47.5, -2.5], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap', maxZoom: 18,
  }).addTo(map);

  rebuildMarkers();

  // Clic sur la carte en mode ajout
  map.on('click', (e) => {
    if (!addMode) return;
    addLatLng = e.latlng;
    openModal(e.latlng.lat, e.latlng.lng);
  });

  // Légende + bouton Ajouter
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = function() {
    const div = L.DomUtil.create('div', 'legend');
    updateLegend(div);
    return div;
  };
  legend.addTo(map);

  // Bouton Ajouter
  const addCtrl = L.control({ position: 'topright' });
  addCtrl.onAdd = function() {
    const div = L.DomUtil.create('div');
    div.innerHTML = '<button class="add-port-btn" onclick="enterAddMode()">+ Ajouter un port</button>';
    L.DomEvent.disableClickPropagation(div);
    return div;
  };
  addCtrl.addTo(map);

  if (HAR_FILES.length > 0) {
    map.fitBounds(
      L.latLngBounds(HAR_FILES.map(p => [p.lat, p.lon])),
      { padding: [30, 30] }
    );
  }
}

function rebuildMarkers() {
  allMarkers.forEach(m => map.removeLayer(m));
  allMarkers = [];

  const greenIcon = makeIcon('#2d8a4e');
  const redIcon   = makeIcon('#c0392b');
  const blueIcon  = makeIcon('#2563eb');

  HAR_FILES.forEach((hf, idx) => {
    const isNew = hf.filename.startsWith('-');
    const icon = isNew ? blueIcon : hf.buggy ? redIcon : greenIcon;
    const marker = L.marker([hf.lat, hf.lon], { icon, draggable: isNew }).addTo(map);
    marker.on('click', () => {
      if (addMode) return;
      selectPort(idx);
    });
    if (isNew) {
      marker.on('dragend', () => {
        const ll = marker.getLatLng();
        relocatePort(idx, ll.lat, ll.lng);
      });
    }
    allMarkers.push(marker);
  });
}

function updateLegend(div) {
  if (!div) div = document.querySelector('.legend');
  if (!div) return;
  const nOK  = HAR_FILES.filter(p => !p.buggy && !p.filename.startsWith('-')).length;
  const nBug = HAR_FILES.filter(p => p.buggy).length;
  const nNew = HAR_FILES.filter(p => p.filename.startsWith('-')).length;
  div.innerHTML = `
    <b>Ports de marée (${HAR_FILES.length})</b><br>
    <i class="green"></i> OK (${nOK})<br>
    ${nBug > 0 ? '<i class="red"></i> Buggy (' + nBug + ')<br>' : ''}
    ${nNew > 0 ? '<i class="blue"></i> Nouveaux (' + nNew + ')<br>' : ''}
    <span style="font-size:11px;color:#888">Clic = courbe &nbsp;◀ ▶ = jour</span>
  `;
}

// ═══════════════════════════════════════════════════════════════
//  MODE AJOUT
// ═══════════════════════════════════════════════════════════════

function enterAddMode() {
  addMode = true;
  document.getElementById('add-banner').style.display = 'block';
  document.getElementById('map').style.cursor = 'crosshair';
}

function cancelAddMode() {
  addMode = false;
  addLatLng = null;
  document.getElementById('add-banner').style.display = 'none';
  document.getElementById('map').style.cursor = '';
}

function openModal(lat, lng) {
  document.getElementById('add-banner').style.display = 'none';
  const modal = document.getElementById('add-modal');
  modal.classList.add('active');
  document.getElementById('modal-coords').textContent =
    `Position : ${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E`;
  document.getElementById('modal-nom').value = '';
  document.getElementById('modal-status').textContent = '';
  document.getElementById('modal-status').className = 'status';
  document.getElementById('modal-ok').disabled = false;
  setTimeout(() => document.getElementById('modal-nom').focus(), 100);
}

function closeModal() {
  document.getElementById('add-modal').classList.remove('active');
  cancelAddMode();
}

async function confirmAddPort() {
  const nom = document.getElementById('modal-nom').value.trim();
  if (!nom) {
    document.getElementById('modal-status').textContent = 'Veuillez saisir un nom.';
    document.getElementById('modal-status').className = 'status error';
    return;
  }

  const statusEl = document.getElementById('modal-status');
  const okBtn = document.getElementById('modal-ok');
  statusEl.textContent = 'Création en cours… (extraction des harmoniques)';
  statusEl.className = 'status';
  okBtn.disabled = true;

  try {
    const resp = await fetch('/api/create_har', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nom: nom,
        lat: addLatLng.lat,
        lon: addLatLng.lng,
      }),
    });

    const result = await resp.json();
    if (!resp.ok) {
      throw new Error(result.error || 'Erreur serveur');
    }

    statusEl.textContent = `Port créé : ${result.filename}`;

    // Ajouter au tableau
    const newEntry = {
      filename: result.filename,
      buggy: false,
      nom: result.nom,
      lat: result.lat,
      lon: result.lon,
      z0: result.z0,
    };
    HAR_FILES.push(newEntry);
    const idx = HAR_FILES.length - 1;
    rebuildMarkers();

    // Mettre à jour la légende
    updateLegend();

    // Fermer la modal après un court délai
    setTimeout(() => {
      closeModal();
      // Sélectionner automatiquement le nouveau port
      selectPort(idx);
    }, 800);

  } catch (e) {
    statusEl.textContent = 'Erreur : ' + e.message;
    statusEl.className = 'status error';
    okBtn.disabled = false;
  }
}

// Touche Entrée dans le champ nom
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && document.getElementById('add-modal').classList.contains('active')) {
    confirmAddPort();
  }
  if (e.key === 'Escape') {
    if (document.getElementById('add-modal').classList.contains('active')) {
      closeModal();
    } else if (addMode) {
      cancelAddMode();
    }
  }
});

// ═══════════════════════════════════════════════════════════════
//  SÉLECTION D'UN PORT
// ═══════════════════════════════════════════════════════════════

async function selectPort(idx) {
  const meta = HAR_FILES[idx];
  const panel = document.getElementById('tide-panel');
  panel.style.display = 'flex';
  setTimeout(() => map.invalidateSize(), 50);

  const isNew = meta.filename.startsWith('-');
  const buggyTag = meta.buggy ? '<span class="buggy-tag"> ⚠ BUGGY</span>' : '';
  const newTag = isNew ? '<span class="new-tag"> ● NOUVEAU</span>' : '';
  document.getElementById('port-title').innerHTML = meta.nom + buggyTag + newTag;
  document.getElementById('port-info').innerHTML = 'Chargement…';
  document.getElementById('extremes').innerHTML = '';
  document.getElementById('grid-nav').style.display = isNew ? 'block' : 'none';
  document.getElementById('grid-status').textContent = '';
  if (activeChart) { activeChart.destroy(); activeChart = null; }
  if (refChart) { refChart.destroy(); refChart = null; }
  document.getElementById('ref-section').style.display = 'none';

  activePortIdx = idx;

  if (!PORT_CACHE[meta.filename]) {
    try {
      const resp = await fetch(HAR_DIR + '/' + meta.filename);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const text = await resp.text();
      const har = parseHAR(text, meta.filename);
      if (!har) throw new Error('Erreur de parsing');
      const portFUV = computeAllFUV(T0_ORD, har.lat);
      PORT_CACHE[meta.filename] = preparePort(har, portFUV, T0_ORD);
    } catch (e) {
      document.getElementById('port-info').innerHTML = 'Erreur : ' + e.message;
      return;
    }
  }

  activePort = PORT_CACHE[meta.filename];
  activeDayOffset = 0;
  updateTidePanel();
}

// ═══════════════════════════════════════════════════════════════
//  DÉPLACEMENT GRILLE ATLAS
// ═══════════════════════════════════════════════════════════════

async function relocatePort(idx, lat, lon) {
  const meta = HAR_FILES[idx];
  if (!meta || !meta.filename.startsWith('-')) return;

  const statusEl = document.getElementById('grid-status');
  if (statusEl) {
    statusEl.textContent = 'Recalcul des harmoniques\u2026';
    statusEl.style.color = '#666';
  }

  try {
    const resp = await fetch('/api/relocate_har', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: meta.filename,
        lat: lat,
        lon: lon,
        nom: meta.nom,
      }),
    });

    const result = await resp.json();
    if (!resp.ok) throw new Error(result.error || 'Erreur serveur');

    meta.lat = result.lat;
    meta.lon = result.lon;
    meta.z0 = result.z0;

    delete PORT_CACHE[meta.filename];
    refCache = {};

    if (statusEl) {
      statusEl.textContent = `\u2192 (${result.lat.toFixed(4)}, ${result.lon.toFixed(4)})`;
      statusEl.style.color = '#2d8a4e';
    }

    rebuildMarkers();

    if (activePortIdx === idx) {
      await selectPort(idx);
    }

  } catch (e) {
    if (statusEl) {
      statusEl.textContent = e.message;
      statusEl.style.color = '#c00';
    }
    // Remettre le marqueur à sa position d'origine
    rebuildMarkers();
  }
}

async function moveGrid(direction) {
  if (!activePort || activePortIdx < 0) return;
  const meta = HAR_FILES[activePortIdx];
  if (!meta.filename.startsWith('-')) return;

  const statusEl = document.getElementById('grid-status');
  statusEl.textContent = 'Déplacement ' + direction + '…';
  statusEl.style.color = '#666';

  // Désactiver les boutons pendant le calcul
  document.querySelectorAll('.grid-btns button:not(.empty)').forEach(b => b.disabled = true);

  try {
    const resp = await fetch('/api/move_grid', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: meta.filename,
        direction: direction,
        nom: meta.nom,
      }),
    });

    const result = await resp.json();
    if (!resp.ok) throw new Error(result.error || 'Erreur serveur');

    // Mettre à jour les métadonnées du port
    meta.lat = result.lat;
    meta.lon = result.lon;
    meta.z0 = result.z0;

    // Invalider le cache pour forcer le rechargement
    delete PORT_CACHE[meta.filename];
    refCache = {};

    statusEl.textContent = `→ (${result.lat.toFixed(4)}, ${result.lon.toFixed(4)})`;
    statusEl.style.color = '#2d8a4e';

    // Recharger le port
    await selectPort(activePortIdx);

    // Mettre à jour le marqueur sur la carte
    rebuildMarkers();

  } catch (e) {
    statusEl.textContent = e.message;
    statusEl.style.color = '#c00';
  } finally {
    document.querySelectorAll('.grid-btns button:not(.empty)').forEach(b => b.disabled = false);
  }
}

async function deleteActivePort() {
  if (!activePort) return;
  const filename = activePort.filename;
  const portName = activePort.nom || filename;
  const ok = confirm(`Supprimer le port "${portName}" et le fichier ${filename} ?`);
  if (!ok) return;

  try {
    const resp = await fetch('/api/delete_har', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename }),
    });
    const result = await resp.json();
    if (!resp.ok) {
      throw new Error(result.error || 'Erreur serveur');
    }

    delete PORT_CACHE[filename];
    const idx = HAR_FILES.findIndex(p => p.filename === filename);
    if (idx !== -1) HAR_FILES.splice(idx, 1);

    closePanel();
    rebuildMarkers();
    updateLegend();
  } catch (e) {
    alert('Suppression impossible : ' + e.message);
  }
}

function updateTidePanel() {
  if (!activePort) return;
  const gpsStr = activePort.lat.toFixed(6) + ', ' + activePort.lon.toFixed(6);
  const gmapUrl = 'https://www.google.com/maps?q=' + activePort.lat.toFixed(6) + ',' + activePort.lon.toFixed(6);
  const harHref = HAR_DIR + '/' + encodeURIComponent(activePort.filename);
  document.getElementById('port-info').innerHTML =
    `<a href="${gmapUrl}" target="_blank" title="Voir sur Google Maps">${gpsStr}</a>` +
    ` &nbsp;|&nbsp; <a href="${harHref}" download="${activePort.filename}" title="Télécharger le fichier HAR">${activePort.filename}</a>`;
  document.getElementById('date-lbl').textContent = dateLabel(activeDayOffset);
  renderChart(activePort, activeDayOffset);
  fetchAndRenderRef(activePort, activeDayOffset);
}

function navigateDay(delta) {
  activeDayOffset += delta;
  updateTidePanel();
}

function closePanel() {
  document.getElementById('tide-panel').style.display = 'none';
  if (activeChart) { activeChart.destroy(); activeChart = null; }
  if (refChart) { refChart.destroy(); refChart = null; }
  activePort = null;
  setTimeout(() => map.invalidateSize(), 50);
}

// ═══════════════════════════════════════════════════════════════
//  RÉFÉRENCE MAREE.INFO
// ═══════════════════════════════════════════════════════════════

function findMareeInfoMatch(portNom) {
  // Cherche directement dans le mapping
  if (PORTS_MAREE_INFO[portNom]) return {id: PORTS_MAREE_INFO[portNom], nom: portNom};
  // Fallback : recherche insensible à la casse
  const lc = portNom.toLowerCase();
  for (const [nom, id] of Object.entries(PORTS_MAREE_INFO)) {
    if (nom.toLowerCase() === lc) return {id, nom};
  }
  return null;
}

async function fetchAndRenderRef(port, dayOffset) {
  const refSection = document.getElementById('ref-section');
  const refExtEl = document.getElementById('ref-extremes');
  if (refChart) { refChart.destroy(); refChart = null; }

  const match = findMareeInfoMatch(port.nom);
  if (!match) {
    refSection.style.display = 'none';
    return;
  }
  const portId = match.id;

  refSection.style.display = 'block';
  document.getElementById('ref-header').textContent = 'Référence maree.info : ' + match.nom;
  refExtEl.innerHTML = '<span style="color:#999; font-style:italic;">Chargement maree.info…</span>';

  // Charger les PM/BM (cache "pm")
  const cacheKeyPM = 'pm_' + portId;
  let dataPM = refCache[cacheKeyPM];
  if (!dataPM) {
    try {
      const resp = await fetch('/api/maree_info?port_id=' + portId);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      dataPM = await resp.json();
      if (dataPM.error) throw new Error(dataPM.error);
      refCache[cacheKeyPM] = dataPM;
    } catch (e) {
      refExtEl.innerHTML = '<span style="color:#c00;">Erreur : ' + e.message + '</span>';
      return;
    }
  }

  // Charger la courbe horaire (cache "hourly")
  const cacheKeyCurve = 'curve_' + portId;
  let dataCurve = refCache[cacheKeyCurve];
  if (!dataCurve) {
    try {
      const resp = await fetch('/api/maree_info_courbe?port_id=' + portId);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      dataCurve = await resp.json();
      if (dataCurve.error) throw new Error(dataCurve.error);
      refCache[cacheKeyCurve] = dataCurve;
    } catch (e) {
      // Non bloquant : on continue sans la courbe
      dataCurve = null;
    }
  }

  // Filtrer les PM/BM du jour demandé
  const targetDate = dateForOffset(dayOffset);
  const ymd = targetDate.getFullYear() * 10000 +
              (targetDate.getMonth() + 1) * 100 +
              targetDate.getDate();

  const dayTides = (dataPM.tides || []).filter(t => t[0] === ymd);

  if (dayTides.length === 0) {
    refExtEl.innerHTML = '<span style="color:#999;">Pas de données maree.info pour ce jour</span>';
    const refCtx = document.getElementById('ref-chart');
    if (refCtx) refCtx.style.display = 'none';
    return;
  }

  // Afficher les extremes
  const sorted = dayTides.slice().sort((a, b) => (a[1] * 60 + a[2]) - (b[1] * 60 + b[2]));
  refExtEl.innerHTML = sorted.map(t => {
    const cls = t[4] === 'PM' ? 'pm' : 'bm';
    const hh = String(t[1]).padStart(2, '0');
    const mm = String(t[2]).padStart(2, '0');
    return `<span class="${cls}">${t[4]} ${hh}h${mm} — ${t[3].toFixed(2)} m</span>`;
  }).join('');

  // Dessiner le graphique de référence
  renderRefChart(port, dayOffset, sorted);

  // Extraire la courbe horaire du jour et l'ajouter au graphe principal
  const hourlyPts = dataCurve && dataCurve.hourly && dataCurve.hourly[String(ymd)];
  if (hourlyPts && hourlyPts.length > 0) {
    addRefCurveToMainChart(hourlyPts);
  }
}

function addRefCurveToMainChart(hourlyPts) {
  // hourlyPts = [[heure, hauteur], ...] — 24 points (0h–23h)
  if (!activeChart || !hourlyPts || hourlyPts.length < 2) return;

  const curve = hourlyPts.map(pt => ({ x: pt[0] * 60, y: pt[1] }));

  activeChart.data.datasets.push({
    label: 'maree.info',
    data: curve,
    borderColor: '#e74c3c',
    borderWidth: 2,
    borderDash: [6, 4],
    pointRadius: 2,
    pointHitRadius: 8,
    fill: false,
    tension: 0.4,
    order: -2,
  });

  // Recalculer les bornes Y
  const allY = [];
  for (const ds of activeChart.data.datasets) {
    for (const pt of (ds.data || [])) {
      if (pt && typeof pt.y === 'number') allY.push(pt.y);
    }
  }
  if (allY.length) {
    const hMin = Math.min(...allY);
    const hMax = Math.max(...allY);
    const hMargin = (hMax - hMin) * 0.1 || 0.5;
    activeChart.options.scales.y.min = Math.floor((hMin - hMargin) * 10) / 10;
    activeChart.options.scales.y.max = Math.ceil((hMax + hMargin) * 10) / 10;
  }

  // Légende : afficher maree.info
  activeChart.options.plugins.legend.labels.filter = item =>
    item.text !== 'Zéro' && item.text !== 'Maintenant' && item.text !== 'Niveau actuel';

  // Tooltip pour maree.info
  const origLabel = activeChart.options.plugins.tooltip.callbacks.label;
  activeChart.options.plugins.tooltip.callbacks.label = ctx => {
    if (ctx.dataset.label === 'maree.info')
      return 'Réf : ' + ctx.parsed.y.toFixed(2) + ' m';
    return origLabel ? origLabel(ctx) : ctx.parsed.y.toFixed(2) + ' m';
  };

  activeChart.update();
}

function renderRefChart(port, dayOffset, refTides) {
  const ctx = document.getElementById('ref-chart');
  if (!ctx) return;
  ctx.style.display = 'block';
  if (refChart) { refChart.destroy(); refChart = null; }

  // Données du modèle (comme le graphe principal)
  const { times, heights } = predict(port, dayOffset);
  const modelData = times.map((t, i) => ({ x: t, y: heights[i] }));

  // Points de référence maree.info
  const refPoints = refTides.map(t => ({
    x: t[1] * 60 + t[2],  // minutes depuis minuit
    y: t[3],
    type: t[4],
  }));

  const pmPoints = refPoints.filter(p => p.type === 'PM');
  const bmPoints = refPoints.filter(p => p.type === 'BM');

  // Calculer les bornes Y en incluant les deux séries
  const allY = [...heights, ...refPoints.map(p => p.y)];
  const hMin = Math.min(...allY);
  const hMax = Math.max(...allY);
  const hMargin = (hMax - hMin) * 0.1 || 0.5;
  const yMin = Math.floor((hMin - hMargin) * 10) / 10;
  const yMax = Math.ceil((hMax + hMargin) * 10) / 10;

  refChart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Modèle',
          data: modelData,
          borderColor: 'rgba(41,128,185,0.4)',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          pointHitRadius: 0,
          fill: false,
          tension: 0.3,
        },
        {
          label: 'PM maree.info',
          data: pmPoints.map(p => ({ x: p.x, y: p.y })),
          borderColor: '#d35400',
          backgroundColor: '#d35400',
          pointRadius: 8,
          pointStyle: 'triangle',
          showLine: false,
          pointHitRadius: 12,
        },
        {
          label: 'BM maree.info',
          data: bmPoints.map(p => ({ x: p.x, y: p.y })),
          borderColor: '#2980b9',
          backgroundColor: '#2980b9',
          pointRadius: 8,
          pointStyle: 'triangle',
          rotation: 180,
          showLine: false,
          pointHitRadius: 12,
        },
        {
          label: 'Zéro',
          data: [{ x: 0, y: 0 }, { x: 1440, y: 0 }],
          borderColor: '#aaa',
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
          pointHitRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 3 / 2,
      animation: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: {
            usePointStyle: true,
            font: { size: 11 },
            padding: 12,
            filter: item => item.text !== 'Zéro',
          },
        },
        tooltip: {
          mode: 'nearest',
          axis: 'x',
          intersect: false,
          filter: item => item.dataset.label !== 'Zéro',
          callbacks: {
            title: items => {
              if (!items.length) return '';
              return minutesToHHMM(items[0].parsed.x);
            },
            label: ctx => {
              if (ctx.dataset.label === 'PM maree.info')
                return '▲ PM ref : ' + ctx.parsed.y.toFixed(2) + ' m';
              if (ctx.dataset.label === 'BM maree.info')
                return '▼ BM ref : ' + ctx.parsed.y.toFixed(2) + ' m';
              return ctx.parsed.y.toFixed(2) + ' m';
            },
          },
        },
      },
      scales: {
        x: {
          type: 'linear',
          min: 0,
          max: 1440,
          ticks: {
            font: { size: 11 },
            maxRotation: 0,
            stepSize: 120,
            callback: function(v) {
              const h = Math.round(v / 60);
              return String(h) + 'h';
            },
          },
          grid: { color: 'rgba(0,0,0,0.06)' },
        },
        y: {
          title: { display: true, text: 'Hauteur (m / ZC)', font: { size: 12 } },
          ticks: { font: { size: 11 } },
          grid: { color: 'rgba(0,0,0,0.06)' },
          min: yMin,
          max: yMax,
        },
      },
    },
  });
}

// ═══════════════════════════════════════════════════════════════
//  RENDU DU GRAPHIQUE (Chart.js)
// ═══════════════════════════════════════════════════════════════

function renderChart(port, dayOffset) {
  const ctx = document.getElementById('tide-chart');
  if (!ctx) return;
  if (activeChart) { activeChart.destroy(); activeChart = null; }

  const { times, heights } = predict(port, dayOffset);
  const hMin = Math.min(...heights);
  const hMax = Math.max(...heights);
  const hMargin = (hMax - hMin) * 0.1 || 0.5;
  const yMin = Math.floor((hMin - hMargin) * 10) / 10;
  const yMax = Math.ceil((hMax + hMargin) * 10) / 10;
  const { pm, bm } = findExtremes(port, dayOffset, times, heights);

  const extEl = document.getElementById('extremes');
  if (extEl) {
    const all = [
      ...pm.map(e => ({ ...e, type: 'PM' })),
      ...bm.map(e => ({ ...e, type: 'BM' })),
    ].sort((a, b) => a.t - b.t);
    extEl.innerHTML = all.map(e => {
      const cls = e.type === 'PM' ? 'pm' : 'bm';
      return `<span class="${cls}">${e.type} ${minutesToHHMM(e.t)} — ${e.h.toFixed(2)} m</span>`;
    }).join('');
  }

  const data = times.map((t, i) => ({ x: t, y: heights[i] }));

  const mainColor = port.buggy ? '#c0392b' : port.isNew ? '#2563eb' : '#2980b9';
  const bgColor = port.buggy ? 'rgba(192,57,43,0.08)' : port.isNew ? 'rgba(37,99,235,0.08)' : 'rgba(41,128,185,0.08)';

  let waterData = [];
  let nowPoint = [];
  if (dayOffset === 0) {
    const now = new Date();
    const nowLocalMin = now.getHours() * 60 + now.getMinutes();
    let hNow = harmonicHeightAtMinute(port, 0, nowLocalMin);
    hNow = Math.round(hNow * 1000) / 1000;
    waterData = [{ x: data[0].x, y: hNow }, { x: data[data.length-1].x, y: hNow }];
    nowPoint = [{ x: nowLocalMin, y: hNow }];
  }

  const crosshairPlugin = {
    id: 'crosshair',
    afterDraw(chart) {
      if (chart.tooltip?._active?.length) {
        const x = chart.tooltip._active[0].element.x;
        const yAxis = chart.scales.y;
        const c2 = chart.ctx;
        c2.save();
        c2.beginPath();
        c2.moveTo(x, yAxis.top);
        c2.lineTo(x, yAxis.bottom);
        c2.lineWidth = 1;
        c2.strokeStyle = 'rgba(0,0,0,0.2)';
        c2.setLineDash([3, 3]);
        c2.stroke();
        c2.restore();
      }
    }
  };

  activeChart = new Chart(ctx, {
    type: 'line',
    plugins: [crosshairPlugin],
    data: {
      datasets: [
        {
          label: 'Hauteur',
          data: data,
          borderColor: mainColor,
          backgroundColor: bgColor,
          fill: false,
          pointRadius: 0,
          pointHitRadius: 8,
          borderWidth: 2.5,
          tension: 0.3,
        },
        {
          label: 'Zéro',
          data: [{ x: data[0].x, y: 0 }, { x: data[data.length-1].x, y: 0 }],
          borderColor: '#aaa',
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
          pointHitRadius: 0,
          fill: false,
        },
        ...(waterData.length ? [{
          label: 'Niveau actuel',
          data: waterData,
          borderColor: 'transparent',
          borderWidth: 0,
          pointRadius: 0,
          pointHitRadius: 0,
          backgroundColor: 'rgba(52,152,219,0.25)',
          fill: 'start',
        }] : []),
        ...(nowPoint.length ? [{
          label: 'Maintenant',
          data: nowPoint,
          borderColor: '#e74c3c',
          backgroundColor: '#e74c3c',
          pointRadius: 7,
          pointStyle: 'circle',
          showLine: false,
          pointHitRadius: 12,
          order: -1,
        }] : []),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 3 / 2,
      animation: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: {
            usePointStyle: true,
            font: { size: 11 },
            padding: 12,
            filter: item => item.text !== 'Zéro' && item.text !== 'Maintenant' && item.text !== 'Niveau actuel',
          },
        },
        tooltip: {
          mode: 'nearest',
          axis: 'x',
          intersect: false,
          filter: item => item.dataset.label !== 'Zéro' && item.dataset.label !== 'Maintenant' && item.dataset.label !== 'Niveau actuel',
          callbacks: {
            title: items => {
              if (!items.length) return '';
              return minutesToHHMM(items[0].parsed.x);
            },
            label: ctx => {
              if (ctx.dataset.label === 'PM')
                return '▲ PM : ' + ctx.parsed.y.toFixed(2) + ' m';
              if (ctx.dataset.label === 'BM')
                return '▼ BM : ' + ctx.parsed.y.toFixed(2) + ' m';
              return ctx.parsed.y.toFixed(2) + ' m';
            },
          },
        },
      },
      scales: {
        x: {
          type: 'linear',
          min: 0,
          max: 1440,
          ticks: {
            font: { size: 11 },
            maxRotation: 0,
            stepSize: 120,
            callback: function(v) {
              const h = Math.round(v / 60);
              return String(h) + 'h';
            },
          },
          grid: { color: 'rgba(0,0,0,0.06)' },
        },
        y: {
          title: { display: true, text: 'Hauteur (m / ZC)', font: { size: 12 } },
          ticks: { font: { size: 11 } },
          grid: { color: 'rgba(0,0,0,0.06)' },
          min: yMin,
          max: yMax,
        },
      },
    },
  });
}

// ═══════════════════════════════════════════════════════════════
//  DÉMARRAGE
// ═══════════════════════════════════════════════════════════════
init();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Éditeur interactif de ports de marée")
    parser.add_argument(
        "--har-dir", default="har_ports", help="Répertoire des fichiers .har"
    )
    parser.add_argument(
        "--atlas-base",
        default="MARC_L1-ATLAS-AHRMONIQUES",
        help="Répertoire parent des atlas",
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port HTTP (défaut: 8000)"
    )
    args = parser.parse_args()

    # Configurer le handler
    EditorHandler.har_dir = args.har_dir
    EditorHandler.atlas_base = args.atlas_base

    # Vérifications
    har_path = Path(args.har_dir)
    if not har_path.exists():
        print(f"Erreur : répertoire {args.har_dir} introuvable")
        sys.exit(1)

    atlas_path = Path(args.atlas_base)
    if not atlas_path.exists():
        print(f"Attention : répertoire atlas {args.atlas_base} introuvable")
        print(f"  La création de nouveaux ports ne fonctionnera pas.")

    n_har = len(list(har_path.glob("*.har")))
    print(f"Éditeur de marées")
    print(f"  Répertoire HAR : {args.har_dir}/ ({n_har} fichiers)")
    print(f"  Atlas SHOM     : {args.atlas_base}/")
    print(f"  Serveur HTTP   : http://localhost:{args.port}/")
    print(f"\n  Ouvrir dans le navigateur et cliquer « + Ajouter un port »")
    print(f"  Ctrl+C pour arrêter\n")

    server = HTTPServer(("", args.port), EditorHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")
        server.server_close()


if __name__ == "__main__":
    main()
