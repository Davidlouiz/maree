#!/usr/bin/env python3
"""
Génère un fichier .har (harmoniques de marée) pour une position donnée,
en extrayant les constituants depuis les atlas SHOM/MARC.

Le Z0 (niveau moyen au-dessus du zéro des cartes) est calculé
automatiquement à partir des harmoniques : Z0 = -LAT (minimum
astronomique sur 18.6 ans).

Usage:
    python genere_har.py --nom "Port-en-Bessin" --lat 49.35 --lon -0.75
    python genere_har.py --nom "Diélette" --lat 49.55 --lon -1.867 --output Dielette.har
    python genere_har.py --nom "Arcachon" --lat 44.667 --lon -1.167 --atlas-dir MARC_L1-ATLAS-AHRMONIQUES/V1_AQUI
"""

import argparse
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np


def extract_constituents(
    atlas_dir: str,
    lat: float,
    lon: float,
    rayon_recherche: float = 0.15,
) -> tuple:
    """
    Extrait les harmoniques (amplitude, phase Greenwich) depuis un atlas.

    Stratégie de sélection du point atlas (best-M2) :

    1. Chercher tous les points océaniques dans un rayon de
       ``rayon_recherche``° autour de la position demandée.
    2. Retenir le point ayant la plus grande amplitude M2.
       Cela permet de s'affranchir des mailles d'estran (sable
       découvrant à marée basse) dont le M2 est artificiellement faible.
    3. Fallback : si aucun point dans le rayon, prendre le
       plus proche voisin océanique.

    Parameters
    ----------
    atlas_dir : str
        Répertoire contenant les fichiers NetCDF de l'atlas.
    lat, lon : float
        Coordonnées du port souhaité (degrés).
    rayon_recherche : float
        Rayon de recherche (degrés). Par défaut 0.15° ≈ 12-17 km.

    Returns
    -------
    constituents : dict  {nom: (amplitude_m, phase_deg)}
    atlas_name : str     Nom du sous-répertoire atlas utilisé
    actual_lat : float   Latitude du point océanique retenu
    actual_lon : float   Longitude du point océanique retenu
    """
    import netCDF4

    adir = Path(atlas_dir)
    xe_files = sorted(adir.glob("*-XE-*-atlas.nc"))
    if not xe_files:
        raise FileNotFoundError(f"Aucun fichier *-XE-* dans {adir}")

    # Lecture de la grille et de l'amplitude M2
    m2_file = next((f for f in xe_files if f.name.startswith("M2-")), xe_files[0])
    ds0 = netCDF4.Dataset(str(m2_file))
    grid_lat = ds0.variables["latitude"][:]
    grid_lon = ds0.variables["longitude"][:]
    amp0 = ds0.variables["XE_a"][:]
    ds0.close()

    dist = (grid_lat - lat) ** 2 + (grid_lon - lon) ** 2
    ocean_mask = ~np.ma.getmaskarray(amp0)
    amp0_data = np.ma.filled(amp0, 0.0)

    # ── Stratégie best-M2 : max M2 dans le rayon ──
    dist_lin = np.sqrt(dist)
    mask_rayon = (dist_lin < rayon_recherche) & ocean_mask

    if np.any(mask_rayon):
        amp_in_rayon = np.where(mask_rayon, amp0_data, 0.0)
        idx = np.unravel_index(np.argmax(amp_in_rayon), amp_in_rayon.shape)
    else:
        # Fallback : plus proche voisin océanique
        valid_dist = np.where(ocean_mask, dist, 1e10)
        idx = np.unravel_index(np.argmin(valid_dist), valid_dist.shape)
        if valid_dist[idx] > 1e9:
            raise ValueError(f"Aucun point océanique près de ({lat:.3f}, {lon:.3f})")

    actual_lat = float(grid_lat[idx])
    actual_lon = float(grid_lon[idx])
    dist_deg = float(dist_lin[idx])

    if dist_deg > 0.1:
        warnings.warn(
            f"Point atlas retenu à {dist_deg:.3f}° "
            f"de ({lat:.3f}, {lon:.3f}) → ({actual_lat:.3f}, {actual_lon:.3f})"
        )

    # Extraction de chaque constituant au point sélectionné
    constituents = {}
    for f in xe_files:
        cname = f.name.split("-XE-")[0]
        if cname == "Z0":
            continue

        ds = netCDF4.Dataset(str(f))
        a = ds.variables["XE_a"][idx]
        p = ds.variables["XE_G"][idx]
        ds.close()

        if np.ma.is_masked(a) or np.ma.is_masked(p):
            continue
        a, p = float(a), float(p)
        if np.isnan(a) or np.isnan(p):
            continue

        constituents[cname] = (a, p)

    return constituents, adir.name, actual_lat, actual_lon


