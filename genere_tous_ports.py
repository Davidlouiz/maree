#!/usr/bin/env python3
"""
Génère les fichiers .har pour tous les ports de France métropolitaine
(Dunkerque → Saint-Jean-de-Luz) et valide contre maree.info.

Usage:
    python genere_tous_ports.py                  # génère + valide tout
    python genere_tous_ports.py --genere-only    # génère sans valider
    python genere_tous_ports.py --valide-only    # valide HAR existants
    python genere_tous_ports.py --port Brest     # un seul port

Sortie:
    har_ports/         — fichiers .har générés
    rapport_marees.txt — rapport de validation (différences)
"""

import argparse
import os
import re
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timezone, timedelta, date
from html import unescape
from pathlib import Path

warnings.filterwarnings("ignore")

# S'assurer qu'on importe depuis le répertoire courant
sys.path.insert(0, str(Path(__file__).parent))

from genere_har import extract_constituents, find_best_atlas, write_har
from maree import Maree

# ─────────────────────────────────────────────────────────────────────────────
# Base de données des ports maree.info
# ─────────────────────────────────────────────────────────────────────────────
# Format: (maree_info_id, nom, latitude, longitude)
# Coordonnées en degrés décimaux (ouest = négatif)
# Sources: maree.info, SHOM

