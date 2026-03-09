#!/usr/bin/env python3
"""
Génère une image de la courbe de marée pour une journée donnée.

Usage:
    python plot_maree.py <fichier.har> <date> [--tz <offset>] [--output <fichier.png>]

Exemples:
    python plot_maree.py Port-en-Bessin.har 2026-03-09
    python plot_maree.py Dielette.har 2026-03-09 --tz 1 --output maree_dielette.png
"""

import argparse
import warnings
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from maree import Maree

warnings.filterwarnings("ignore", "dtype.*align", DeprecationWarning)


def main():
    parser = argparse.ArgumentParser(
        description="Courbe de marée journalière à partir d'un fichier .har"
    )
    parser.add_argument("har", help="Fichier harmonique .har")
    parser.add_argument("date", help="Date au format YYYY-MM-DD")
    parser.add_argument(
        "--tz",
        type=int,
        default=1,
        help="Décalage horaire UTC (défaut: 1 = heure d'hiver France)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Nom du fichier image en sortie (défaut: <port>_<date>.png)",
    )
    args = parser.parse_args()

    date = datetime.strptime(args.date, "%Y-%m-%d")
    m = Maree.from_har(args.har)

    # Calcul marée du jour (pas de 5 min)
    times, heights, extremes = m.maree_jour(date, tz_offset_h=args.tz)

    # Nom du fichier de sortie
    if args.output:
        output = args.output
    else:
        safe_name = m.name.replace(" ", "_").replace("é", "e").replace("è", "e")
        output = f"{safe_name}_{args.date}.png"

    tz_label = f"UTC{args.tz:+d}"

    # ── Figure ──────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 5))

    # Courbe principale
    ax.plot(times, heights, color="#1a6db0", linewidth=2)

    # Remplissage sous la courbe
    ax.fill_between(times, 0, heights, alpha=0.15, color="#1a6db0")

    # Annotations PM / BM
    for kind, t, h in extremes:
        color = "#d62728" if kind == "PM" else "#2ca02c"
        label = "PM" if kind == "PM" else "BM"
        ax.plot(t, h, "o", color=color, markersize=7, zorder=5)
        t_local = t.strftime("%Hh%M")
        ax.annotate(
            f"{label}\n{t_local}\n{h:.2f} m",
            xy=(t, h),
            textcoords="offset points",
            xytext=(0, 18 if kind == "PM" else -32),
            ha="center",
            fontsize=8,
            fontweight="bold",
            color=color,
        )

    # Axe X : heures
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh", tz=times[0].tzinfo))
    ax.xaxis.set_minor_locator(mdates.MinuteLocator(byminute=[15, 30, 45]))
    plt.xticks(rotation=45, fontsize=8)

    # Axe Y
    ax.set_ylabel("Hauteur d'eau (m)", fontsize=11)
    ax.set_xlabel(f"Heure ({tz_label})", fontsize=11)

    # Grille
    ax.grid(True, which="major", linestyle="-", alpha=0.3)
    ax.grid(True, which="minor", linestyle=":", alpha=0.15)

    # Titre
    date_str = date.strftime("%d/%m/%Y")
    ax.set_title(f"Marée à {m.name} — {date_str}", fontsize=14, fontweight="bold")

    # Limites Y avec marge
    y_min = min(heights) - 0.3
    y_max = max(heights) + 0.5
    ax.set_ylim(max(0, y_min), y_max)

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)

    print(f"Image sauvegardée : {output}")


if __name__ == "__main__":
    main()
