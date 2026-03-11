#!/usr/bin/env python3
"""Génération propre d'un fichier .har depuis les atlas SHOM/MARC.

Mode standard:
1) on prend le point océanique atlas le plus proche de (lat, lon),
2) on extrait amplitude/phase de chaque constituant à ce point,
3) on calcule Z0 via ``maree.Maree``,
4) on écrit un ``.har`` avec les vraies coordonnées utilisées.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class AtlasPoint:
    index: tuple[int, int]
    lat: float
    lon: float


def _list_constituent_files(atlas_dir: Path) -> list[Path]:
    files = sorted(atlas_dir.glob("*-XE-*-atlas.nc"))
    if not files:
        raise FileNotFoundError(f"Aucun fichier *-XE-* dans {atlas_dir}")
    return files


def _exact_ocean_point(
    atlas_dir: Path,
    lat: float,
    lon: float,
) -> AtlasPoint:
    import netCDF4

    files = _list_constituent_files(atlas_dir)
    m2_file = next((f for f in files if f.name.startswith("M2-")), files[0])

    with netCDF4.Dataset(str(m2_file)) as ds:
        grid_lat = ds.variables["latitude"][:]
        grid_lon = ds.variables["longitude"][:]
        amp = ds.variables["XE_a"][:]

    ocean_mask = ~np.ma.getmaskarray(amp)
    dist2 = (grid_lat - lat) ** 2 + (grid_lon - lon) ** 2
    valid_dist2 = np.where(ocean_mask, dist2, np.inf)
    if not np.isfinite(valid_dist2).any():
        raise ValueError(
            f"Aucun point océanique disponible dans l'atlas pour ({lat:.6f}, {lon:.6f})"
        )

    idx_raw = np.unravel_index(np.argmin(valid_dist2), valid_dist2.shape)
    idx = (int(idx_raw[0]), int(idx_raw[1]))

    point_lat = float(grid_lat[idx])
    point_lon = float(grid_lon[idx])

    return AtlasPoint(index=idx, lat=point_lat, lon=point_lon)


def _extract_constituents(
    atlas_dir: Path,
    point_index: tuple[int, int],
) -> dict[str, tuple[float, float]]:
    import netCDF4

    constituents: dict[str, tuple[float, float]] = {}
    for nc_file in _list_constituent_files(atlas_dir):
        cname = nc_file.name.split("-XE-")[0]
        if cname == "Z0":
            continue

        with netCDF4.Dataset(str(nc_file)) as ds:
            amp = ds.variables["XE_a"][point_index]
            phase = ds.variables["XE_G"][point_index]

        if np.ma.is_masked(amp) or np.ma.is_masked(phase):
            raise ValueError(
                f"Donnée manquante au point atlas pour le constituant {cname}"
            )

        amp_f = float(amp)
        phase_f = float(phase)
        if np.isnan(amp_f) or np.isnan(phase_f):
            raise ValueError(f"Donnée NaN au point atlas pour le constituant {cname}")

        constituents[cname] = (amp_f, phase_f)

    if not constituents:
        raise ValueError("Aucun constituant exploitable extrait de l'atlas")
    return constituents


def _find_atlas_with_exact_point(atlas_base_dir: Path, lat: float, lon: float) -> Path:
    candidates = sorted(
        (d for d in atlas_base_dir.iterdir() if d.is_dir()), reverse=True
    )
    if not candidates:
        raise FileNotFoundError(f"Aucun sous-répertoire atlas dans {atlas_base_dir}")

    best_dir: Path | None = None
    best_dist2 = np.inf
    for atlas_dir in candidates:
        try:
            point = _exact_ocean_point(atlas_dir, lat, lon)
        except (FileNotFoundError, ValueError):
            continue
        d2 = (point.lat - lat) ** 2 + (point.lon - lon) ** 2
        if d2 < best_dist2:
            best_dist2 = d2
            best_dir = atlas_dir

    if best_dir is None:
        raise ValueError(f"Aucun atlas valide trouvé pour ({lat:.6f}, {lon:.6f})")
    return best_dir


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", name.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "port"


def _write_har(
    output_path: Path,
    port_name: str,
    used_lat: float,
    used_lon: float,
    constituents: dict[str, tuple[float, float]],
    atlas_name: str,
) -> float:
    from maree import Maree

    maree_obj = Maree(constituents=constituents, name=port_name, lat=used_lat)
    z0 = maree_obj.z0
    sorted_constituents = sorted(
        constituents.items(), key=lambda item: (-item[1][0], item[0])
    )

    with output_path.open("w", encoding="utf-8") as f:
        f.write(f"# Fichier harmonique — {port_name}\n")
        f.write(f"# Source: atlas SHOM/MARC {atlas_name}\n")
        f.write(f"# Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(
            "# Phases référencées à Greenwich (UTC), convention Doodson/Schureman\n"
        )
        f.write("# Amplitude en mètres, phase en degrés\n\n")
        f.write("[port]\n")
        f.write(f"nom       = {port_name}\n")
        f.write(f"latitude  = {used_lat:.6f}\n")
        f.write(f"longitude = {used_lon:.6f}\n")
        f.write(f"z0        = {z0:.4f}\n\n")
        f.write("[constituants]\n")
        f.write(f"# {'nom':<12s} {'amplitude(m)':>12s}   {'phase(°)':>10s}\n")
        for cname, (amp, phase) in sorted_constituents:
            f.write(f"{cname:<12s} {amp:12.6f}   {phase:10.4f}\n")

    return float(z0)


# API publique (compatibilité avec scripts existants)
def find_best_atlas(atlas_base_dir: str, lat: float, lon: float) -> str:
    """Retourne l'atlas dont le point océanique le plus proche est optimal."""
    return str(_find_atlas_with_exact_point(Path(atlas_base_dir), lat, lon))