def find_best_atlas(atlas_base_dir: str, lat: float, lon: float) -> str:
    """Sélectionne le meilleur atlas (résolution la plus fine) couvrant le point."""
    import netCDF4

    base = Path(atlas_base_dir)
    atlas_dirs = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)

    best = None
    best_dist = 1e10

    for ad in atlas_dirs:
        xe_files = list(ad.glob("*-XE-*-atlas.nc"))
        if not xe_files:
            continue

        m2_file = next((f for f in xe_files if f.name.startswith("M2-")), xe_files[0])
        ds = netCDF4.Dataset(str(m2_file))
        glat = ds.variables["latitude"][:]
        glon = ds.variables["longitude"][:]
        amp = ds.variables["XE_a"][:]
        ds.close()

        dist = (glat - lat) ** 2 + (glon - lon) ** 2
        ocean = ~np.ma.getmaskarray(amp)
        vd = np.where(ocean, dist, 1e10)
        min_idx = np.unravel_index(np.argmin(vd), vd.shape)
        d = float(vd[min_idx])

        if d < best_dist:
            best_dist = d
            best = ad

    if best is None:
        raise ValueError(f"Aucun atlas ne couvre ({lat:.3f}, {lon:.3f})")

    return str(best)


def write_har(
    filepath: str,
    nom: str,
    lat: float,
    lon: float,
    constituents: dict,
    atlas_name: str,
):
    """Écrit un fichier .har avec Z0 pré-calculé."""
    from maree import Maree

    # Trier par amplitude décroissante
    sorted_const = sorted(constituents.items(), key=lambda x: -x[1][0])

    # Calculer Z0 à partir des harmoniques
    maree_obj = Maree(constituents=constituents, name=nom, lat=lat)
    z0 = maree_obj.z0

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Fichier harmonique — {nom}\n")
        f.write(f"# Source: atlas MARC/SHOM {atlas_name}\n")
        f.write(f"# Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# Format: .har (harmoniques marée)\n")
        f.write(f"#\n")
        f.write(
            f"# Phases référencées à Greenwich (UTC), convention Doodson/Schureman\n"
        )
        f.write(f"# Amplitude en mètres, phase en degrés\n")
        f.write(
            f"# Z0 = niveau moyen au-dessus du zéro des cartes (LAT sur 18.6 ans)\n"
        )
        f.write(f"\n")
        f.write(f"[port]\n")
        f.write(f"nom       = {nom}\n")
        f.write(f"latitude  = {lat}\n")
        f.write(f"longitude = {lon}\n")
        f.write(f"z0        = {z0:.4f}\n")
        f.write(f"\n")
        f.write(f"[constituants]\n")
        f.write(f"# {'nom':<12s} {'amplitude(m)':>12s}   {'phase(°)':>10s}\n")
        for cname, (amp, phase) in sorted_const:
            f.write(f"{cname:<12s} {amp:12.6f}   {phase:10.4f}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Génère un fichier .har depuis les atlas SHOM/MARC"
    )
    parser.add_argument("--nom", required=True, help="Nom du port")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrés)")
    parser.add_argument(
        "--lon", type=float, required=True, help="Longitude (degrés, ouest = négatif)"
    )
    parser.add_argument(
        "--atlas-dir",
        default=None,
        help="Répertoire atlas spécifique (ex: .../V1_MANE)",
    )
    parser.add_argument(
        "--atlas-base",
        default="MARC_L1-ATLAS-AHRMONIQUES",
        help="Répertoire parent des atlas (défaut: MARC_L1-ATLAS-AHRMONIQUES)",
    )
    parser.add_argument(
        "--output", "-o", default=None, help="Fichier de sortie (défaut: <nom>.har)"
    )
    args = parser.parse_args()

    # Déterminer le répertoire atlas
    if args.atlas_dir:
        atlas_dir = args.atlas_dir
    else:
        print(f"Recherche du meilleur atlas pour ({args.lat:.3f}, {args.lon:.3f})...")
        atlas_dir = find_best_atlas(args.atlas_base, args.lat, args.lon)
        print(f"  → Atlas sélectionné : {Path(atlas_dir).name}")

    # Extraction
    print(f"Extraction des harmoniques depuis {Path(atlas_dir).name}...")
    constituents, atlas_name, actual_lat, actual_lon = extract_constituents(
        atlas_dir, args.lat, args.lon
    )
    print(f"  → {len(constituents)} constituants extraits")
    print(f"  → Point océanique : ({actual_lat:.4f}°N, {actual_lon:.4f}°E)")

    # Fichier de sortie
    if args.output:
        output = args.output
    else:
        safe_name = args.nom.replace(" ", "-").replace("é", "e").replace("è", "e")
        output = f"{safe_name}.har"

    # Écriture
    write_har(output, args.nom, args.lat, args.lon, constituents, atlas_name)

    # Calcul du Z0 pour affichage
    from maree import Maree

    m = Maree.from_har(output)
    print(f"\nFichier sauvegardé : {output}")
    print(f"  {len(constituents)} constituants")
    print(f"  Z0 = {m.z0:.4f} m (calculé automatiquement, LAT 18.6 ans)")


if __name__ == "__main__":
    main()
