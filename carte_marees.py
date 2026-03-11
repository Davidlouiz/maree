#!/usr/bin/env python3
"""
Génère une carte interactive HTML des ports de marée.

Le calcul des marées est entièrement réalisé en JavaScript côté client.
Le script Python ne fait que :
  1. Scanner le répertoire des fichiers .har
  2. Exporter les tables de constantes utide en JSON
  3. Générer le HTML avec ces données embarquées

À l'ouverture de la page, le JavaScript :
  1. Récupère chaque fichier .har via fetch()
  2. Parse les harmoniques (nom, amplitude, phase, z0, lat/lon)
  3. Calcule les corrections nodales (F, U, V) via un port fidèle de utide
  4. Prédit la marée heure par heure et trace la courbe

Usage:
    python carte_marees.py [--har-dir har_ports] [--output carte_marees.html]
"""

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from maree import _SHOM_TO_UTIDE, _EXTRA_CONSTITUENTS


# ─────────────────────────────────────────────────────────────────────────────
# Export des constantes utide pour le moteur JS
# ─────────────────────────────────────────────────────────────────────────────


def export_utide_json() -> str:
    """Exporte les tables utide nécessaires au calcul JS (F, U, V)."""
    from utide import ut_constants

    c = ut_constants.const
    s = ut_constants.sat
    sh = ut_constants.shallow

    constituents = []
    for i in range(len(c.name)):
        entry = {
            "n": c.name[i],
            "f": round(float(c.freq[i]), 12),
        }
        # Doodson numbers only for direct constituents (NaN for shallow water)
        if not np.isnan(c.doodson[i][0]):
            entry["d"] = [round(float(x), 2) for x in c.doodson[i]]

        semi = c.semi[i]
        if not np.isnan(semi) and semi != 0:
            entry["s"] = round(float(semi), 6)

        ns = c.nshallow[i]
        if not np.isnan(ns):
            entry["ns"] = int(ns)
            entry["is"] = int(c.ishallow[i]) - 1  # 0-based

        constituents.append(entry)

    satellites = []
    for i in range(len(s.iconst)):
        satellites.append(
            [
                int(s.iconst[i]) - 1,
                [round(float(x), 2) for x in s.deldood[i]],
                round(float(s.phcorr[i]), 6),
                round(float(s.amprat[i]), 8),
                int(s.ilatfac[i]),
            ]
        )

    shallows = []
    for i in range(len(sh.iname)):
        shallows.append(
            [
                int(sh.iname[i]) - 1,
                round(float(sh.coef[i]), 6),
            ]
        )

    return json.dumps(
        {
            "c": constituents,
            "s": satellites,
            "sh": shallows,
            "nf": len(c.isat),
        },
        separators=(",", ":"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Export des mappings SHOM → utide et constituants extra
# ─────────────────────────────────────────────────────────────────────────────


def export_mappings_json() -> tuple[str, str]:
    """Exporte _SHOM_TO_UTIDE et _EXTRA_CONSTITUENTS en JSON."""
    shom = {}
    for k, v in _SHOM_TO_UTIDE.items():
        if v is None:
            shom[k] = None
        elif v != k:
            shom[k] = v

    extra = {}
    for k, (speed, decomp) in _EXTRA_CONSTITUENTS.items():
        extra[k] = {
            "w": round(speed, 8),
            "d": [[pname, coef] for pname, coef in decomp],
        }

    return (
        json.dumps(shom, separators=(",", ":")),
        json.dumps(extra, separators=(",", ":")),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scan des fichiers HAR
# ─────────────────────────────────────────────────────────────────────────────


def scan_har_files(har_dir: str) -> list[dict]:
    """Scanne le répertoire HAR et retourne la liste des fichiers."""
    har_path = Path(har_dir)
    if not har_path.exists():
        print(f"Répertoire {har_dir} introuvable")
        sys.exit(1)

    files = []
    seen = set()
    for f in sorted(har_path.glob("*.har")):
        if f.name not in seen:
            seen.add(f.name)
            files.append(
                {
                    "filename": f.name,
                    "buggy": f.name.startswith("_"),
                }
            )
    return files


# ─────────────────────────────────────────────────────────────────────────────
# Template HTML
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Carte des marées — Ports de France</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  #map { width: 100vw; height: 100vh; }

  .popup-content { width: 620px; max-width: 92vw; }
  .popup-content h3 { margin: 0 0 2px 0; font-size: 17px; color: #333; }
  .popup-content .info { font-size: 12px; color: #666; margin-bottom: 2px; }
  .popup-content .buggy-tag { color: #c00; font-weight: bold; }
  .popup-content .chart-wrap { position: relative; width: 600px; max-width: 90vw; height: 280px; }
  .popup-content canvas { display: block; }
  .leaflet-popup-content { margin: 10px 12px; min-width: 620px; }

  .nav-bar {
    display: flex; align-items: center; justify-content: center;
    gap: 10px; margin: 4px 0 2px 0;
  }
  .nav-bar button {
    border: none; background: #eee; border-radius: 4px;
    padding: 3px 14px; font-size: 18px; cursor: pointer; line-height: 1;
  }
  .nav-bar button:hover { background: #ddd; }
  .nav-bar .date-label {
    font-size: 14px; font-weight: 600; min-width: 270px; text-align: center;
  }

  .extremes-list {
    display: flex; flex-wrap: wrap; gap: 4px 14px;
    font-size: 12px; margin-bottom: 4px; color: #444;
  }
  .extremes-list .pm { color: #d35400; font-weight: 600; }
  .extremes-list .bm { color: #2980b9; font-weight: 600; }

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

  .loading-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(255,255,255,0.85); z-index: 10000;
    display: flex; align-items: center; justify-content: center;
    flex-direction: column; font-family: inherit;
  }
  .loading-overlay .spinner {
    width: 40px; height: 40px; border: 4px solid #ddd;
    border-top-color: #2d8a4e; border-radius: 50%;
    animation: spin 0.8s linear infinite; margin-bottom: 12px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-overlay .msg { font-size: 15px; color: #555; }
</style>
</head>
<body>
<div id="loading" class="loading-overlay">
  <div class="spinner"></div>
  <div class="msg" id="loading-msg">Chargement des fichiers harmoniques…</div>
</div>
<div id="map"></div>
<script>
// ═══════════════════════════════════════════════════════════════
//  CONSTANTES UTIDE (exportées depuis la bibliothèque Python utide)
//  c[i] = {n:name, f:freq_cph, d:doodson[6], s?:semi, ns?:nshallow, is?:ishallow}
//  s[i] = [iconst, deldood[3], phcorr, amprat, ilatfac]
//  sh[i] = [iname, coef]
// ═══════════════════════════════════════════════════════════════
const UTIDE = __UTIDE_JSON__;

// ═══════════════════════════════════════════════════════════════
//  MAPPING NOMS SHOM → UTIDE  +  CONSTITUANTS EXTRA
// ═══════════════════════════════════════════════════════════════
const SHOM_TO_UTIDE = __SHOM_JSON__;
const EXTRA_CONSTITUENTS = __EXTRA_JSON__;

// ═══════════════════════════════════════════════════════════════
//  LISTE DES FICHIERS HAR
// ═══════════════════════════════════════════════════════════════
const HAR_DIR = '__HAR_DIR__';
const HAR_FILES = __HAR_FILES_JSON__;

// ═══════════════════════════════════════════════════════════════
//  INDEX DES NOMS UTIDE
// ═══════════════════════════════════════════════════════════════
const UTIDE_NAMES = UTIDE.c.map(c => c.n);
const UTIDE_NAME_IDX = {};
UTIDE_NAMES.forEach((n, i) => UTIDE_NAME_IDX[n] = i);

// Pré-calcul : quels constituants sont « shallow water »
const NCONST = UTIDE.c.length;
const IS_SHALLOW = new Array(NCONST);
for (let i = 0; i < NCONST; i++) {
  IS_SHALLOW[i] = UTIDE.c[i].ns !== undefined;
}

// ═══════════════════════════════════════════════════════════════
//  ASTRONOMIE  (port fidèle de utide/astronomy.py ut_astron)
//
//  Calcule les 6 arguments astronomiques fondamentaux (en cycles) :
//    tau = temps lunaire
//    s   = longitude moyenne de la Lune
//    h   = longitude moyenne du Soleil
//    p   = longitude du périgée lunaire
//    np  = -longitude du nœud ascendant lunaire
//    pp  = longitude du périhélie solaire
// ═══════════════════════════════════════════════════════════════

const _ASTRO_COEFS = [
  [270.434164, 13.1763965268, -0.0000850,  0.000000039],   // s
  [279.696678,  0.9856473354,  0.00002267, 0.000000000],   // h
  [334.329556,  0.1114040803, -0.0007739, -0.00000026],    // p
  [-259.183275, 0.0529539222, -0.0001557, -0.000000050],   // np
  [281.220844,  0.0000470684,  0.0000339,  0.000000070],   // pp
];

function utAstron(jd) {
  const daten = 693595.5;
  const d = jd - daten;
  const D = d / 10000;
  const D2 = D * D;
  const D3 = D2 * D;

  const astro = new Float64Array(6);
  const ader  = new Float64Array(6);

  // Compute s, h, p, np, pp (indices 1..5 in astro)
  for (let i = 0; i < 5; i++) {
    const c = _ASTRO_COEFS[i];
    const val = c[0] + c[1] * d + c[2] * D2 + c[3] * D3;
    astro[i + 1] = (val / 360) % 1;

    const dval = c[1] + c[2] * 2e-4 * D + c[3] * 3e-4 * D2;
    ader[i + 1] = dval / 360;
  }

  // tau = fractional day + h - s
  astro[0] = (jd % 1) + astro[2] - astro[1];
  ader[0] = 1.0 + ader[2] - ader[1];

  return { astro, ader };
}

// ═══════════════════════════════════════════════════════════════
//  CALCUL FUV  (port fidèle de utide/harmonics.py FUV)
//
//  Calcule pour chaque constituant utide (146) à l'instant t_ord :
//    F = correction nodale d'amplitude (sans unité)
//    U = correction nodale de phase (cycles)
//    V = argument astronomique de Greenwich (cycles)
//
//  Équivalent à ngflgs = [0,0,0,0] (exact nodsat + exact Greenwich)
// ═══════════════════════════════════════════════════════════════

function computeAllFUV(t_ord, lat) {
  const { astro } = utAstron(t_ord);
  const TWO_PI = 2 * Math.PI;

  // ── Corrections nodales (F, U) via satellites ──
  if (Math.abs(lat) < 5) lat = Math.sign(lat || 1) * 5;
  const slat = Math.sin(lat * Math.PI / 180);

  const sats = UTIDE.s;
  const nsat = sats.length;

  // Accumuler les contributions satellites dans F (complexe)
  const Fr = new Float64Array(NCONST).fill(1);
  const Fi = new Float64Array(NCONST).fill(0);

  for (let i = 0; i < nsat; i++) {
    let r = sats[i][3];  // amprat
    const ilatfac = sats[i][4];
    if (ilatfac === 1) r *= 0.36309 * (1.0 - 5.0 * slat * slat) / slat;
    else if (ilatfac === 2) r *= 2.59808 * slat;

    // Phase satellite: dot(deldood, astro[3:6]) + phcorr, en cycles
    const dd = sats[i][1];
    let u = dd[0] * astro[3] + dd[1] * astro[4] + dd[2] * astro[5] + sats[i][2];
    u = u % 1;  // fmod (rem)

    const angle = TWO_PI * u;
    const ic = sats[i][0];  // iconst, 0-based
    Fr[ic] += r * Math.cos(angle);
    Fi[ic] += r * Math.sin(angle);
  }

  const F = new Float64Array(NCONST);
  const U = new Float64Array(NCONST);
  for (let i = 0; i < NCONST; i++) {
    F[i] = Math.sqrt(Fr[i] * Fr[i] + Fi[i] * Fi[i]);
    U[i] = Math.atan2(Fi[i], Fr[i]) / TWO_PI;  // cycles
  }

  // Shallow water : F et U dérivés des parents
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

  // ── Argument astronomique V ──
  const V = new Float64Array(NCONST);

  // Constituants directs : V = dot(doodson, astro) + semi
  for (let i = 0; i < NCONST; i++) {
    if (IS_SHALLOW[i]) continue;
    const ci = UTIDE.c[i];
    let v = 0;
    for (let j = 0; j < 6; j++) v += ci.d[j] * astro[j];
    if (ci.s) v += ci.s;
    v = v % 1;
    V[i] = v;
  }

  // Shallow water : V dérivé des parents
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
//  PARSEUR DE FICHIERS .har
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
//  Mappe les noms SHOM → indices utide, calcule les harmoniques
//  effectives (amplitude et phase pré-corrigées à t0).
// ═══════════════════════════════════════════════════════════════

function resolveUtideName(shomName) {
  if (SHOM_TO_UTIDE.hasOwnProperty(shomName)) return SHOM_TO_UTIDE[shomName];
  if (UTIDE_NAME_IDX.hasOwnProperty(shomName)) return shomName;
  return shomName;
}

function datetimeToOrdinal(date) {
  const epochOrdinal = 719163;  // ordinal Python de 1970-01-01
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

  // Cache des données FUV des parents (pour les constituants extra)
  const parentCache = {};

  for (const [shomName, [amp, phaseG]] of Object.entries(harData.constituents)) {
    if (shomName === 'Z0') continue;

    const utideName = resolveUtideName(shomName);

    // ── Constituant utide connu ──
    if (utideName !== null && UTIDE_NAME_IDX.hasOwnProperty(utideName)) {
      const idx = UTIDE_NAME_IDX[utideName];
      const speed = UTIDE.c[idx].f * DEG;  // cycles/h → °/h
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

    // ── Constituant extra (hors utide) ──
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
    // Constituant inconnu → ignoré
  }

  return {
    nom: harData.nom,
    lat: harData.lat,
    lon: harData.lon,
    z0: harData.z0 || 0,
    filename: harData.filename,
    buggy: harData.filename.startsWith('_'),
    c: cList,
  };
}

// ═══════════════════════════════════════════════════════════════
//  PRÉDICTION HARMONIQUE
// ═══════════════════════════════════════════════════════════════

function predict(port, dayOffset) {
  const STEP = 10;
  const N = 24 * 60 / STEP + 1;
  const baseH = dayOffset * 24;
  const DEG2RAD = Math.PI / 180;
  const nc = port.c.length;
  const times = new Array(N);
  const heights = new Array(N);

  for (let i = 0; i < N; i++) {
    const dt = baseH + i * STEP / 60;
    let h = port.z0;
    for (let j = 0; j < nc; j++) {
      const c = port.c[j];
      h += c.a * Math.cos((c.w * dt + c.p) * DEG2RAD);
    }
    times[i] = i * STEP;
    heights[i] = Math.round(h * 1000) / 1000;
  }
  return { times, heights };
}

function findExtremes(times, heights) {
  const pm = [], bm = [];
  for (let i = 1; i < heights.length - 1; i++) {
    if (heights[i] > heights[i-1] && heights[i] >= heights[i+1])
      pm.push({ t: times[i], h: heights[i] });
    else if (heights[i] < heights[i-1] && heights[i] <= heights[i+1])
      bm.push({ t: times[i], h: heights[i] });
  }
  return { pm, bm };
}

function pad2(n) { return String(n).padStart(2, '0'); }
function minutesToHHMM(m) { return pad2(Math.floor(m/60)) + 'h' + pad2(m%60); }

// ═══════════════════════════════════════════════════════════════
//  CHARGEMENT PRINCIPAL
// ═══════════════════════════════════════════════════════════════

const PORTS = [];
let T0, T0_ORD;

async function init() {
  const loadMsg = document.getElementById('loading-msg');

  // t0 = aujourd'hui 0h UTC
  const now = new Date();
  T0 = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  T0_ORD = datetimeToOrdinal(T0);

  // Chargement des fichiers HAR en parallèle
  loadMsg.textContent = `Chargement de ${HAR_FILES.length} fichiers .har…`;
  await new Promise(r => setTimeout(r, 10));

  const results = await Promise.allSettled(
    HAR_FILES.map(hf =>
      fetch(HAR_DIR + '/' + hf.filename)
        .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(text => ({ text, hf }))
    )
  );

  loadMsg.textContent = 'Calcul des corrections astronomiques…';
  await new Promise(r => setTimeout(r, 10));

  let loaded = 0;
  for (const result of results) {
    if (result.status !== 'fulfilled') continue;
    const { text, hf } = result.value;
    const har = parseHAR(text, hf.filename);
    if (!har) continue;

    // FUV à la latitude exacte du port
    const portFUV = computeAllFUV(T0_ORD, har.lat);
    const port = preparePort(har, portFUV, T0_ORD);
    PORTS.push(port);
    loaded++;
  }

  loadMsg.textContent = `${loaded} ports chargés. Initialisation de la carte…`;
  await new Promise(r => setTimeout(r, 10));

  initMap();
  document.getElementById('loading').style.display = 'none';
}

// ═══════════════════════════════════════════════════════════════
//  CARTE LEAFLET
// ═══════════════════════════════════════════════════════════════

let map;
let activeChart = null;
let activePortIdx = null;
let activeDayOffset = 0;

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
    iconSize: [20, 28], iconAnchor: [10, 28], popupAnchor: [0, -28],
  });
}

function initMap() {
  const greenIcon = makeIcon('#2d8a4e');
  const redIcon   = makeIcon('#c0392b');

  map = L.map('map').setView([47.5, -2.5], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap', maxZoom: 18,
  }).addTo(map);

  PORTS.forEach((port, idx) => {
    const icon = port.buggy ? redIcon : greenIcon;
    const marker = L.marker([port.lat, port.lon], { icon }).addTo(map);
    marker.bindPopup('', { maxWidth: 660, minWidth: 620 });

    marker.on('popupopen', function() {
      const buggyTag = port.buggy
        ? '<span class="buggy-tag"> ⚠ BUGGY</span>' : '';
      const content = `
        <div class="popup-content">
          <h3>${port.nom}${buggyTag}</h3>
          <div class="info">
            ${port.lat.toFixed(3)}°N, ${port.lon.toFixed(3)}°
            &nbsp;|&nbsp; Z0 = ${port.z0.toFixed(2)} m
            &nbsp;|&nbsp; ${port.c.length} harmoniques
            &nbsp;|&nbsp; <span style="font-size:11px;color:#999">${port.filename}</span>
          </div>
          <div class="nav-bar">
            <button onclick="renderChart(${idx}, activeDayOffset - 1)">◀</button>
            <span class="date-label" id="date-lbl-${idx}">${dateLabel(0)}</span>
            <button onclick="renderChart(${idx}, activeDayOffset + 1)">▶</button>
          </div>
          <div class="extremes-list" id="extremes-${idx}"></div>
          <div class="chart-wrap"><canvas id="chart-${idx}"></canvas></div>
        </div>
      `;
      marker.getPopup().setContent(content);
      activePortIdx = idx;
      activeDayOffset = 0;
      setTimeout(() => renderChart(idx, 0), 50);
    });

    marker.on('popupclose', function() {
      if (activeChart) { activeChart.destroy(); activeChart = null; }
      activePortIdx = null;
    });
  });

  // Légende
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = function() {
    const div = L.DomUtil.create('div', 'legend');
    const nOK  = PORTS.filter(p => !p.buggy).length;
    const nBug = PORTS.filter(p => p.buggy).length;
    div.innerHTML = `
      <b>Ports de marée</b><br>
      <i class="green"></i> OK (${nOK})<br>
      ${nBug > 0 ? '<i class="red"></i> Buggy (' + nBug + ')<br>' : ''}
      <span style="font-size:11px;color:#888">Clic = courbe &nbsp;◀ ▶ = jour</span>
    `;
    return div;
  };
  legend.addTo(map);

  if (PORTS.length > 0) {
    map.fitBounds(
      L.latLngBounds(PORTS.map(p => [p.lat, p.lon])),
      { padding: [30, 30] }
    );
  }
}

// ═══════════════════════════════════════════════════════════════
//  RENDU DU GRAPHIQUE (Chart.js)
// ═══════════════════════════════════════════════════════════════

function renderChart(idx, dayOffset) {
  const port = PORTS[idx];
  const canvasId = 'chart-' + idx;
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (activeChart) { activeChart.destroy(); activeChart = null; }

  activeDayOffset = dayOffset;
  activePortIdx = idx;

  const dateEl = document.getElementById('date-lbl-' + idx);
  if (dateEl) dateEl.textContent = dateLabel(dayOffset);

  const { times, heights } = predict(port, dayOffset);
  const { pm, bm } = findExtremes(times, heights);

  const extEl = document.getElementById('extremes-' + idx);
  if (extEl) {
    const all = [
      ...pm.map(e => ({ ...e, type: 'PM' })),
      ...bm.map(e => ({ ...e, type: 'BM' })),
    ].sort((a, b) => a.t - b.t);
    extEl.innerHTML = all.map(e => {
      const cls = e.type === 'PM' ? 'pm' : 'bm';
      const arrow = e.type === 'PM' ? '▲' : '▼';
      return `<span class="${cls}">${arrow} ${e.type} ${minutesToHHMM(e.t)} — ${e.h.toFixed(2)} m</span>`;
    }).join('');
  }

  const iso = dateISO(dayOffset);
  function minToDate(m) {
    return new Date(iso + 'T' + pad2(Math.floor(m/60)) + ':' + pad2(m%60) + ':00Z');
  }
  const data   = times.map((t, i) => ({ x: minToDate(t), y: heights[i] }));
  const pmData = pm.map(e => ({ x: minToDate(e.t), y: e.h }));
  const bmData = bm.map(e => ({ x: minToDate(e.t), y: e.h }));

  const mainColor = port.buggy ? '#c0392b' : '#2d8a4e';
  const bgColor   = port.buggy ? 'rgba(192,57,43,0.08)' : 'rgba(45,138,78,0.08)';

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
          fill: true,
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
        {
          label: 'PM',
          data: pmData,
          borderColor: '#d35400',
          backgroundColor: '#d35400',
          pointRadius: 7,
          pointStyle: 'triangle',
          showLine: false,
          pointHitRadius: 10,
        },
        {
          label: 'BM',
          data: bmData,
          borderColor: '#2980b9',
          backgroundColor: '#2980b9',
          pointRadius: 7,
          pointStyle: 'triangle',
          pointRotation: 180,
          showLine: false,
          pointHitRadius: 10,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
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
              const d = new Date(items[0].parsed.x);
              return pad2(d.getUTCHours()) + 'h' + pad2(d.getUTCMinutes()) + ' UTC';
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
          type: 'time',
          time: { unit: 'hour', stepSize: 2, displayFormats: { hour: 'HH:mm' } },
          ticks: {
            font: { size: 11 },
            maxRotation: 0,
            callback: function(v) {
              return pad2(new Date(v).getUTCHours()) + 'h';
            },
          },
          grid: { color: 'rgba(0,0,0,0.06)' },
        },
        y: {
          title: { display: true, text: 'Hauteur (m / ZC)', font: { size: 12 } },
          ticks: { font: { size: 11 } },
          grid: { color: 'rgba(0,0,0,0.06)' },
        },
      },
    },
  });
}

// ═══════════════════════════════════════════════════════════════
//  DÉMARRAGE
// ═══════════════════════════════════════════════════════════════
init().catch(err => {
  console.error('Erreur init:', err);
  document.getElementById('loading-msg').textContent = 'Erreur : ' + err.message;
});
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Génération HTML
# ─────────────────────────────────────────────────────────────────────────────


def generate_html(
    har_files: list[dict],
    har_dir: str,
    utide_json: str,
    shom_json: str,
    extra_json: str,
    output_path: str,
):
    """Génère le fichier HTML autonome."""
    har_files_json = json.dumps(har_files, ensure_ascii=False, separators=(",", ":"))

    html = (
        HTML_TEMPLATE.replace("__UTIDE_JSON__", utide_json)
        .replace("__SHOM_JSON__", shom_json)
        .replace("__EXTRA_JSON__", extra_json)
        .replace("__HAR_DIR__", har_dir)
        .replace("__HAR_FILES_JSON__", har_files_json)
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = len(html.encode("utf-8")) / 1024
    print(f"  Carte générée : {output_path} ({size_kb:.0f} Ko)")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Carte interactive des marées (calcul 100%% JavaScript)"
    )
    parser.add_argument(
        "--har-dir", default="har_ports", help="Répertoire des fichiers .har"
    )
    parser.add_argument(
        "--output", default="carte_marees.html", help="Fichier HTML de sortie"
    )
    args = parser.parse_args()

    print(f"Scan des fichiers .har dans {args.har_dir}/ ...")
    har_files = scan_har_files(args.har_dir)
    print(f"  → {len(har_files)} fichiers trouvés")

    print("Export des constantes utide ...")
    utide_json = export_utide_json()
    print(f"  → {len(utide_json) / 1024:.1f} Ko de données harmoniques")

    print("Export des mappings SHOM/extra ...")
    shom_json, extra_json = export_mappings_json()

    print("Génération de la carte ...")
    generate_html(
        har_files, args.har_dir, utide_json, shom_json, extra_json, args.output
    )

    n_ok = len([f for f in har_files if not f["buggy"]])
    n_bug = len([f for f in har_files if f["buggy"]])
    print(f"  → {len(har_files)} ports ({n_ok} OK + {n_bug} buggy)")
    print(f"\nLe HTML est autonome : ouvrir avec un serveur HTTP local :")
    print(f"  python -m http.server 8000")
    print(f"  → http://localhost:8000/{args.output}")


if __name__ == "__main__":
    main()
