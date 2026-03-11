#!/usr/bin/env python3
"""
Ajoute le Z0 pré-calculé à tous les fichiers .har existants.

Le Z0 (niveau moyen au-dessus du zéro des cartes) est calculé comme
Z0 = -LAT (Lowest Astronomical Tide sur 18.6 ans).

Usage:
    python add_z0_to_har.py [--har-dir har_ports]
"""

import argparse
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from maree import Maree


def add_z0_to_file(filepath: str) -> float | None:
    """Calcule Z0 et l'ajoute au fichier .har. Retourne z0 ou None si erreur."""
    warnings.filterwarnings("ignore")

    try:
        m = Maree.from_har(filepath)
    except Exception as e:
        print(f"  ERREUR lecture: {e}")
        return None

    z0 = m.z0

    # Lire le fichier
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Vérifier si z0 est déjà présent
    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("z0") and "=" in stripped:
            # Déjà présent, mettre à jour
            break
    else:
        # Ajouter z0 après la ligne longitude dans [port]
        new_lines = []
        in_port = False
        z0_added = False
        for line in lines:
            new_lines.append(line)
            stripped = line.strip()
            if stripped == "[port]":
                in_port = True
            elif stripped.startswith("[") and in_port:
                in_port = False
            elif in_port and stripped.lower().startswith("longitude") and not z0_added:
                new_lines.append(f"z0        = {z0:.4f}\n")
                z0_added = True

        if z0_added:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return z0

    # Si z0 existait déjà, mettre à jour la valeur
    new_lines = []
    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("z0") and "=" in stripped:
            new_lines.append(f"z0        = {z0:.4f}\n")
        else:
            new_lines.append(line)

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return z0


def main():
    parser = argparse.ArgumentParser(description="Ajoute Z0 à tous les fichiers .har")
    parser.add_argument("--har-dir", default="har_ports", help="Répertoire des .har")
    args = parser.parse_args()

    har_dir = Path(args.har_dir)
    if not har_dir.exists():
        print(f"Répertoire {har_dir} introuvable")
        sys.exit(1)

    files = sorted(har_dir.glob("*.har")) + sorted(har_dir.glob("_*.har"))
    # Dédupliquer
    seen = set()
    unique_files = []
    for f in files:
        if f.name not in seen:
            seen.add(f.name)
            unique_files.append(f)

    print(f"Ajout de Z0 à {len(unique_files)} fichiers .har ...")

    ok = 0
    for i, f in enumerate(unique_files):
        z0 = add_z0_to_file(str(f))
        if z0 is not None:
            print(f"  [{i + 1:3d}/{len(unique_files)}] {f.stem:<40s} z0 = {z0:+.4f} m")
            ok += 1
        else:
            print(f"  [{i + 1:3d}/{len(unique_files)}] {f.stem:<40s} SKIP")

    print(f"\nTerminé : {ok}/{len(unique_files)} fichiers mis à jour.")


if __name__ == "__main__":
    main()
