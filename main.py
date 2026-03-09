#!/usr/bin/env python3
"""Exemple minimal : hauteur d'eau à Port-en-Bessin le 9 mars 2026 à 18h20."""

from datetime import datetime, timezone, timedelta
from maree import Maree

m = Maree.from_har("Brest.har")

# 9 mars 2026 à 18h20 heure locale (UTC+1)
dt = datetime(2026, 3, 9, 8, 0, tzinfo=timezone(timedelta(hours=1)))

h = m.hauteur(dt)
print(f"Hauteur d'eau à {m.name} le {dt.strftime('%d/%m/%Y à %Hh%M')} : {h:.2f} m")