def extract_constituents(
    atlas_dir: str,
    lat: float,
    lon: float,
    rayon_recherche: float | None = None,
) -> tuple[dict[str, tuple[float, float]], str, float, float]:
    """Extrait les constituants au point océanique le plus proche.

    Le paramètre ``rayon_recherche`` est ignoré et conservé uniquement
    pour compatibilité ascendante.
    """
    del rayon_recherche
    atlas_path = Path(atlas_dir)
    point = _exact_ocean_point(atlas_path, lat, lon)
    constituents = _extract_constituents(atlas_path, point.index)
    return constituents, atlas_path.name, point.lat, point.lon


def write_har(
    filepath: str,
    nom: str,
    lat: float,
    lon: float,
    constituents: dict[str, tuple[float, float]],
    atlas_name: str,
) -> None:
    """Écrit un HAR en utilisant strictement les coordonnées fournies."""
    _write_har(
        output_path=Path(filepath),
        port_name=nom,
        used_lat=lat,
        used_lon=lon,
        constituents=constituents,
        atlas_name=atlas_name,
    )


def move_grid_point(
    atlas_base_dir: str,
    current_lat: float,
    current_lon: float,
    direction: str,
) -> tuple[dict[str, tuple[float, float]], str, float, float]:
    """Déplace le point de grille d'une case dans la direction donnée.

    Parameters
    ----------
    atlas_base_dir : str
        Répertoire parent des atlas.
    current_lat, current_lon : float
        Coordonnées actuelles (point de grille exact ou approché).
    direction : str
        'N', 'S', 'E' ou 'O' (nord, sud, est, ouest).

    Returns
    -------
    (constituents, atlas_name, new_lat, new_lon)
        Mêmes sorties que ``extract_constituents``.

    Raises
    ------
    ValueError
        Si le déplacement sort de la grille ou tombe sur la terre.
    """
    import netCDF4

    atlas_path = _find_atlas_with_exact_point(
        Path(atlas_base_dir), current_lat, current_lon
    )
    files = _list_constituent_files(atlas_path)
    m2_file = next((f for f in files if f.name.startswith("M2-")), files[0])

    with netCDF4.Dataset(str(m2_file)) as ds:
        grid_lat = ds.variables["latitude"][:]
        grid_lon = ds.variables["longitude"][:]
        amp = ds.variables["XE_a"][:]

    ocean_mask = ~np.ma.getmaskarray(amp)

    # Trouver l'index du point de grille le plus proche (parmi les océaniques)
    dist2 = (grid_lat - current_lat) ** 2 + (grid_lon - current_lon) ** 2
    valid_dist2 = np.where(ocean_mask, dist2, np.inf)
    idx_raw = np.unravel_index(np.argmin(valid_dist2), valid_dist2.shape)
    j, i = int(idx_raw[0]), int(idx_raw[1])

    # Déplacer d'une case (j croissant = nord, i croissant = est)
    dj, di = {"N": (1, 0), "S": (-1, 0), "E": (0, 1), "O": (0, -1)}[direction.upper()]
    nj, ni = j + dj, i + di

    if nj < 0 or nj >= grid_lat.shape[0] or ni < 0 or ni >= grid_lat.shape[1]:
        raise ValueError(f"Déplacement {direction} sort de la grille atlas")

    if not ocean_mask[nj, ni]:
        raise ValueError(
            f"Le point {direction} ({float(grid_lat[nj, ni]):.6f}, "
            f"{float(grid_lon[nj, ni]):.6f}) est sur la terre"
        )

    new_idx = (nj, ni)
    new_lat = float(grid_lat[new_idx])
    new_lon = float(grid_lon[new_idx])

    constituents = _extract_constituents(atlas_path, new_idx)
    return constituents, atlas_path.name, new_lat, new_lon


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère un fichier .har depuis les atlas SHOM/MARC"
    )
    parser.add_argument("--nom", required=True, help="Nom du port")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrés)")
    parser.add_argument(
        "--lon", type=float, required=True, help="Longitude (degrés, ouest négatif)"
    )
    parser.add_argument(
        "--atlas-dir",
        type=Path,
        default=None,
        help="Répertoire atlas spécifique (sinon auto via --atlas-base)",
    )
    parser.add_argument(
        "--atlas-base",
        type=Path,
        default=Path("MARC_L1-ATLAS-AHRMONIQUES"),
        help="Répertoire parent des atlas",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None, help="Fichier .har de sortie"
    )
    args = parser.parse_args()

    atlas_dir = args.atlas_dir or _find_atlas_with_exact_point(
        args.atlas_base, args.lat, args.lon
    )
    point = _exact_ocean_point(atlas_dir, args.lat, args.lon)
    constituents = _extract_constituents(atlas_dir, point.index)

    output_path = args.output or Path(f"{_safe_filename(args.nom)}.har")
    z0 = _write_har(
        output_path=output_path,
        port_name=args.nom,
        used_lat=point.lat,
        used_lon=point.lon,
        constituents=constituents,
        atlas_name=atlas_dir.name,
    )

    print(f"Atlas: {atlas_dir.name}")
    print(f"Point utilisé: ({point.lat:.6f}, {point.lon:.6f})")
    print(f"Constituants extraits: {len(constituents)}")
    print(f"Z0: {z0:.4f} m")
    print(f"Fichier HAR généré: {output_path}")


if __name__ == "__main__":
    main()