PORTS = [
    # ══ Mer du Nord ══
    (3, "Dunkerque", 51.050, 2.367),
    (4, "Gravelines", 51.017, 2.100),
    (5, "Calais", 50.967, 1.867),
    (6, "Wissant", 50.883, 1.667),
    (7, "Boulogne-sur-Mer", 50.733, 1.583),
    (8, "Le Touquet", 50.517, 1.583),
    (9, "Berck Plage - Fort Mahon", 50.350, 1.517),
    # ══ Manche Est ══
    (150, "Baie de Somme (Le Crotoy)", 50.217, 1.633),
    (11, "Cayeux-sur-Mer", 50.183, 1.500),
    (12, "Le Tréport", 50.067, 1.367),
    (14, "Dieppe", 49.933, 1.083),
    (15, "Saint-Valery-en-Caux", 49.867, 0.717),
    (16, "Fécamp", 49.767, 0.367),
    (17, "Etretat", 49.717, 0.200),
    (18, "Le Havre-Antifer", 49.667, 0.150),
    (19, "Le Havre", 49.483, 0.100),
    (22, "Honfleur", 49.417, 0.233),
    (23, "Trouville / Deauville", 49.367, 0.067),
    (24, "Dives-sur-Mer", 49.283, -0.100),
    (25, "Ouistreham", 49.283, -0.250),
    (26, "Courseulles-sur-Mer", 49.333, -0.467),
    (27, "Arromanches-Les-Bains", 49.350, -0.617),
    (28, "Port-en-Bessin", 49.350, -0.750),
    (29, "Grandcamp", 49.383, -1.050),
    (30, "Iles Saint-Marcouf", 49.500, -1.133),
    (31, "Saint-Vaast-La-Hougue", 49.583, -1.267),
    (32, "Barfleur", 49.667, -1.267),
    (33, "Cherbourg", 49.650, -1.617),
    # ══ Manche Ouest ══
    (34, "Omonville-la-Rogue", 49.717, -1.833),
    (35, "Goury", 49.717, -1.950),
    (37, "Diélette", 49.550, -1.867),
    (38, "Carteret", 49.367, -1.783),
    (39, "Portbail", 49.333, -1.733),
    (41, "Saint-Germain-sur-Ay", 49.217, -1.633),
    (43, "Pointe d'Agon", 49.000, -1.583),
    (45, "Granville", 48.833, -1.600),
    (47, "Iles Chausey (Grande-Ile)", 48.867, -1.833),
    (48, "Cancale", 48.667, -1.850),
    (52, "Saint-Malo", 48.650, -2.000),
    (53, "Ile des Hébihens", 48.617, -2.133),
    (54, "Saint-Cast", 48.633, -2.250),
    (55, "Erquy", 48.633, -2.467),
    (56, "Dahouet", 48.583, -2.567),
    (57, "Baie de Saint-Brieuc (Le Légué)", 48.517, -2.733),
    (58, "Binic", 48.600, -2.833),
    (59, "Saint-Quay-Portrieux", 48.683, -2.817),
    (60, "Ile de Bréhat", 48.850, -3.000),
    (61, "Les Héaux-de-Bréhat", 48.883, -3.083),
    (62, "Paimpol", 48.783, -3.050),
    (63, "Lézardrieux", 48.783, -3.100),
    (64, "Port-Béni", 48.817, -3.200),
    (65, "Tréguier", 48.783, -3.233),
    (66, "Perros-Guirec", 48.817, -3.433),
    (67, "Ploumanac'h", 48.833, -3.483),
    (68, "Trébeurden", 48.767, -3.567),
    (157, "Locquemeau", 48.733, -3.583),
    (69, "Locquirec", 48.683, -3.650),
    (70, "Anse de Primel", 48.717, -3.817),
    (71, "Baie de Morlaix - Carantec", 48.683, -3.900),
    (72, "Roscoff", 48.717, -3.983),
    # ══ Pointe Bretagne ══
    (73, "Brignogan-Plage", 48.667, -4.333),
    (74, "Aber Wrac'h", 48.600, -4.567),
    (75, "L'Aber Benoît", 48.583, -4.600),
    (76, "Portsall", 48.567, -4.700),
    (77, "L'Aber Ildut - Lanildut", 48.467, -4.750),
    (78, "Ile d'Ouessant (Baie de Lampaul)", 48.450, -5.100),
    (79, "Ile Molène", 48.400, -4.967),
    (80, "Le Conquet", 48.367, -4.783),
    (81, "Trez-Hir", 48.367, -4.633),
    (82, "Brest", 48.383, -4.500),
    (83, "Camaret-sur-Mer", 48.283, -4.600),
    (84, "Morgat", 48.217, -4.500),
    (85, "Douarnenez", 48.100, -4.333),
    (86, "Ile de Sein", 48.033, -4.850),
    (87, "Audierne", 48.017, -4.533),
    (88, "Penmarc'h / Saint Guénolé", 47.817, -4.383),
    (89, "Le Guilvinec", 47.800, -4.283),
    (90, "Lesconil", 47.800, -4.217),
    (91, "Loctudy", 47.833, -4.167),
    (92, "Bénodet", 47.867, -4.117),
    # ══ Bretagne Sud ══
    (93, "Concarneau", 47.867, -3.917),
    (94, "Penfret (Iles de Glénan)", 47.733, -3.950),
    (155, "Port Manec'h", 47.800, -3.733),
    (151, "Le Pouldu", 47.767, -3.533),
    (95, "Lorient", 47.733, -3.367),
    (97, "Port-Louis (Locmalo)", 47.717, -3.350),
    (98, "Ile de Groix (Port-Tudy)", 47.650, -3.450),
    (99, "Etel", 47.650, -3.200),
    (100, "Quiberon (Port-Maria)", 47.483, -3.117),
    (101, "Belle-Ile (Le Palais)", 47.350, -3.150),
    (102, "Quiberon (Port-Haliguen)", 47.483, -3.100),
    (103, "La Trinité-sur-Mer", 47.583, -3.017),
    (105, "Auray (St-Goustan)", 47.667, -2.983),
    (154, "Locmariaquer", 47.567, -2.933),
    (106, "Arradon", 47.617, -2.817),
    (107, "Vannes", 47.650, -2.750),
    (108, "Saint-Armel (Le Passage)", 47.583, -2.683),
    (109, "Le Logeo", 47.533, -2.800),
    (104, "Port-Navalo", 47.550, -2.917),
    (156, "Port du Crouesty", 47.533, -2.900),
    (110, "Pénerf", 47.500, -2.633),
    (111, "Tréhiguier", 47.517, -2.467),
    (112, "Hoëdic", 47.333, -2.867),
    (113, "Houat", 47.383, -2.950),
    (114, "Le Croisic", 47.300, -2.517),
    (115, "Le Pouliguen", 47.267, -2.433),
    (116, "Pornichet", 47.250, -2.350),
    (117, "Saint-Nazaire", 47.267, -2.200),
    (118, "Pointe de Saint-Gildas", 47.133, -2.233),
    (119, "Pornic", 47.117, -2.100),
    # ══ Atlantique ══
    (120, "Noirmoutier (L'Herbaudière)", 47.017, -2.300),
    (121, "Fromentine Bouée", 46.883, -2.167),
    (122, "Fromentine Port", 46.883, -2.150),
    (123, "Ile d'Yeu (Port-Joinville)", 46.733, -2.350),
    (124, "Saint-Gilles-Croix-de-Vie", 46.700, -1.950),
    (125, "Les Sables-d'Olonne", 46.500, -1.800),
    (126, "Ile de Ré (Saint-Martin)", 46.200, -1.367),
    (127, "La Rochelle-Pallice", 46.167, -1.217),
    (128, "Ile d'Aix", 46.017, -1.183),
    (159, "Saint-Denis d'Oléron", 46.033, -1.367),
    (153, "Ile d'Oléron (La Cotinière)", 45.917, -1.333),
    (129, "Pointe de Gatseau", 45.783, -1.233),
    (130, "Cordouan", 45.583, -1.167),
    (131, "Royan", 45.617, -1.033),
    (132, "Pointe de Grave (Port-Bloc)", 45.567, -1.067),
    (133, "Richards", 45.467, -0.917),
    (162, "Laména", 45.217, -0.750),
    (160, "Pauillac", 45.200, -0.750),
    (161, "Bordeaux", 44.867, -0.550),
    (134, "Lacanau (Large)", 44.967, -1.333),
    (135, "Cap Ferret", 44.633, -1.250),
    (136, "Arcachon (Jetée d'Eyrac)", 44.667, -1.167),
    (137, "Biscarrosse", 44.367, -1.383),
    (138, "Mimizan", 44.133, -1.350),
    (139, "Vieux-Boucau", 43.783, -1.400),
    (140, "Boucau-Bayonne / Biarritz", 43.533, -1.533),
    (141, "Saint-Jean-de-Luz", 43.400, -1.683),
]


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions utilitaires
# ─────────────────────────────────────────────────────────────────────────────


def safe_filename(nom: str) -> str:
    """Convertit un nom de port en nom de fichier sûr."""
    s = nom
    # Remplacements accentués
    for old, new in [
        ("é", "e"),
        ("è", "e"),
        ("ê", "e"),
        ("ë", "e"),
        ("à", "a"),
        ("â", "a"),
        ("ä", "a"),
        ("î", "i"),
        ("ï", "i"),
        ("ô", "o"),
        ("ö", "o"),
        ("ù", "u"),
        ("û", "u"),
        ("ü", "u"),
        ("ç", "c"),
        ("É", "E"),
        ("È", "E"),
        ("Ê", "E"),
        ("À", "A"),
        ("Â", "A"),
        ("Î", "I"),
        ("Ô", "O"),
        ("Ù", "U"),
    ]:
        s = s.replace(old, new)
    # Caractères spéciaux → tiret
    s = re.sub(r"[/\\()\[\]{}]", "-", s)
    s = re.sub(r"['\",;:!?]", "", s)
    s = s.replace(" ", "-")
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s


def fetch_maree_info(port_id: int, max_retries: int = 3):
    """
    Récupère les données de marée depuis maree.info pour une semaine.

    Le HTML utilise des <br> entre les valeurs et <b> pour les PM.
    Format typique d'une ligne :
      <th>Mer.<br><b>11</b></th>
      <td>03h37<br><b>09h21</b><br>15h57<br><b>22h02</b></td>
      <td>2,91m<br><b>5,15m</b><br>3,22m<br><b>5,04m</b></td>

    Returns
    -------
    dict avec 'nom', 'coords', 'dates' (YYYYMMDD list), 'tides'.
    Chaque tide = (date_ymd, hh, mi, hauteur_m, 'PM'|'BM').
    None si échec réseau.
    """
    url = f"https://maree.info/{port_id}"
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return None

    result = {"nom": "", "coords": "", "dates": [], "tides": []}

    # Extraire le nom du port
    m = re.search(r'class="Port"[^>]*>([^<]+)', html)
    if m:
        result["nom"] = unescape(m.group(1).strip())

    # Extraire les coordonnées
    m_lat = re.search(r'itemprop="latitude"\s+content="([^"]+)"', html)
    m_lon = re.search(r'itemprop="longitude"\s+content="([^"]+)"', html)
    if m_lat and m_lon:
        result["coords"] = f"{m_lat.group(1)}°N {m_lon.group(1)}°E"

    # Extraire les dates depuis le JS
    m_dates = re.search(r"'Dates'\s*:\s*\[([\d,]+)\]", html)
    dates = []
    if m_dates:
        dates = [int(d) for d in m_dates.group(1).split(",")]
        result["dates"] = dates

    # Extraire les lignes de marée
    # Pattern: <tr class="MJ ..."> ... </tr>
    # Chaque ligne contient: <th>jour</th><td>heures</td><td>hauteurs</td><td>coeffs</td>
    rows = re.findall(r'<tr\s+class="MJ[^"]*"[^>]*>.*?</tr>', html, re.DOTALL)

    tides = []
    date_idx = 0
    for row in rows:
        # Extraire les cellules <td>
        cells = re.findall(r"<td>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 2:
            continue  # skip header row (has only <th>)

        # Vérifier que c'est une ligne de données (contient des heures)
        if not re.search(r"\d{2}h\d{2}", cells[0]):
            continue

        if date_idx >= len(dates):
            break
        date_ymd = dates[date_idx]
        date_idx += 1

        heures_html = cells[0]
        hauteurs_html = cells[1]

        # Parser les heures - séparer par <br>
        time_parts = re.split(r"<br\s*/?>", heures_html)
        # Parser les hauteurs - séparer par <br>
        height_parts = re.split(r"<br\s*/?>", hauteurs_html)

        if len(time_parts) != len(height_parts):
            continue

        for t_html, h_html in zip(time_parts, height_parts):
            # Déterminer PM (en gras) ou BM (pas en gras)
            is_pm = "<b>" in t_html

            # Extraire l'heure
            t_clean = re.sub(r"<[^>]+>", "", t_html).strip()
            h_clean = re.sub(r"<[^>]+>", "", h_html).strip()

            t_match = re.match(r"(\d{2})h(\d{2})", t_clean)
            h_match = re.match(r"(\d+,\d+)m", h_clean)

            if not t_match or not h_match:
                continue

            hh = int(t_match.group(1))
            mi = int(t_match.group(2))
            hauteur = float(h_match.group(1).replace(",", "."))
            kind = "PM" if is_pm else "BM"

            tides.append((date_ymd, hh, mi, hauteur, kind))

    result["tides"] = tides
    return result


def genere_port(port_id, nom, lat, lon, output_dir, atlas_base, verbose=True):
    """
    Génère le fichier .har pour un port.

    Returns
    -------
    (success: bool, filename: str, n_const: int, atlas: str, actual_lat: float, actual_lon: float, error: str)
    """
    fname = safe_filename(nom) + ".har"
    fpath = os.path.join(output_dir, fname)

    try:
        atlas_dir = find_best_atlas(atlas_base, lat, lon)
        atlas_name = Path(atlas_dir).name
        constituents, atlas_used, actual_lat, actual_lon = extract_constituents(
            atlas_dir, lat, lon
        )
        write_har(fpath, nom, lat, lon, constituents, atlas_used)
        n_const = len(constituents)

        if verbose:
            print(
                f"  OK  {nom:<40s}  {n_const:>3d} const  "
                f"({actual_lat:.3f}°N, {actual_lon:.3f}°E)  [{atlas_name}]"
            )

        return True, fname, n_const, atlas_name, actual_lat, actual_lon, ""

    except Exception as e:
        if verbose:
            print(f"  ERR {nom:<40s}  {e}")
        return False, fname, 0, "", lat, lon, str(e)


def valide_port(port_id, nom, lat, lon, har_dir, atlas_base, ref_data=None):
    """
    Valide les prédictions d'un port contre maree.info.

    Returns
    -------
    dict avec les résultats de validation.
    """
    fname = safe_filename(nom) + ".har"
    fpath = os.path.join(har_dir, fname)

    result = {
        "port_id": port_id,
        "nom": nom,
        "lat": lat,
        "lon": lon,
        "success": False,
        "error": "",
        "comparisons": [],
        "ecart_moyen": None,
        "ecart_max": None,
        "z0": None,
    }

    try:
        if not os.path.exists(fpath):
            result["error"] = "Fichier .har manquant"
            return result

        m = Maree.from_har(fpath)
        result["z0"] = m.z0

        # Récupérer les données de référence maree.info
        if ref_data is None:
            ref_data = fetch_maree_info(port_id)
            if ref_data is None:
                result["error"] = "Impossible de récupérer maree.info"
                return result
            time.sleep(0.5)  # politesse

        if not ref_data["tides"]:
            result["error"] = "Aucune donnée de marée trouvée sur maree.info"
            return result

        tz = timezone(timedelta(hours=1))  # UTC+1 (heure d'hiver)

        comparisons = []
        for date_ymd, hh, mi, h_ref, kind in ref_data["tides"]:
            year = date_ymd // 10000
            month = (date_ymd % 10000) // 100
            day = date_ymd % 100

            try:
                dt = datetime(year, month, day, hh, mi, tzinfo=tz)
            except ValueError:
                continue

            h_pred = m.hauteur(dt)
            ecart = h_pred - h_ref
            comparisons.append(
                {
                    "date": dt.strftime("%d/%m %Hh%M"),
                    "type": kind,
                    "h_pred": h_pred,
                    "h_ref": h_ref,
                    "ecart": ecart,
                }
            )

        result["comparisons"] = comparisons
        result["success"] = True

        if comparisons:
            ecarts = [abs(c["ecart"]) for c in comparisons]
            result["ecart_moyen"] = sum(ecarts) / len(ecarts)
            result["ecart_max"] = max(ecarts)

    except Exception as e:
        result["error"] = str(e)

    return result


def ecrire_rapport(resultats_gen, resultats_val, filepath):
    """Écrit le rapport de validation dans un fichier texte."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 90 + "\n")
        f.write("  RAPPORT DE GÉNÉRATION ET VALIDATION DES FICHIERS HARMONIQUES\n")
        f.write(f"  Date : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"  Référence : maree.info (données SHOM)\n")
        f.write("=" * 90 + "\n\n")

        # ── Résumé de génération ──
        f.write("─" * 90 + "\n")
        f.write("  RÉSUMÉ DE GÉNÉRATION\n")
        f.write("─" * 90 + "\n")
        n_ok = sum(1 for r in resultats_gen if r["success"])
        n_err = sum(1 for r in resultats_gen if not r["success"])
        f.write(f"  Ports traités : {len(resultats_gen)}\n")
        f.write(f"  Succès : {n_ok}\n")
        f.write(f"  Erreurs : {n_err}\n\n")

        if n_err > 0:
            f.write("  Ports en erreur :\n")
            for r in resultats_gen:
                if not r["success"]:
                    f.write(f"    - {r['nom']}: {r['error']}\n")
            f.write("\n")

        # ── Table de génération ──
        f.write("─" * 90 + "\n")
        f.write(
            f"  {'Port':<40s}  {'Lat':>8s}  {'Lon':>8s}  "
            f"{'Const':>5s}  {'Atlas':>12s}  {'Fichier':<30s}\n"
        )
        f.write("─" * 90 + "\n")
        for r in resultats_gen:
            status = "OK" if r["success"] else "ERR"
            f.write(
                f"  {r['nom']:<40s}  {r['actual_lat']:>8.3f}  {r['actual_lon']:>8.3f}  "
                f"{r['n_const']:>5d}  {r['atlas']:>12s}  {r['filename']:<30s}\n"
            )
        f.write("\n")

        # ── Validation détaillée ──
        if resultats_val:
            f.write("=" * 90 + "\n")
            f.write("  VALIDATION CONTRE MAREE.INFO\n")
            f.write("=" * 90 + "\n\n")

            # Résumé global
            valid_ports = [
                r for r in resultats_val if r["success"] and r["comparisons"]
            ]
            f.write(f"  Ports validés : {len(valid_ports)} / {len(resultats_val)}\n\n")

            # Table résumé
            f.write("─" * 90 + "\n")
            f.write(
                f"  {'Port':<35s}  {'Z0':>6s}  {'Écart moy':>10s}  "
                f"{'Écart max':>10s}  {'N pts':>5s}  {'Lat':>8s}  {'Lon':>8s}\n"
            )
            f.write("─" * 90 + "\n")

            for r in resultats_val:
                if r["success"] and r["comparisons"]:
                    f.write(
                        f"  {r['nom']:<35s}  {r['z0']:>6.2f}  "
                        f"{r['ecart_moyen']:>9.2f}m  {r['ecart_max']:>9.2f}m  "
                        f"{len(r['comparisons']):>5d}  "
                        f"{r['lat']:>8.3f}  {r['lon']:>8.3f}\n"
                    )
                elif not r["success"]:
                    f.write(
                        f"  {r['nom']:<35s}  {'---':>6s}  "
                        f"{'ERREUR':>10s}  {r['error'][:30]:<30s}\n"
                    )
            f.write("─" * 90 + "\n\n")

            # Détail par port
            for r in resultats_val:
                if not r["success"] or not r["comparisons"]:
                    continue

                f.write(f"  ── {r['nom']} (maree.info/{r['port_id']}) ──\n")
                f.write(f"     Coordonnées : {r['lat']:.3f}°N  {r['lon']:.3f}°E\n")
                f.write(f"     Z0 (auto) : {r['z0']:.3f} m\n")
                f.write(
                    f"     {'Date':>10s}  {'Type':>4s}  "
                    f"{'Prédit':>8s}  {'Réf':>8s}  {'Écart':>8s}\n"
                )
                f.write(f"     {'-' * 50}\n")

                for c in r["comparisons"]:
                    f.write(
                        f"     {c['date']:>10s}  {c['type']:>4s}  "
                        f"{c['h_pred']:>7.2f}m  {c['h_ref']:>7.2f}m  "
                        f"{c['ecart']:>+7.2f}m\n"
                    )

                f.write(
                    f"     Écart moyen : {r['ecart_moyen']:.2f}m  "
                    f"| max : {r['ecart_max']:.2f}m\n\n"
                )

            # ── Statistiques globales ──
            if valid_ports:
                all_ecarts = []
                for r in valid_ports:
                    all_ecarts.extend(abs(c["ecart"]) for c in r["comparisons"])

                f.write("=" * 90 + "\n")
                f.write("  STATISTIQUES GLOBALES\n")
                f.write("=" * 90 + "\n")
                f.write(f"  Nombre total de comparaisons : {len(all_ecarts)}\n")
                f.write(
                    f"  Écart moyen global : {sum(all_ecarts) / len(all_ecarts):.2f} m\n"
                )
                f.write(f"  Écart max global : {max(all_ecarts):.2f} m\n")
                f.write(
                    f"  Écart médian : {sorted(all_ecarts)[len(all_ecarts) // 2]:.2f} m\n"
                )

                # Distribution
                bins = [0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0]
                f.write(f"\n  Distribution des écarts absolus :\n")
                for b in bins:
                    n = sum(1 for e in all_ecarts if e <= b)
                    pct = 100 * n / len(all_ecarts)
                    f.write(
                        f"    ≤ {b:.1f}m : {n:>4d} / {len(all_ecarts)} ({pct:.0f}%)\n"
                    )

                # Classement des ports par écart
                f.write(f"\n  Classement par écart moyen :\n")
                sorted_ports = sorted(valid_ports, key=lambda r: r["ecart_moyen"])
                for i, r in enumerate(sorted_ports, 1):
                    f.write(
                        f"    {i:>3d}. {r['nom']:<35s}  "
                        f"moy={r['ecart_moyen']:.2f}m  max={r['ecart_max']:.2f}m\n"
                    )

        f.write("\n" + "=" * 90 + "\n")
        f.write(f"  Fin du rapport\n")
        f.write("=" * 90 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Programme principal
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Génère les fichiers .har pour tous les ports de France"
    )
    parser.add_argument(
        "--port", default=None, help="Nom du port (filtre partiel, ex: 'Brest')"
    )
    parser.add_argument(
        "--genere-only", action="store_true", help="Génère les .har sans validation"
    )
    parser.add_argument(
        "--valide-only",
        action="store_true",
        help="Valide les .har existants sans regénérer",
    )
    parser.add_argument(
        "--output-dir",
        default="har_ports",
        help="Répertoire de sortie (défaut: har_ports/)",
    )
    parser.add_argument(
        "--atlas-base",
        default="MARC_L1-ATLAS-AHRMONIQUES",
        help="Répertoire parent des atlas",
    )
    parser.add_argument(
        "--rapport",
        default="rapport_marees.txt",
        help="Fichier rapport (défaut: rapport_marees.txt)",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Ne pas récupérer les données maree.info (prédictions seules)",
    )
    args = parser.parse_args()

    # Filtrer les ports si demandé
    ports = PORTS
    if args.port:
        pattern = args.port.lower()
        ports = [p for p in PORTS if pattern in p[1].lower()]
        if not ports:
            print(f"Aucun port trouvé pour '{args.port}'")
            print("Ports disponibles :")
            for _, nom, _, _ in PORTS:
                print(f"  {nom}")
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"  Génération de fichiers harmoniques — {len(ports)} ports")
    print(f"  Atlas : {args.atlas_base}")
    print(f"  Sortie : {args.output_dir}/")
    print(f"{'=' * 70}\n")

    # ── Phase 1 : Génération ──
    resultats_gen = []
    if not args.valide_only:
        print("── PHASE 1 : Génération des fichiers .har ──\n")
        t_start = time.time()

        for port_id, nom, lat, lon in ports:
            success, filename, n_const, atlas, actual_lat, actual_lon, error = (
                genere_port(port_id, nom, lat, lon, args.output_dir, args.atlas_base)
            )

            resultats_gen.append(
                {
                    "port_id": port_id,
                    "nom": nom,
                    "lat": lat,
                    "lon": lon,
                    "success": success,
                    "filename": filename,
                    "n_const": n_const,
                    "atlas": atlas,
                    "actual_lat": actual_lat,
                    "actual_lon": actual_lon,
                    "error": error,
                }
            )

        elapsed = time.time() - t_start
        n_ok = sum(1 for r in resultats_gen if r["success"])
        print(f"\n  → {n_ok}/{len(ports)} fichiers générés en {elapsed:.0f}s\n")
    else:
        # Charger les infos depuis les fichiers existants
        for port_id, nom, lat, lon in ports:
            fname = safe_filename(nom) + ".har"
            fpath = os.path.join(args.output_dir, fname)
            exists = os.path.exists(fpath)
            resultats_gen.append(
                {
                    "port_id": port_id,
                    "nom": nom,
                    "lat": lat,
                    "lon": lon,
                    "success": exists,
                    "filename": fname,
                    "n_const": 0,
                    "atlas": "",
                    "actual_lat": lat,
                    "actual_lon": lon,
                    "error": "" if exists else "Fichier manquant",
                }
            )

    # ── Phase 2 : Validation ──
    resultats_val = []
    if not args.genere_only:
        print("── PHASE 2 : Validation contre maree.info ──\n")
        t_start = time.time()

        for i, (port_id, nom, lat, lon) in enumerate(ports):
            fname = safe_filename(nom) + ".har"
            fpath = os.path.join(args.output_dir, fname)

            if not os.path.exists(fpath):
                print(f"  SKIP {nom:<40s}  (fichier manquant)")
                resultats_val.append(
                    {
                        "port_id": port_id,
                        "nom": nom,
                        "lat": lat,
                        "lon": lon,
                        "success": False,
                        "error": "Fichier .har manquant",
                        "comparisons": [],
                        "ecart_moyen": None,
                        "ecart_max": None,
                        "z0": None,
                    }
                )
                continue

            # Récupérer les données maree.info
            if args.no_fetch:
                ref_data = None
            else:
                print(f"  [{i + 1:>3d}/{len(ports)}] {nom:<40s}", end="", flush=True)
                ref_data = fetch_maree_info(port_id)
                if ref_data is None:
                    print("  ERREUR fetch")
                    resultats_val.append(
                        {
                            "port_id": port_id,
                            "nom": nom,
                            "lat": lat,
                            "lon": lon,
                            "success": False,
                            "error": "Échec récupération maree.info",
                            "comparisons": [],
                            "ecart_moyen": None,
                            "ecart_max": None,
                            "z0": None,
                        }
                    )
                    continue
                time.sleep(0.3)  # politesse entre requêtes

            result = valide_port(
                port_id, nom, lat, lon, args.output_dir, args.atlas_base, ref_data
            )
            resultats_val.append(result)

            if result["success"] and result["comparisons"]:
                print(
                    f"  moy={result['ecart_moyen']:.2f}m  "
                    f"max={result['ecart_max']:.2f}m  "
                    f"Z0={result['z0']:.2f}m  "
                    f"({len(result['comparisons'])} pts)"
                )
            elif result["error"]:
                print(f"  ERREUR: {result['error'][:50]}")
            else:
                print(f"  (pas de données)")

        elapsed = time.time() - t_start
        n_val = sum(1 for r in resultats_val if r["success"] and r["comparisons"])
        print(f"\n  → {n_val}/{len(ports)} ports validés en {elapsed:.0f}s\n")

    # ── Phase 3 : Rapport ──
    print(f"── Écriture du rapport : {args.rapport} ──\n")
    ecrire_rapport(resultats_gen, resultats_val, args.rapport)

    # Résumé final
    if resultats_val:
        valid = [r for r in resultats_val if r["success"] and r["comparisons"]]
        if valid:
            all_moy = [r["ecart_moyen"] for r in valid]
            all_max = [r["ecart_max"] for r in valid]
            print(f"  Résumé : {len(valid)} ports validés")
            print(f"  Écart moyen des moyennes : {sum(all_moy) / len(all_moy):.2f} m")
            print(f"  Écart max global : {max(all_max):.2f} m")

            # Top 5 meilleurs
            sorted_v = sorted(valid, key=lambda r: r["ecart_moyen"])
            print(f"\n  Top 5 meilleurs :")
            for r in sorted_v[:5]:
                print(f"    {r['nom']:<35s}  moy={r['ecart_moyen']:.2f}m")
            print(f"\n  Top 5 pires :")
            for r in sorted_v[-5:]:
                print(f"    {r['nom']:<35s}  moy={r['ecart_moyen']:.2f}m")

    print(f"\n  Rapport détaillé : {args.rapport}")
    print(f"  Fichiers .har : {args.output_dir}/")
    print()


if __name__ == "__main__":
    main()
